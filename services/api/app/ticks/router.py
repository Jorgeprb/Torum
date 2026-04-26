from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.candles.service import candle_to_read
from app.db.session import get_db
from app.mt5.status_store import mt5_status_store
from app.ticks.schemas import TickBatchRequest, TickBatchResponse, TickInput, TickRead
from app.ticks.service import TickIngestionError, get_recent_ticks, ingest_tick_batch
from app.websockets.manager import market_ws_manager

router = APIRouter(prefix="/ticks", tags=["ticks"])


async def broadcast_candle_reads(candles: list[dict[str, object]]) -> None:
    for candle in candles:
        await market_ws_manager.broadcast_candle_update(candle)


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
    return TickBatchResponse(
        received=received_ticks,
        inserted=inserted_ticks,
        duplicates_ignored=duplicates,
        candles_updated=len(candles),
        accepted_ticks=inserted_ticks,
        updated_candles=len(candles),
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
