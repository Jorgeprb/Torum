from datetime import UTC, datetime
from dataclasses import asdict
from threading import Lock
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.mt5.status_store import mt5_status_store
from app.orders.service import OrderManager
from app.risk.manager import RiskManager
from app.settings.trading_service import get_global_trading_settings
from app.strategies.ath import ath_zone_for_price, get_or_update_symbol_ath, latest_executable_price, plan_torum_v1_bot_exposure
from app.market_context.dollar_strength import DollarStrengthService, usd_strength_decision_for_symbol
from app.strategies.engine import StrategyContextBuilder
from app.strategies.models import StrategyConfig, StrategyRun, StrategySignal
from app.strategies.registry import strategy_registry
from app.strategies.repository import get_definition, get_global_strategy_settings
from app.strategies.schemas import StrategyRunRead, StrategyRunResult, StrategySignalRead
from app.symbols.service import get_symbol_by_internal
from app.trading.schemas import ClientConfirmation, ManualOrderRequest
from app.users.models import User

_TORUM_V1_SYMBOL_LOCKS: dict[str, Lock] = {}


class StrategyRunner:
    def __init__(self, db: Session, order_manager: OrderManager | None = None) -> None:
        self.db = db
        self.order_manager = order_manager or OrderManager(db)

    def run_config(self, config: StrategyConfig, user: User) -> StrategyRunResult:
        started = datetime.now(UTC)
        run = StrategyRun(
            strategy_config_id=config.id,
            strategy_key=config.strategy_key,
            started_at=started,
            status="STARTED",
            candles_used=0,
            indicators_used_json={},
            context_summary_json={},
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)

        settings = get_global_strategy_settings(self.db)
        if not settings.strategies_enabled:
            return self._fail_run(run, "Strategies are disabled")
        if not config.enabled:
            return self._fail_run(run, "Strategy config is disabled")

        definition = get_definition(self.db, config.strategy_key)
        if definition is None or not definition.enabled:
            return self._fail_run(run, "Strategy definition is disabled or missing")
        if config.mode == "LIVE" and not settings.strategy_live_enabled:
            return self._fail_run(run, "Strategy LIVE execution is disabled")

        lock = _torum_v1_symbol_lock(config.internal_symbol) if config.strategy_key == "torum_v1" else None
        if lock is not None:
            lock.acquire()

        signal: StrategySignal | None = None
        try:
            plugin = strategy_registry.get(config.strategy_key)
            context = StrategyContextBuilder(self.db).build(config)
            signal_data = plugin.generate_signal(context)
            run.candles_used = len(context.candles)
            run.indicators_used_json = {"required": list(plugin.required_indicators), "available": list(context.indicators.keys())}
            run.context_summary_json = context.summary()
            signal = self._save_signal(config, user, signal_data)
            if signal.signal_type == "NONE":
                signal.status = "IGNORED"
                run.status = "FINISHED"
                run.finished_at = datetime.now(UTC)
                self.db.commit()
                return StrategyRunResult(
                    ok=True,
                    run=StrategyRunRead.model_validate(run),
                    signal=StrategySignalRead.model_validate(signal),
                    message=signal.reason,
                )

            if signal.strategy_key == "torum_v1" and signal.signal_type == "ENTRY" and signal.side == "BUY":
                duplicate = self._previous_torum_v1_setup_signal(signal)
                if duplicate is not None:
                    signal.status = "REJECTED_BY_RISK"
                    signal.risk_result_json = {"allowed": False, "reasons": ["duplicate_setup_signal"], "warnings": []}
                    run.status = "FINISHED"
                    run.finished_at = datetime.now(UTC)
                    self.db.commit()
                    return StrategyRunResult(
                        ok=False,
                        run=StrategyRunRead.model_validate(run),
                        signal=StrategySignalRead.model_validate(signal),
                        message="Signal rejected: duplicate setup",
                        reasons=["duplicate_setup_signal"],
                    )
                params = (signal.metadata_json or {}).get("params")
                usd_snapshot = DollarStrengthService(self.db).latest_snapshot_read()
                usd_decision = usd_strength_decision_for_symbol(
                    signal.internal_symbol,
                    params if isinstance(params, dict) else {},
                    usd_snapshot,
                )
                signal.metadata_json = {**(signal.metadata_json or {}), **usd_decision.metadata}
                if not usd_decision.allowed:
                    signal.status = "REJECTED_BY_RISK"
                    signal.risk_result_json = {"allowed": False, "reasons": [usd_decision.reason], "warnings": []}
                    run.status = "FINISHED"
                    run.finished_at = datetime.now(UTC)
                    self.db.commit()
                    return StrategyRunResult(
                        ok=False,
                        run=StrategyRunRead.model_validate(run),
                        signal=StrategySignalRead.model_validate(signal),
                        message="Signal rejected by USD strength filter",
                        reasons=[usd_decision.reason],
                    )
                trading_settings = _strategy_trading_settings(get_global_trading_settings(self.db), config.mode)
                latest_price = latest_executable_price(context.latest_tick, "BUY")
                account = mt5_status_store.get().account
                raw_desired_multiplier = int((signal.metadata_json or {}).get("desired_multiplier") or 1)
                desired_multiplier = _torum_v1_desired_multiplier_for_ath_zone(
                    self.db,
                    symbol=signal.internal_symbol,
                    current_price=latest_price,
                    params=params if isinstance(params, dict) else {},
                    desired_multiplier=raw_desired_multiplier,
                )
                plan = plan_torum_v1_bot_exposure(
                    self.db,
                    symbol=signal.internal_symbol,
                    user_id=config.user_id,
                    desired_multiplier=desired_multiplier,
                    current_price=latest_price,
                    balance=account.balance if account is not None else None,
                    trading_settings=trading_settings,
                    symbol_mapping=get_symbol_by_internal(self.db, signal.internal_symbol),
                    exclude_signal_id=signal.id,
                )
                signal.metadata_json = {
                    **(signal.metadata_json or {}),
                    "raw_desired_multiplier": raw_desired_multiplier,
                    "desired_multiplier": desired_multiplier,
                    "accepted_multiplier": plan.multiplier,
                    "accepted_volume": plan.volume,
                    "plan_reason": plan.reason,
                    "bot_exposure_plan": asdict(plan),
                }
                if not plan.allowed:
                    signal.status = "REJECTED_BY_RISK"
                    signal.risk_result_json = {"allowed": False, "reasons": [plan.reason], "warnings": []}
                    run.status = "FINISHED"
                    run.finished_at = datetime.now(UTC)
                    self.db.commit()
                    return StrategyRunResult(
                        ok=False,
                        run=StrategyRunRead.model_validate(run),
                        signal=StrategySignalRead.model_validate(signal),
                        message="Signal rejected by Torum V1 risk",
                        reasons=[plan.reason],
                    )
                signal.suggested_volume = plan.volume
                signal.status = "RISK_APPROVED"
                self.db.commit()

            order_payload = ManualOrderRequest(
                internal_symbol=signal.internal_symbol,
                side=signal.side,  # type: ignore[arg-type]
                order_type="MARKET",
                volume=signal.suggested_volume or 0.01,
                sl=signal.sl,
                tp=signal.tp,
                comment=f"Strategy {signal.strategy_key} signal {signal.id}",
                client_confirmation=ClientConfirmation(confirmed=True, mode_acknowledged=config.mode),
            )
            risk_decision = RiskManager(self.db).evaluate_strategy_order(
                order=order_payload,
                trading_settings=_strategy_trading_settings(get_global_trading_settings(self.db), config.mode),
                strategy_settings=settings,
                symbol_mapping=get_symbol_by_internal(self.db, signal.internal_symbol),
                mt5_status=mt5_status_store.get(),
                price_stale_after_seconds=get_settings().price_stale_after_seconds,
                user_id=config.user_id,
                strategy_key=config.strategy_key,
                exclude_signal_id=signal.id,
            )
            signal.risk_result_json = risk_decision.model_dump()
            if not risk_decision.allowed:
                signal.status = "REJECTED_BY_RISK"
                run.status = "FINISHED"
                run.finished_at = datetime.now(UTC)
                self.db.commit()
                return StrategyRunResult(
                    ok=False,
                    run=StrategyRunRead.model_validate(run),
                    signal=StrategySignalRead.model_validate(signal),
                    message="Signal rejected by risk manager",
                    reasons=risk_decision.reasons,
                    warnings=risk_decision.warnings,
                )

            signal.status = "SENT_TO_ORDER_MANAGER"
            self.db.commit()
            order_response = self.order_manager.create_strategy_order(
                order_payload,
                user,
                strategy_key=signal.strategy_key,
                strategy_signal_id=signal.id,
                mode=config.mode,
                strategy_settings=settings,
            )
            signal.order_id = order_response.order_id
            signal.status = "ORDER_EXECUTED" if order_response.ok else ("REJECTED_BY_RISK" if order_response.status == "REJECTED" else "ORDER_FAILED")
            run.status = "FINISHED"
            run.finished_at = datetime.now(UTC)
            self.db.commit()
            return StrategyRunResult(
                ok=order_response.ok,
                run=StrategyRunRead.model_validate(run),
                signal=StrategySignalRead.model_validate(signal),
                message=order_response.message,
                order_id=order_response.order_id,
                reasons=order_response.reasons,
                warnings=order_response.warnings,
            )
        except Exception as exc:
            if signal is not None and signal.status in {"RISK_APPROVED", "SENT_TO_ORDER_MANAGER"}:
                signal.status = "ORDER_FAILED"
                signal.risk_result_json = {"allowed": False, "reasons": [str(exc)], "warnings": []}
                self.db.commit()
            return self._fail_run(run, str(exc))
        finally:
            if lock is not None:
                lock.release()

    def _save_signal(self, config: StrategyConfig, user: User, signal_data: object) -> StrategySignal:
        signal = StrategySignal(
            strategy_config_id=config.id,
            strategy_key=signal_data.strategy_key,
            user_id=user.id,
            internal_symbol=signal_data.internal_symbol,
            timeframe=signal_data.timeframe,
            signal_type=signal_data.signal_type,
            side=signal_data.side,
            entry_type=signal_data.entry_type,
            confidence=signal_data.confidence,
            suggested_volume=signal_data.suggested_volume,
            sl=signal_data.sl,
            tp=signal_data.tp,
            reason=signal_data.reason,
            metadata_json=signal_data.metadata,
            status="GENERATED",
        )
        self.db.add(signal)
        self.db.commit()
        self.db.refresh(signal)
        return signal

    def _previous_torum_v1_setup_signal(self, signal: StrategySignal) -> StrategySignal | None:
        metadata = signal.metadata_json or {}
        confirmation_time = metadata.get("confirmation_candle_time")
        pullback_low_time = metadata.get("pullback_low_time")
        operation_zone_id = metadata.get("operation_zone_id")
        if confirmation_time is None or pullback_low_time is None:
            return None

        stmt = (
            select(StrategySignal)
            .where(
                StrategySignal.id < signal.id,
                StrategySignal.strategy_key == "torum_v1",
                StrategySignal.user_id == signal.user_id,
                StrategySignal.internal_symbol == signal.internal_symbol,
                StrategySignal.signal_type == "ENTRY",
                StrategySignal.side == "BUY",
            )
            .order_by(StrategySignal.id.desc())
            .limit(100)
        )
        for previous in self.db.scalars(stmt):
            previous_metadata = previous.metadata_json or {}
            if (
                previous_metadata.get("confirmation_candle_time") == confirmation_time
                and previous_metadata.get("pullback_low_time") == pullback_low_time
                and previous_metadata.get("operation_zone_id") == operation_zone_id
            ):
                return previous
        return None

    def _fail_run(self, run: StrategyRun, message: str) -> StrategyRunResult:
        run.status = "FAILED"
        run.finished_at = datetime.now(UTC)
        run.error_message = message
        self.db.commit()
        self.db.refresh(run)
        return StrategyRunResult(ok=False, run=StrategyRunRead.model_validate(run), signal=None, message=message, reasons=[message])


