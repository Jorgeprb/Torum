from typing import Any

from app.strategies.context import StrategyContext
from app.strategies.signals import StrategySignalData
from app.strategies.ath import latest_executable_price
from app.strategies.torum_v1 import TORUM_V1_KEY, operation_zones_from_drawings, should_buy_torum_v1, support_zones_from_drawings


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
        "pullback_enabled": True,
        "pullback_max_count": 10,
        "pullback_min_pct": 0.0,
        "pullback_threshold_pct": 0.0,
        "pullback_entry_min_pct": 0.20,
        "pullback_lookback_bars": 12,
        "pullback_swing_confirm_bars": 1,
        "pullback_allow_peak_extension": True,
        "pullback_require_bearish_leg": True,
        "pullback_min_bearish_candles": 1,
        "pullback_min_lower_close_candles": 1,
        "pullback_disallow_same_candle_peak_low": True,
        "pullback_impulse_green_filter_enabled": True,
        "pullback_recovery_pct": 0.10,
        "pullback_end_confirmation_bars": 1,
        "pullback_min_bars_between": 0,
        "pullback_use_wicks": True,
        "pullback_use_close_confirmation": True,
        "pullback_live_update_enabled": True,
        "pullback_show_labels": True,
        "pullback_show_only_live": False,
        "pullback_label_decimals": 2,
        "pullback_line_width": 2,
        "pullback_opacity": 0.95,
        "show_pullback_debug": False,
        "require_zone": True,
        "one_position_per_symbol": False,
        "usd_strength_filter_enabled": True,
        "usd_strength_apply_to_symbols": ["XAUUSD", "XAUEUR"],
        "usd_strength_mode": "only_operate_when_weak",
        "usd_sma_period": 30,
        "usd_neutral_band_points": 0.10,
        "usd_allow_when_neutral": False,
        "usd_strong_drop_override_enabled": True,
        "usd_strong_drop_lookback_days": 3,
        "usd_strong_drop_min_pct": 0.45,
        "usd_strong_drop_require_bearish_close": True,
        "usd_strength_strict": False,
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
            support_zones=support_zones_from_drawings(context.manual_zones),
            params=params,
            now=context.now,
            current_price=latest_executable_price(context.latest_tick, "BUY"),
            open_positions=context.open_positions,
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
