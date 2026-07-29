from dataclasses import asdict
from typing import Any

from app.core.config import get_settings
from app.core.decision_log import trace_event

from app.strategies.context import StrategyContext
from app.strategies.signals import StrategySignalData
from app.strategies.ath import latest_executable_price
from app.strategies.torum_v1 import (
    TORUM_V1_KEY,
    operation_zones_from_drawings,
    should_buy_torum_v1,
    support_zones_from_drawings,
    torum_v1_diagnostic_snapshot,
)
from app.strategies.torum_v1_config import TorumV1Params


class TorumV1Strategy:
    key = TORUM_V1_KEY
    name = "Estrategia Torum V1.0"
    version = "1.0"
    description = "Bloqueo visual y entrada BUY por pullback M5 dentro de zona operativa manual."
    default_params: dict[str, Any] = TorumV1Params.defaults_for_symbol("XAUEUR").model_dump()
    supported_symbols = ("XAUEUR", "XAUUSD")
    supported_timeframes = ("H2", "H3", "M5")
    required_indicators: tuple[str, ...] = ()
    required_context = ("candles", "no_trade_zones")

    def generate_signal(self, context: StrategyContext) -> StrategySignalData:
        params = TorumV1Params.normalize(context.symbol, context.params).model_dump()
        current_price = latest_executable_price(context.latest_tick, "BUY")
        operation_zones = operation_zones_from_drawings(context.manual_zones)
        support_zones = support_zones_from_drawings(context.manual_zones)
        recent_count = max(5, min(100, get_settings().strategy_trace_recent_candles))
        trace_event(
            "torum_v1_technical",
            "evaluation_started",
            config_id=context.config.id,
            config_revision=context.config.revision,
            user_id=context.config.user_id,
            symbol=context.symbol,
            mode=context.mode,
            now=context.now,
            current_price=current_price,
            params=params,
            candle_count=len(context.candles),
            recent_candles=[
                {
                    "time": candle.time,
                    "open": candle.open,
                    "high": candle.high,
                    "low": candle.low,
                    "close": candle.close,
                    "volume": candle.volume,
                    "tick_count": candle.tick_count,
                }
                for candle in context.candles[-recent_count:]
            ],
            operation_zones=[asdict(zone) for zone in operation_zones],
            support_zones=[asdict(zone) for zone in support_zones],
            open_positions=[
                {
                    "id": position.id,
                    "order_id": position.order_id,
                    "status": position.status,
                    "volume": position.volume,
                    "open_price": position.open_price,
                    "tp": position.tp,
                    "opened_at": position.opened_at,
                    "mt5_position_ticket": position.mt5_position_ticket,
                }
                for position in context.open_positions
            ],
        )
        if str(params.get("entry_timeframe", "M5")).upper() != "M5":
            trace_event(
                "torum_v1_technical",
                "decision",
                config_id=context.config.id,
                symbol=context.symbol,
                should_buy=False,
                reason="entry_timeframe_not_m5",
                configured_entry_timeframe=params.get("entry_timeframe"),
            )
            return StrategySignalData(
                strategy_key=self.key,
                internal_symbol=context.symbol,
                timeframe="M5",
                signal_type="NONE",
                side="NONE",
                reason="entry_timeframe_not_m5",
                metadata={"params": params},
            )

        decision = should_buy_torum_v1(
            symbol=context.symbol,
            candles_m5=context.candles,
            operation_zones=operation_zones,
            support_zones=support_zones,
            params=params,
            now=context.now,
            current_price=current_price,
            open_positions=context.open_positions,
        )
        diagnostic_snapshot = torum_v1_diagnostic_snapshot(
            symbol=context.symbol,
            candles_m5=context.candles,
            operation_zones=operation_zones,
            support_zones=support_zones,
            params=params,
            now=context.now,
            current_price=current_price,
        )
        trace_event(
            "torum_v1_technical",
            "diagnostic_snapshot",
            config_id=context.config.id,
            config_revision=context.config.revision,
            user_id=context.config.user_id,
            symbol=context.symbol,
            decision_should_buy=decision.should_buy,
            decision_reason=decision.reason,
            snapshot=diagnostic_snapshot,
        )
        trace_event(
            "torum_v1_technical",
            "decision",
            config_id=context.config.id,
            config_revision=context.config.revision,
            user_id=context.config.user_id,
            symbol=context.symbol,
            mode=context.mode,
            should_buy=decision.should_buy,
            reason=decision.reason,
            confirmation_candle_time=decision.confirmation_candle_time,
            pullback=asdict(decision.pullback) if decision.pullback is not None else None,
            operation_zone=asdict(decision.zone) if decision.zone is not None else None,
            support_zone=asdict(decision.support) if decision.support is not None else None,
            metadata=decision.metadata,
            current_price=current_price,
        )
        if not decision.should_buy:
            return StrategySignalData(
                strategy_key=self.key,
                internal_symbol=context.symbol,
                timeframe="M5",
                signal_type="NONE",
                side="NONE",
                reason=decision.reason,
                metadata={"params": params, **(decision.metadata or {})},
            )

        if decision.confirmation_candle_time is not None:
            context.config.params_json = {
                **(context.config.params_json or {}),
                "last_signal_candle_time": int(decision.confirmation_candle_time.timestamp()),
                "last_signal_pullback_low_time": int(decision.pullback.pullback_low_time.timestamp()) if decision.pullback is not None else None,
                "last_signal_operation_zone_id": decision.zone.drawing_id if decision.zone is not None else None,
            }

        trace_event(
            "torum_v1_technical",
            "entry_signal_generated",
            config_id=context.config.id,
            config_revision=context.config.revision,
            user_id=context.config.user_id,
            symbol=context.symbol,
            reason=decision.reason,
            confirmation_candle_time=decision.confirmation_candle_time,
            pullback=asdict(decision.pullback) if decision.pullback is not None else None,
            operation_zone=asdict(decision.zone) if decision.zone is not None else None,
            support_zone=asdict(decision.support) if decision.support is not None else None,
            metadata=decision.metadata,
        )
        return StrategySignalData(
            strategy_key=self.key,
            internal_symbol=context.symbol,
            timeframe="M5",
            signal_type="ENTRY",
            side="BUY",
            confidence=0.72,
            suggested_volume=float(params.get("suggested_volume") or 0.01),
            reason=decision.reason,
            metadata={"params": params, **(decision.metadata or {})},
        )