def _strategy_trading_settings(trading_settings: object, mode: str) -> object:
    return SimpleNamespace(
        trading_mode=mode,
        live_trading_enabled=getattr(trading_settings, "live_trading_enabled", False),
        require_live_confirmation=getattr(trading_settings, "require_live_confirmation", True),
        default_volume=getattr(trading_settings, "default_volume", 0.01),
        default_magic_number=getattr(trading_settings, "default_magic_number", 260426),
        default_deviation_points=getattr(trading_settings, "default_deviation_points", 20),
        max_order_volume=getattr(trading_settings, "max_order_volume", None),
        allow_market_orders=getattr(trading_settings, "allow_market_orders", True),
        allow_pending_orders=getattr(trading_settings, "allow_pending_orders", False),
        is_paused=getattr(trading_settings, "is_paused", False),
        long_only=getattr(trading_settings, "long_only", True),
        default_take_profit_percent=getattr(trading_settings, "default_take_profit_percent", 0.09),
        use_stop_loss=getattr(trading_settings, "use_stop_loss", False),
        lot_per_equity_enabled=getattr(trading_settings, "lot_per_equity_enabled", True),
        equity_per_0_01_lot=getattr(trading_settings, "equity_per_0_01_lot", 2500.0),
        minimum_lot=getattr(trading_settings, "minimum_lot", 0.01),
        allow_manual_lot_adjustment=getattr(trading_settings, "allow_manual_lot_adjustment", True),
        show_bid_line=getattr(trading_settings, "show_bid_line", True),
        show_ask_line=getattr(trading_settings, "show_ask_line", True),
        mt5_order_execution_enabled=getattr(trading_settings, "mt5_order_execution_enabled", False),
        market_data_source=getattr(trading_settings, "market_data_source", "MT5"),
    )


def _torum_v1_symbol_lock(symbol: str) -> Lock:
    normalized = symbol.upper()
    lock = _TORUM_V1_SYMBOL_LOCKS.get(normalized)
    if lock is None:
        lock = Lock()
        _TORUM_V1_SYMBOL_LOCKS[normalized] = lock
    return lock


def _torum_v1_desired_multiplier_for_ath_zone(
    db: Session,
    *,
    symbol: str,
    current_price: float | None,
    params: dict[str, object],
    desired_multiplier: int,
) -> int:
    safe_desired = max(1, min(3, int(desired_multiplier)))
    if not _bool_param(params.get("ath_green_prefer_x2_entries"), True):
        return safe_desired
    ath = get_or_update_symbol_ath(db, symbol)
    zone = ath_zone_for_price(ath, current_price)
    if zone is not None and zone.key in {"green", "deep_green"}:
        return max(safe_desired, 2)
    return safe_desired


def _bool_param(value: object, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "si", "sí"}
    return bool(value)
