import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from time import sleep

from sqlalchemy import select

from app.db.session import SessionLocal
from app.core.decision_log import trace_event, trace_exception
from app.strategies.models import StrategyConfig
from app.trade_jobs.models import TradeJob
from app.strategies.repository import get_global_strategy_settings
from app.strategies.runner import StrategyRunner
from app.strategies.torum_v1 import MADRID_TZ, TORUM_V1_KEY, TorumV1StatusService
from app.users.models import User

logger = logging.getLogger(__name__)


def run_torum_v1_for_symbols(symbols: list[str]) -> bool:
    normalized_symbols = sorted({symbol.upper() for symbol in symbols if symbol})
    if not normalized_symbols:
        trace_event("auto_runner", "batch_skipped", reason="empty_symbol_list", raw_symbols=symbols)
        return True

    trace_event("auto_runner", "batch_started", symbols=normalized_symbols)
    with SessionLocal() as db:
        settings = get_global_strategy_settings(db)
        if not settings.strategies_enabled:
            trace_event("auto_runner", "batch_skipped", reason="strategies_disabled", symbols=normalized_symbols)
            return True
        configs = list(
            db.scalars(
                select(StrategyConfig).where(
                    StrategyConfig.strategy_key == TORUM_V1_KEY,
                    StrategyConfig.enabled.is_(True),
                    StrategyConfig.internal_symbol.in_(normalized_symbols),
                )
            )
        )
        execution_configs, duplicate_configs = _latest_configs_by_execution_scope(configs)
        execution_config_ids = [int(config.id) for config in execution_configs if config.id is not None]
        trace_event(
            "auto_runner",
            "configs_loaded",
            symbols=normalized_symbols,
            configs=[
                {
                    "config_id": config.id,
                    "user_id": config.user_id,
                    "symbol": config.internal_symbol,
                    "mode": config.mode,
                    "revision": config.revision,
                    "enabled": config.enabled,
                    "selected_for_execution": config in execution_configs,
                }
                for config in configs
            ],
        )
        for duplicate in duplicate_configs:
            trace_event(
                "auto_runner",
                "duplicate_config_skipped",
                config_id=duplicate.id,
                user_id=duplicate.user_id,
                symbol=duplicate.internal_symbol,
                mode=duplicate.mode,
                revision=duplicate.revision,
                reason="newer_enabled_config_exists_for_same_execution_scope",
            )

    # XAUUSD and XAUEUR often close their M5 candles in the same tick batch.
    # Each config gets an independent SQLAlchemy session and worker so one MT5
    # request or database hiccup cannot delay the other asset's entry.
    max_workers = max(1, min(4, len(execution_config_ids)))
    all_ok = True
    if execution_config_ids:
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="torum-entry") as executor:
            futures = {executor.submit(_run_single_config_with_retry, config_id): config_id for config_id in execution_config_ids}
            for future in as_completed(futures):
                config_id = futures[future]
                try:
                    future.result()
                except Exception as exc:  # noqa: BLE001 - isolate each symbol/config
                    all_ok = False
                    trace_exception("auto_runner", "config_worker_failed", exc, config_id=config_id)
                    logger.exception("Torum V1 worker failed for config %s", config_id)

    trace_event(
        "auto_runner",
        "batch_finished",
        symbols=normalized_symbols,
        config_count=len(execution_config_ids),
        duplicate_config_count=len(duplicate_configs),
        all_ok=all_ok,
    )
    return all_ok


def run_torum_v1_with_durable_fallback(symbols: list[str], fallback_job_ids: list[int]) -> None:
    """Run immediately and retire the delayed durable fallback on success.

    FastAPI background callbacks are not durable across process termination. A
    tick close therefore creates a delayed TradeJob first, then starts this fast
    path. If the API dies before or during evaluation, the job remains pending
    and the trade worker retries the same candle after restart. Strategy setup
    idempotency and the symbol lock make the fallback safe if execution crossed
    the broker boundary just before the crash.
    """

    try:
        succeeded = run_torum_v1_for_symbols(symbols)
    except Exception as exc:  # noqa: BLE001 - leave jobs pending for retry
        trace_exception("auto_runner", "immediate_batch_failed_fallback_retained", exc, symbols=symbols, fallback_job_ids=fallback_job_ids)
        return
    if not succeeded:
        trace_event("auto_runner", "immediate_batch_incomplete_fallback_retained", symbols=symbols, fallback_job_ids=fallback_job_ids)
        return

    with SessionLocal() as db:
        retired: list[int] = []
        for job_id in fallback_job_ids:
            job = db.get(TradeJob, job_id)
            if job is None or job.job_type != "RUN_TORUM_STRATEGY":
                continue
            # Never steal a fallback already claimed by the worker. Its own
            # duplicate protections will finish it safely.
            if job.status in {"PENDING", "RETRY"}:
                job.status = "COMPLETED"
                job.locked_at = None
                job.last_error = None
                retired.append(job.id)
        if retired:
            db.commit()
        trace_event("auto_runner", "durable_fallbacks_retired", symbols=symbols, job_ids=retired)


def _run_single_config_with_retry(config_id: int) -> None:
    last_error: Exception | None = None
    for attempt in range(1, 3):
        try:
            _run_single_config(config_id)
            return
        except Exception as exc:  # noqa: BLE001 - duplicate guard makes retry safe
            last_error = exc
            trace_exception(
                "auto_runner",
                "config_retry_scheduled",
                exc,
                config_id=config_id,
                attempt=attempt,
            )
            if attempt < 2:
                sleep(0.1)
    if last_error is not None:
        raise last_error


