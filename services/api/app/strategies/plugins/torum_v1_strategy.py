from typing import Any

from app.strategies.context import StrategyContext
from app.strategies.signals import StrategySignalData
from app.strategies.torum_v1 import TORUM_V1_KEY, operation_zones_from_drawings, should_buy_torum_v1


class TorumV1Strategy:
    key = TORUM_V1_KEY
    name = "Estrategia Torum V1.0"
    version = "1.0"
    description = "Bloqueo visual y entrada BUY por pullback M5 dentro de zona operativa manual."
    default_params: dict[str, Any] = {
        "use_news": True,
        "enabled": True,
        "timeframe": "H2",
        "session_start": "09:00",
        "session_end": "15:00",
        "enable_operation_zones": True,
        "entry_timeframe": "M5",
        "pullback_threshold_pct": 0.20,
        "pullback_lookback_bars": 12,
        "show_pullback_debug": False,
        "require_zone": True,
        "one_position_per_symbol": True,
    }
    supported_symbols = ("XAUEUR", "XAUUSD")
    supported_timeframes = ("H2", "H3", "M5")
    required_indicators: tuple[str, ...] = ()
    required_context = ("candles", "no_trade_zones")

    def generate_signal(self, context: StrategyContext) -> StrategySignalData:
        params = {**self.default_params, **context.params}
        if str(params.get("entry_timeframe", "M5")).upper() != "M5":
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
            operation_zones=operation_zones_from_drawings(context.manual_zones),
            params=params,
            now=context.now,
            open_positions=context.open_positions if params.get("one_position_per_symbol", True) else [],
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
            }

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
