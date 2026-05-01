from typing import Any

from app.strategies.context import StrategyContext
from app.strategies.signals import StrategySignalData


class ExampleManualZoneStrategy:
    key = "example_manual_zone_strategy"
    name = "Example Manual Zone Strategy"
    version = "0.1.0"
    description = "Reads visible manual_zone drawings and can generate a PAPER-only example ENTRY signal."
    default_params: dict[str, Any] = {"dry_run": True, "volume": 0.01}
    supported_symbols = ("XAUUSD", "XAUEUR", "XAUAUD", "XAUJPY")
    supported_timeframes = ("M1", "M5", "H1", "H2", "H3", "H4", "D1", "W1")
    required_indicators: tuple[str, ...] = ()
    required_context = ("candles", "latest_tick", "manual_zones", "no_trade_zones")

    def generate_signal(self, context: StrategyContext) -> StrategySignalData:
        price = context.latest_price
        if price is None:
            return self._none(context, "No price available for manual zone evaluation", {})

        for drawing in context.manual_zones:
            payload = drawing.payload_json or {}
            price_min = _float_or_none(payload.get("price_min"))
            price_max = _float_or_none(payload.get("price_max"))
            direction = str(payload.get("direction") or "NEUTRAL").upper()
            if price_min is None or price_max is None:
                continue
            if price_min <= price <= price_max and direction in {"BUY", "SELL"}:
                dry_run = bool(context.params.get("dry_run", True))
                signal_type = "NONE" if dry_run else "ENTRY"
                return StrategySignalData(
                    strategy_key=self.key,
                    internal_symbol=context.symbol,
                    timeframe=context.timeframe,
                    signal_type=signal_type,
                    side=direction if signal_type == "ENTRY" else "NONE",
                    confidence=0.5,
                    suggested_volume=float(context.params.get("volume") or 0.01),
                    reason=(
                        "Example signal generated inside manual zone"
                        if not dry_run
                        else "Manual zone matched, but dry_run=true so no order signal is emitted"
                    ),
                    metadata={
                        "manual_zone_id": drawing.id,
                        "price": price,
                        "price_min": price_min,
                        "price_max": price_max,
                        "direction": direction,
                        "dry_run": dry_run,
                    },
                )

        return self._none(context, "No visible manual_zone contains current price", {"price": price})

    def _none(self, context: StrategyContext, reason: str, metadata: dict[str, Any]) -> StrategySignalData:
        return StrategySignalData(
            strategy_key=self.key,
            internal_symbol=context.symbol,
            timeframe=context.timeframe,
            signal_type="NONE",
            side="NONE",
            reason=reason,
            metadata=metadata,
        )


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
