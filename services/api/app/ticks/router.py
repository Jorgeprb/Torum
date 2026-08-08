from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.candles.service import candle_to_read
from app.core.config import get_settings
from app.core.decision_log import trace_event, trace_exception
from app.core.service_auth import require_service_token
from app.alerts.evaluator import PriceAlertEvaluator
from app.alerts.push import PushNotificationService
from app.db.session import SessionLocal, get_db
from app.mt5.status_store import mt5_status_store
from app.market_data.tick_time import tick_time_msc_from_datetime
from app.risk.snapshot import RiskSnapshotService
from app.settings.trading_service import get_global_trading_settings
from app.strategies.auto_runner import run_torum_v1_with_durable_fallback
from app.strategies.ath import update_symbol_ath_from_candles
from app.strategies.candle_trigger import symbols_with_newly_closed_m5
from app.strategies.notifications import notify_torum_v1_unlocks_for_symbols
from app.ticks.schemas import TickBatchRequest, TickBatchResponse, TickInput, TickRead
from app.trade_jobs.service import enqueue_trade_job
from app.ticks.service import TickIngestionError, get_recent_ticks, ingest_tick_batch
from app.websockets.manager import market_ws_manager

router = APIRouter(prefix="/ticks", tags=["ticks"])


async def evaluate_and_dispatch_price_alerts(inserted_rows: list[dict[str, object]]) -> None:
    """Evaluate and deliver alerts only after the trading task has finished.

    FastAPI does not start any background task until the response body is ready.
    Keeping alert SQL in the request handler therefore delayed the supposedly
    first strategy task.  This helper owns its DB session and is queued after
    the entry evaluation, including all push-network work.
    """

    with SessionLocal() as db:
        events = PriceAlertEvaluator(db).evaluate_inserted_ticks(inserted_rows)
    for event in events:
        event_payload = event.model_dump(mode="json")
        await market_ws_manager.broadcast_price_alert_triggered(event_payload)
        with SessionLocal() as db:
            PushNotificationService(db).send_price_alert(event)


def mark_risk_snapshots_dirty(symbols: list[str]) -> None:
    """Invalidate risk snapshots after entry processing, never before it."""

    with SessionLocal() as db:
        for symbol in sorted({item.upper() for item in symbols if item}):
            RiskSnapshotService(db).mark_dirty(symbol)
        db.commit()


async def broadcast_candle_reads(candles: list[dict[str, object]]) -> None:
    for candle in candles:
        await market_ws_manager.broadcast_candle_update(candle)


async def broadcast_tick_reads(ticks: list[dict[str, object]]) -> None:
    for tick in ticks:
        await market_ws_manager.broadcast_market_tick(tick)


@router.post("", response_model=TickBatchResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_service_token)])
def ingest_tick(
    payload: TickInput,
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
) -> TickBatchResponse:
    source = payload.source or "MT5"
    batch = TickBatchRequest(source=source, ticks=[payload])
    return ingest_ticks_batch(batch, background_tasks, db)


