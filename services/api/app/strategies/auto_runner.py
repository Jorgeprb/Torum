import logging
from datetime import UTC, datetime

from sqlalchemy import select

from app.db.session import SessionLocal
from app.core.decision_log import trace_event, trace_exception
from app.strategies.models import StrategyConfig
from app.strategies.repository import get_global_strategy_settings
from app.strategies.runner import StrategyRunner
from app.strategies.torum_v1 import MADRID_TZ, TORUM_V1_KEY, TorumV1StatusService
from app.users.models import User

logger = logging.getLogger(__name__)


def run_torum_v1_for_symbols(symbols: list[str]) -> None:
    normalized_symbols = sorted({symbol.upper() for symbol in symbols if symbol})
    if not normalized_symbols:
        trace_event("auto_runner", "batch_skipped", reason="empty_symbol_list", raw_symbols=symbols)
        return

    trace_event("auto_runner", "batch_started", symbols=normalized_symbols)
    with SessionLocal() as db:
        settings = get_global_strategy_settings(db)
        if not settings.strategies_enabled:
            trace_event("auto_runner", "batch_skipped", reason="strategies_disabled", symbols=normalized_symbols)
            return

        configs = list(
            db.scalars(
                select(StrategyConfig).where(
                    StrategyConfig.strategy_key == TORUM_V1_KEY,
                    StrategyConfig.enabled.is_(True),
                    StrategyConfig.internal_symbol.in_(normalized_symbols),
                )
            )
        )
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
                }
                for config in configs
            ],
        )
        runner = StrategyRunner(db)
        for config in configs:
            if config.user_id is None:
                trace_event("auto_runner", "config_skipped", config_id=config.id, symbol=config.internal_symbol, reason="missing_user_id")
                continue
            user = db.get(User, config.user_id)
            if user is None:
                trace_event("auto_runner", "config_skipped", config_id=config.id, symbol=config.internal_symbol, reason="user_not_found", user_id=config.user_id)
                continue
            if not user.is_active:
                trace_event("auto_runner", "config_skipped", config_id=config.id, symbol=config.internal_symbol, reason="user_inactive", user_id=config.user_id)
                continue
            try:
                status_service = TorumV1StatusService(db)
                status_checked_at = datetime.now(UTC)
                asset_status = status_service.asset_status(
                    config.internal_symbol.upper(),
                    config,
                    settings.strategies_enabled,
                    status_checked_at,
                )
                unlock_diagnostic = status_service.unlock_diagnostic_snapshot(
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
                    unlock_diagnostic=unlock_diagnostic,
                )
                result = runner.run_config(config, user)
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
    trace_event("auto_runner", "batch_finished", symbols=normalized_symbols, config_count=len(configs))
