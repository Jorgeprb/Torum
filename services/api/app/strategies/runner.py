from datetime import UTC, datetime
from types import SimpleNamespace

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.mt5.status_store import mt5_status_store
from app.orders.service import OrderManager
from app.risk.manager import RiskManager
from app.settings.trading_service import get_global_trading_settings
from app.strategies.engine import StrategyContextBuilder
from app.strategies.models import StrategyConfig, StrategyRun, StrategySignal
from app.strategies.registry import strategy_registry
from app.strategies.repository import get_definition, get_global_strategy_settings
from app.strategies.schemas import StrategyRunRead, StrategyRunResult, StrategySignalRead
from app.symbols.service import get_symbol_by_internal
from app.trading.schemas import ClientConfirmation, ManualOrderRequest
from app.users.models import User


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
            return self._fail_run(run, str(exc))

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
    )