def _run_single_config(config_id: int) -> None:
    with SessionLocal() as db:
        settings = get_global_strategy_settings(db)
        config = db.get(StrategyConfig, config_id)
        if config is None or not config.enabled:
            trace_event("auto_runner", "config_skipped", config_id=config_id, reason="config_missing_or_disabled")
            return
        if config.user_id is None:
            trace_event("auto_runner", "config_skipped", config_id=config.id, symbol=config.internal_symbol, reason="missing_user_id")
            return
        user = db.get(User, config.user_id)
        if user is None:
            trace_event("auto_runner", "config_skipped", config_id=config.id, symbol=config.internal_symbol, reason="user_not_found", user_id=config.user_id)
            return
        if not user.is_active:
            trace_event("auto_runner", "config_skipped", config_id=config.id, symbol=config.internal_symbol, reason="user_inactive", user_id=config.user_id)
            return

        status_service = TorumV1StatusService(db)
        status_checked_at = datetime.now(UTC)
        asset_status = status_service.asset_status(
            config.internal_symbol.upper(),
            config,
            settings.strategies_enabled,
            status_checked_at,
        )
        trace_event(
            "auto_runner",
            "asset_status_before_run",
            config_id=config.id,
            user_id=config.user_id,
            symbol=config.internal_symbol,
            status=asset_status.status,
            reason=asset_status.reason,
            enabled=asset_status.enabled,
            session_start=asset_status.session_start,
            session_end=asset_status.session_end,
            unlocked_at=asset_status.unlocked_at,
            blocked_by_news=asset_status.blocked_by_news,
            timeframe=asset_status.timeframe,
            checked_at_utc=status_checked_at,
            madrid_time=status_checked_at.astimezone(MADRID_TZ),
            unlock_diagnostic={"deferred_off_critical_path": True},
        )
        if asset_status.status != "UNLOCKED":
            trace_event(
                "auto_runner",
                "config_skipped",
                config_id=config.id,
                user_id=config.user_id,
                symbol=config.internal_symbol,
                reason="asset_not_unlocked",
                asset_status=asset_status,
            )
            return

        try:
            result = StrategyRunner(db).run_config(
                config, user, prevalidated_asset_status=asset_status
            )
            trace_event(
                "auto_runner",
                "config_finished",
                config_id=config.id,
                symbol=config.internal_symbol,
                user_id=config.user_id,
                ok=result.ok,
                message=result.message,
                reasons=result.reasons,
                warnings=result.warnings,
                order_id=result.order_id,
                run_id=result.run.id,
                run_status=result.run.status,
                signal_id=result.signal.id if result.signal is not None else None,
                signal_type=result.signal.signal_type if result.signal is not None else None,
                signal_status=result.signal.status if result.signal is not None else None,
                signal_reason=result.signal.reason if result.signal is not None else None,
            )
            # StrategyRunner deliberately returns a structured FAILED result for
            # exceptions and lock/preflight failures instead of leaking them
            # across the request boundary.  Treat that result as incomplete so
            # the immediate retry and the durable candle-close fallback remain
            # armed.  Definitive outcomes (no setup, risk rejection, broker
            # rejection or RECONCILING after an ambiguous MT5 response) finish
            # with run.status=FINISHED and must not be re-evaluated as a new buy.
            _raise_if_incomplete_result(config.id, result)
        except Exception as exc:
            trace_exception(
                "auto_runner",
                "config_failed",
                exc,
                config_id=config.id,
                symbol=config.internal_symbol,
                user_id=config.user_id,
            )
            logger.exception("Torum V1 auto run failed for config %s", config.id)
            raise



def _raise_if_incomplete_result(config_id: int, result: object) -> None:
    """Escalate only infrastructure/preflight failures to the durable retry.

    A normal no-entry decision or a definitive risk/broker response has a
    FINISHED run and is a completed evaluation.  FAILED means the candle was
    not evaluated to a terminal decision and must remain retryable.
    """

    run = getattr(result, "run", None)
    if getattr(run, "status", None) != "FAILED":
        return
    message = str(getattr(result, "message", "strategy_run_failed"))
    raise RuntimeError(f"torum_strategy_run_failed:{config_id}:{message}")

def _latest_configs_by_execution_scope(
    configs: list[StrategyConfig],
) -> tuple[list[StrategyConfig], list[StrategyConfig]]:
    """Select one enabled config per user/symbol execution scope.

    Old installations can contain more than one active row for the same Torum
    asset (for example a revision-1 seed plus the current edited config). Running
    both rows evaluates conflicting parameters and can create duplicate orders.
    The highest revision wins; the id breaks ties deterministically.
    """

    selected_by_scope: dict[tuple[int | None, str, str], StrategyConfig] = {}
    for config in configs:
        scope = (
            config.user_id,
            str(config.strategy_key).lower(),
            str(config.internal_symbol).upper(),
        )
        current = selected_by_scope.get(scope)
        candidate_rank = (int(config.revision or 1), int(config.id or 0))
        current_rank = (int(current.revision or 1), int(current.id or 0)) if current is not None else None
        if current is None or candidate_rank > current_rank:
            selected_by_scope[scope] = config

    selected_ids = {int(config.id) for config in selected_by_scope.values() if config.id is not None}
    selected = [config for config in configs if config.id is not None and int(config.id) in selected_ids]
    duplicates = [config for config in configs if config.id is None or int(config.id) not in selected_ids]
    return selected, duplicates
