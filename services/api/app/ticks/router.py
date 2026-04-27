from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.candles.service import candle_to_read
from app.alerts.evaluator import PriceAlertEvaluator
from app.alerts.push import PushNotificationService
from app.db.session import get_db
from app.mt5.status_store import mt5_status_store
from app.market_data.tick_time import tick_time_msc_from_datetime
from app.settings.trading_service import get_global_trading_settings
from app.ticks.schemas import TickBatchRequest, TickBatchResponse, TickInput, TickRead
from app.ticks.service import TickIngestionError, get_recent_ticks, ingest_tick_batch
from app.websockets.manager import market_ws_manager

router = APIRouter(prefix="/ticks", tags=["ticks"])


async def broadcast_candle_reads(candles: list[dict[str, object]]) -> None:
    for candle in candles:
        await market_ws_manager.broadcast_candle_update(candle)


async def broadcast_tick_reads(ticks: list[dict[str, object]]) -> None:
    for tick in ticks:
        await market_ws_manager.broadcast_market_tick(tick)


@router.post("", response_model=TickBatchResponse, status_code=status.HTTP_201_CREATED)
def ingest_tick(
    payload: TickInput,
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
) -> TickBatchResponse:
    source = payload.source or "MT5"
    batch = TickBatchRequest(source=source, ticks=[payload])
    return ingest_ticks_batch(batch, background_tasks, db)


@router.post("/batch", response_model=TickBatchResponse, status_code=status.HTTP_201_CREATED)
def ingest_ticks_batch(
    payload: TickBatchRequest,
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
) -> TickBatchResponse:
    active_source = get_global_trading_settings(db).market_data_source
    if payload.source.upper() == "MOCK" and active_source == "MT5":
        return TickBatchResponse(
            received=len(payload.ticks),
            inserted=0,
            duplicates_ignored=0,
            candles_updated=0,
            accepted_ticks=0,
            updated_candles=0,
            source=payload.source,
            errors=["MOCK ticks ignored because market_data_source=MT5"],
        )

    try:
        received_ticks, inserted_ticks, candles, inserted_rows = ingest_tick_batch(db, payload)
    except TickIngestionError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        raise

    candle_payloads = [candle_to_read(candle).model_dump() for candle in candles]
    background_tasks.add_task(broadcast_candle_reads, candle_payloads)
    background_tasks.add_task(broadcast_tick_reads, inserted_rows)
    alert_events = PriceAlertEvaluator(db, push_service=PushNotificationService(db)).evaluate_inserted_ticks(inserted_rows)
    for event in alert_events:
        background_tasks.add_task(market_ws_manager.broadcast_price_alert_triggered, event.model_dump(mode="json"))

    last_tick_time_by_symbol: dict[str, object] = {}
    for row in inserted_rows:
        last_tick_time_by_symbol[str(row["internal_symbol"])] = row["time"]

    account_trade_mode = payload.account.trade_mode if payload.account else "UNKNOWN"
    mt5_status_store.update_from_tick_batch(
        source=payload.source,
        inserted_ticks=inserted_ticks,
        last_tick_time_by_symbol=last_tick_time_by_symbol,  # type: ignore[arg-type]
        account_trade_mode=account_trade_mode,
    )
    if inserted_rows:
        last_tick_time = max(row["time"] for row in inserted_rows)
        background_tasks.add_task(market_ws_manager.broadcast_market_status, True, payload.source, last_tick_time)

    duplicates = received_ticks - inserted_ticks
    min_time = min((row["time"] for row in inserted_rows), default=None)
    max_time = max((row["time"] for row in inserted_rows), default=None)
    max_time_msc = max((int(row["time_msc"]) for row in inserted_rows if row.get("time_msc") is not None), default=None)
    latest_row = max(inserted_rows, key=lambda row: (int(row.get("time_msc") or 0), row["time"]), default=None)
    return TickBatchResponse(
        received=received_ticks,
        inserted=inserted_ticks,
        duplicates_ignored=duplicates,
        candles_updated=len(candles),
        accepted_ticks=inserted_ticks,
        updated_candles=len(candles),
        source=payload.source,
        min_time=min_time,
        max_time=max_time,
        max_time_msc=max_time_msc,
        last_bid=float(latest_row["bid"]) if latest_row and latest_row.get("bid") is not None else None,
        last_ask=float(latest_row["ask"]) if latest_row and latest_row.get("ask") is not None else None,
        last_broker_symbol=str(latest_row["broker_symbol"]) if latest_row else None,
    )


@router.get("", response_model=list[TickRead])
def get_ticks(
    db: Annotated[Session, Depends(get_db)],
    symbol: str = Query(min_length=3),
    limit: int = Query(default=1000, ge=1, le=10000),
) -> list[TickRead]:
    return [
        TickRead(
            time=tick.time,
            time_msc=tick.time_msc or tick_time_msc_from_datetime(tick.time),
            internal_symbol=tick.internal_symbol,
            broker_symbol=tick.broker_symbol,
            bid=tick.bid,
            ask=tick.ask,
            last=tick.last,
            volume=tick.volume,
            source=tick.source,
        )
        for tick in get_recent_ticks(db, symbol=symbol, limit=limit)
    ]
