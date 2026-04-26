from typing import Any

from app.candles.models import Candle
from app.indicators.plugins.base import IndicatorContext


class CustomZoneExamplePlugin:
    key = "CUSTOM_ZONE_EXAMPLE"
    name = "Custom Operational Zone Example"
    version = "0.1.0"
    description = "Placeholder plugin showing the normalized shape for future operational zones."
    default_params: dict[str, Any] = {}
    supported_outputs = ("zone",)

    def calculate(self, candles: list[Candle], params: dict[str, Any], context: IndicatorContext) -> dict[str, Any]:
        return {
            "type": "zone",
            "name": self.name,
            "symbol": context.symbol,
            "timeframe": context.timeframe,
            "zones": [],
            "style": {"color": "#62d995"},
        }
