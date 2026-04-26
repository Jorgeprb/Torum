from typing import Any

from app.candles.models import Candle
from app.market_data.timeframes import ensure_utc
from app.indicators.plugins.base import IndicatorContext


class SMAPlugin:
    key = "SMA"
    name = "Simple Moving Average"
    version = "1.0.0"
    description = "Simple moving average calculated from Torum candles."
    default_params = {"period": 30}
    supported_outputs = ("line",)

    def calculate(self, candles: list[Candle], params: dict[str, Any], context: IndicatorContext) -> dict[str, Any]:
        period = int(params.get("period") or self.default_params["period"])
        if period <= 0:
            raise ValueError("SMA period must be greater than zero")

        ordered = sorted(candles, key=lambda candle: ensure_utc(candle.time))
        points: list[dict[str, float | int]] = []
        closes: list[float] = []
        for candle in ordered:
            closes.append(float(candle.close))
            if len(closes) < period:
                continue
            window = closes[-period:]
            points.append(
                {
                    "time": int(ensure_utc(candle.time).timestamp()),
                    "value": sum(window) / period,
                }
            )

        return {
            "type": "line",
            "name": f"SMA{period}",
            "symbol": context.symbol,
            "timeframe": context.timeframe,
            "points": points,
            "style": {"lineWidth": 2, "color": "#d6b25e"},
        }
