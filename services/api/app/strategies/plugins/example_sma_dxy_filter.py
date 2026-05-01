from typing import Any

from app.strategies.context import StrategyContext
from app.strategies.signals import StrategySignalData


class ExampleSmaDxyFilter:
    key = "example_sma_dxy_filter"
    name = "Example DXY SMA Filter"
    version = "0.1.0"
    description = "Reads DXY D1 SMA30 context and returns a NONE signal with dollar strength metadata."
    default_params: dict[str, Any] = {"dxy_symbol": "DXY", "dxy_timeframe": "D1", "sma_period": 30}
    supported_symbols = ("XAUUSD", "XAUEUR", "XAUAUD", "XAUJPY")
    supported_timeframes = ("M1", "M5", "H1", "H2", "H3", "H4", "D1", "W1")
    required_indicators = ("SMA:DXY:D1:30",)
    required_context = ("candles", "indicators")

    def generate_signal(self, context: StrategyContext) -> StrategySignalData:
        dxy = context.indicators.get("dxy_sma30", {})
        latest_close = dxy.get("latest_close")
        latest_sma = dxy.get("latest_sma")
        if latest_close is None or latest_sma is None:
            strength = "UNKNOWN"
            reason = "DXY/SMA30 unavailable or not enough DXY D1 candles"
        elif latest_close > latest_sma:
            strength = "STRONG"
            reason = "DXY close is above SMA30; dollar strength filter is STRONG"
        elif latest_close < latest_sma:
            strength = "WEAK"
            reason = "DXY close is below SMA30; dollar strength filter is WEAK"
        else:
            strength = "NEUTRAL"
            reason = "DXY close equals SMA30; dollar strength filter is NEUTRAL"

        return StrategySignalData(
            strategy_key=self.key,
            internal_symbol=context.symbol,
            timeframe=context.timeframe,
            signal_type="NONE",
            side="NONE",
            confidence=0.0,
            reason=reason,
            metadata={"dollar_strength": strength, "dxy": dxy},
        )
