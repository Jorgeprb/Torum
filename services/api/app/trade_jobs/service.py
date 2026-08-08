from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from threading import Event, Thread
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.trade_jobs.models import TradeJob

logger = logging.getLogger(__name__)

PENDING_STATUSES = {"PENDING", "RETRY"}


def enqueue_trade_job(
    db: Session,
    *,
    job_type: str,
    idempotency_key: str,
    payload: dict[str, Any],
    run_after: datetime | None = None,
    reactivate_completed: bool = False,
) -> TradeJob:
    now = datetime.now(UTC)
    job = db.scalar(select(TradeJob).where(TradeJob.idempotency_key == idempotency_key).limit(1))
    if job is None:
        candidate = TradeJob(
            job_type=job_type,
            idempotency_key=idempotency_key,
            status="PENDING",
            payload_json=payload,
            next_run_at=run_after or now,
            rerun_requested=False,
        )
        # A SAVEPOINT prevents an idempotency race from rolling back the
        # caller's order/position transaction.
        try:
            with db.begin_nested():
                db.add(candidate)
                db.flush()
            return candidate
        except IntegrityError:
            job = db.scalar(select(TradeJob).where(TradeJob.idempotency_key == idempotency_key).limit(1))
            if job is None:
                raise

    job.job_type = job_type
    job.payload_json = payload
    if job.status == "RUNNING":
        # Do not steal a job that another worker already owns.  For coalesced
        # jobs (risk recompute), request exactly one follow-up run instead.
        if reactivate_completed:
            job.rerun_requested = True
            job.next_run_at = run_after or now
        return job

    if job.status in PENDING_STATUSES:
        job.next_run_at = min(job.next_run_at, run_after or now) if job.next_run_at else (run_after or now)
        job.last_error = None
        return job

    if reactivate_completed:
        job.status = "PENDING"
        job.next_run_at = run_after or now
        job.locked_at = None
        job.last_error = None
        job.attempts = 0
        job.rerun_requested = False
    return job