@router.post("/batch", response_model=TickBatchResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_service_token)])
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
        trace_exception("tick_ingestion", "batch_rejected", exc, source=payload.source, received=len(payload.ticks))
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        trace_exception("tick_ingestion", "batch_failed", exc, source=payload.source, received=len(payload.ticks))
        raise

    ath_symbols_updated = update_symbol_ath_from_candles(db, candles)
    if ath_symbols_updated:
        trace_event("ath", "incremental_ath_updated", symbols=sorted(ath_symbols_updated))

    candle_payloads = [candle_to_read(candle).model_dump() for candle in candles]
    inserted_symbols = sorted({str(row["internal_symbol"]) for row in inserted_rows}) if inserted_rows else []
    settings = get_settings()
    strategy_symbols = (
        symbols_with_newly_closed_m5(candles)
        if inserted_rows and settings.strategy_run_on_candle_close_only
        else inserted_symbols
    )
    if strategy_symbols:
        trace_event(
            "strategy_trigger",
            "auto_run_scheduled",
            symbols=strategy_symbols,
            trigger_mode="candle_close" if settings.strategy_run_on_candle_close_only else "tick",
            source=payload.source,
            received=received_ticks,
            inserted=inserted_ticks,
            inserted_symbols=inserted_symbols,
            m5_candle_buckets=[
                {
                    "symbol": candle.internal_symbol,
                    "time": candle.time,
                    "open": candle.open,
                    "high": candle.high,
                    "low": candle.low,
                    "close": candle.close,
                }
                for candle in candles
                if str(candle.timeframe).upper() == "M5"
                and candle.internal_symbol in strategy_symbols
            ],
        )
        # FastAPI background tasks are intentionally fast but not durable if the
        # API process terminates after acknowledging this tick batch. Create a
        # delayed, idempotent fallback per M5 bucket first; the immediate task
        # retires it after a successful run. A crash therefore causes a safe
        # retry instead of silently losing the candle-close entry.
        latest_m5_bucket_by_symbol: dict[str, datetime] = {}
        for candle in candles:
            if str(candle.timeframe).upper() != "M5" or candle.internal_symbol not in strategy_symbols:
                continue
            current = latest_m5_bucket_by_symbol.get(candle.internal_symbol)
            if current is None or candle.time > current:
                latest_m5_bucket_by_symbol[candle.internal_symbol] = candle.time
        fallback_job_ids: list[int] = []
        try:
            for symbol in strategy_symbols:
                bucket = latest_m5_bucket_by_symbol.get(symbol)
                bucket_epoch = int(bucket.timestamp()) if bucket is not None else int(datetime.now(UTC).timestamp())
                job = enqueue_trade_job(
                    db,
                    job_type="RUN_TORUM_STRATEGY",
                    idempotency_key=f"run-torum:{symbol}:{bucket_epoch}",
                    payload={"symbols": [symbol], "m5_bucket_epoch": bucket_epoch},
                    run_after=datetime.now(UTC) + timedelta(seconds=5),
                    reactivate_completed=False,
                )
                fallback_job_ids.append(job.id)
            db.commit()
        except Exception as exc:  # noqa: BLE001 - immediate path must still run
            db.rollback()
            fallback_job_ids = []
            trace_exception(
                "strategy_trigger",
                "durable_fallback_enqueue_failed",
                exc,
                symbols=strategy_symbols,
            )

        # This remains the first background task. Push notifications, websocket
        # fan-out and unlock diagnostics are non-critical and may perform slow
        # network I/O; none of them may delay an entry after an M5 close.
        background_tasks.add_task(
            run_torum_v1_with_durable_fallback,
            strategy_symbols,
            fallback_job_ids,
        )

    background_tasks.add_task(broadcast_candle_reads, candle_payloads)
    background_tasks.add_task(broadcast_tick_reads, inserted_rows)
    if inserted_rows:
        background_tasks.add_task(evaluate_and_dispatch_price_alerts, inserted_rows)
    if inserted_symbols:
        background_tasks.add_task(notify_torum_v1_unlocks_for_symbols, inserted_symbols)

    last_tick_time_by_symbol: dict[str, object] = {}
    for row in inserted_rows:
        last_tick_time_by_symbol[str(row["internal_symbol"])] = row["time"]

    account_trade_mode = payload.account.trade_mode if payload.account else "UNKNOWN"
    previous_account = mt5_status_store.get().account
    previous_balance = previous_account.balance if previous_account else None
    status_snapshot = mt5_status_store.update_from_tick_batch(
        source=payload.source,
        inserted_ticks=inserted_ticks,
        last_tick_time_by_symbol=last_tick_time_by_symbol,
        account_trade_mode=account_trade_mode,
        account=payload.account,
    )
    next_balance = status_snapshot.account.balance if status_snapshot and status_snapshot.account else None
    if next_balance is not None and next_balance != previous_balance:
        background_tasks.add_task(mark_risk_snapshots_dirty, ["XAUUSD", "XAUEUR"])
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