class TradeJobWorker:
    def __init__(self) -> None:
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._recover_stale_jobs()
        self._thread = Thread(target=self._run, name="torum-trade-job-worker", daemon=False)
        self._thread.start()
        logger.info("Trade job worker started")

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                logger.error("Trade job worker did not stop within %.1fs", timeout)
        logger.info("Trade job worker stopped")

    def _recover_stale_jobs(self) -> None:
        stale_before = datetime.now(UTC) - timedelta(minutes=5)
        with SessionLocal() as db:
            jobs = list(
                db.scalars(
                    select(TradeJob).where(
                        TradeJob.status == "RUNNING",
                        or_(TradeJob.locked_at.is_(None), TradeJob.locked_at < stale_before),
                    )
                )
            )
            for job in jobs:
                job.status = "RETRY"
                job.locked_at = None
                job.rerun_requested = False
                job.next_run_at = datetime.now(UTC)
                job.last_error = "Recovered stale RUNNING job after process restart"
            if jobs:
                db.commit()
                logger.warning("Recovered %s stale trade jobs", len(jobs))

    def _run(self) -> None:
        settings = get_settings()
        while not self._stop.is_set():
            job_id = self._claim_one()
            if job_id is None:
                self._stop.wait(max(0.1, settings.trade_job_poll_interval_seconds))
                continue
            self._execute(job_id)

    def _claim_one(self) -> int | None:
        now = datetime.now(UTC)
        with SessionLocal() as db:
            stmt = (
                select(TradeJob)
                .where(
                    TradeJob.status.in_(["PENDING", "RETRY"]),
                    TradeJob.next_run_at <= now,
                )
                .order_by(TradeJob.next_run_at, TradeJob.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            job = db.scalar(stmt)
            if job is None:
                return None
            job.status = "RUNNING"
            job.locked_at = now
            job.attempts += 1
            db.commit()
            return job.id

    def _execute(self, job_id: int) -> None:
        settings = get_settings()
        try:
            with SessionLocal() as db:
                job = db.get(TradeJob, job_id)
                if job is None:
                    return
                _dispatch_job(db, job)
                db.flush()
                # Lock and reload the row before finalizing.  This closes the
                # small race where a concurrent mark_dirty arrives between a
                # plain refresh and the COMPLETED update.
                job = db.scalar(
                    select(TradeJob)
                    .where(TradeJob.id == job_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                if job is None:
                    return
                if job.rerun_requested:
                    job.status = "PENDING"
                    job.rerun_requested = False
                    job.next_run_at = datetime.now(UTC)
                else:
                    job.status = "COMPLETED"
                job.locked_at = None
                job.last_error = None
                db.commit()
                logger.info(
                    "trade_job_completed id=%s type=%s attempts=%s rerun=%s",
                    job.id,
                    job.job_type,
                    job.attempts,
                    job.status == "PENDING",
                )
        except Exception as exc:  # noqa: BLE001 - durable worker boundary
            logger.exception("trade_job_failed id=%s", job_id)
            with SessionLocal() as db:
                job = db.get(TradeJob, job_id)
                if job is None:
                    return
                job.locked_at = None
                job.rerun_requested = False
                job.last_error = str(exc)[:4000]
                _record_domain_failure(db, job, str(exc))
                if job.attempts >= settings.trade_job_max_attempts:
                    job.status = "FAILED"
                else:
                    job.status = "RETRY"
                    delay = min(300, 2 ** max(0, job.attempts - 1))
                    job.next_run_at = datetime.now(UTC) + timedelta(seconds=delay)
                db.commit()


def _record_domain_failure(db: Session, job: TradeJob, error: str) -> None:
    if job.job_type != "APPLY_TP":
        return
    from app.orders.models import Order
    from app.positions.models import Position

    position = db.get(Position, int(job.payload_json.get("position_id") or 0))
    order = db.get(Order, int(job.payload_json.get("order_id") or 0))
    if position is None or order is None:
        return
    _set_tp_status(position, order, "FAILED", error=error[:1000])


def _dispatch_job(db: Session, job: TradeJob) -> None:
    if job.job_type == "APPLY_TP":
        _apply_tp(db, job.payload_json)
        return
    if job.job_type == "ENRICH_CLOSE":
        _enrich_close(db, job.payload_json)
        return
    if job.job_type == "RECOMPUTE_RISK":
        _recompute_risk(db, job.payload_json)
        return
    if job.job_type == "NOTIFY_ORDER":
        _notify_order(db, job.payload_json)
        return
    if job.job_type == "RUN_TORUM_STRATEGY":
        from app.strategies.auto_runner import run_torum_v1_for_symbols

        symbols = job.payload_json.get("symbols")
        normalized = [str(symbol).upper() for symbol in symbols] if isinstance(symbols, list) else []
        if not normalized:
            raise RuntimeError("missing_symbols_for_torum_strategy_job")
        if not run_torum_v1_for_symbols(normalized):
            raise RuntimeError("torum_strategy_batch_incomplete")
        return
    raise RuntimeError(f"Unknown trade job type: {job.job_type}")


def _apply_tp(db: Session, payload: dict[str, Any]) -> None:
    from app.mt5.client import MT5BridgeClient, MT5BridgeClientError
    from app.orders.models import Order
    from app.positions.models import Position

    position_id = int(payload["position_id"])
    order_id = int(payload["order_id"])
    final_tp = float(payload["final_tp"])
    position = db.get(Position, position_id)
    order = db.get(Order, order_id)
    if position is None or order is None:
        return
    if position.status != "OPEN":
        return
    if position.mode == "PAPER":
        position.tp = final_tp
        order.tp = final_tp
        _set_tp_status(position, order, "UPDATED")
        return
    if position.mt5_position_ticket is None:
        raise RuntimeError("missing_mt5_position_ticket_for_tp")
    try:
        response = MT5BridgeClient().modify_position_tp(
            position.mt5_position_ticket,
            {
                "internal_symbol": position.internal_symbol,
                "broker_symbol": position.broker_symbol,
                "side": position.side,
                "mode": position.mode,
                "tp": final_tp,
                "sl": position.sl or 0,
                "magic_number": position.magic_number,
                "comment": "tp-final",
            },
        )
    except MT5BridgeClientError as exc:
        _set_tp_status(position, order, "FAILED", error=str(exc))
        raise
    if not response.get("ok"):
        error = str(response.get("comment") or "MT5 TP rejected")
        _set_tp_status(position, order, "FAILED", error=error, response=response)
        raise RuntimeError(error)
    confirmed_tp = _float_or_none(response.get("price")) or final_tp
    position.tp = confirmed_tp
    order.tp = confirmed_tp
    _set_tp_status(position, order, "UPDATED", response=response)


def _set_tp_status(
    position: Any,
    order: Any,
    status: str,
    *,
    error: str | None = None,
    response: dict[str, Any] | None = None,
) -> None:
    update = {"tp_status": status, "tp_update_error": error}
    if response is not None:
        update["tp_modify_response"] = response
    position.raw_payload_json = {**(position.raw_payload_json or {}), **update}
    order.response_payload_json = {**(order.response_payload_json or {}), **update}


def _enrich_close(db: Session, payload: dict[str, Any]) -> None:
    from app.mt5.client import MT5BridgeClient
    from app.positions.models import Position
    from app.positions.service import _apply_close_deal

    position = db.get(Position, int(payload["position_id"]))
    if position is None:
        return
    ticket = int(payload["ticket"])
    deal_ticket = payload.get("deal_ticket")
    response = MT5BridgeClient().get_close_deal(ticket, int(deal_ticket) if deal_ticket is not None else None)
    close_deal = response.get("close_deal") if isinstance(response, dict) else None
    deals = response.get("deals") if isinstance(response, dict) else None
    if isinstance(deals, list) and deals:
        from app.positions.service import _aggregate_position_deals

        normalized_deals = [deal for deal in deals if isinstance(deal, dict)]
        close_deal = _aggregate_position_deals(normalized_deals) if normalized_deals else close_deal
    if not isinstance(close_deal, dict):
        raise RuntimeError(str(response.get("comment") if isinstance(response, dict) else "close_deal_missing"))
    _apply_close_deal(position, close_deal)
    position.status = "CLOSED"
    position.raw_payload_json = {
        **(position.raw_payload_json or {}),
        "close_enrichment_status": "UPDATED",
    }


def _recompute_risk(db: Session, payload: dict[str, Any]) -> None:
    from app.risk.snapshot import RiskSnapshotService

    RiskSnapshotService(db).recompute(str(payload["symbol"]), source=str(payload.get("source") or "ALL"))


def _notify_order(db: Session, payload: dict[str, Any]) -> None:
    from app.alerts.push import PushNotificationService
    from app.orders.models import Order

    order = db.get(Order, int(payload["order_id"]))
    if order is None or order.source != "STRATEGY" or order.user_id is None:
        return
    response_payload = order.response_payload_json or {}
    if response_payload.get("bot_order_push_sent_at"):
        return
    sent, _failed = PushNotificationService(db).send_bot_order_executed(
        order.user_id,
        symbol=order.internal_symbol,
        side=order.side,
        volume=float(order.volume),
        price=order.executed_price or order.requested_price,
        tp=order.tp,
        order_id=order.id,
    )
    if sent > 0:
        response_payload["bot_order_push_sent_at"] = datetime.now(UTC).isoformat()
        order.response_payload_json = response_payload


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


trade_job_worker = TradeJobWorker()
