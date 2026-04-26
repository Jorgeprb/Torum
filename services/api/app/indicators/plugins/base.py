from dataclasses import dataclass
from typing import Any, Protocol

from app.candles.models import Candle


@dataclass(frozen=True, slots=True)
class IndicatorContext:
    symbol: str
    timeframe: str
    config_id: int | None = None


class IndicatorPlugin(Protocol):
    key: str
    name: str
    version: str
    description: str
    default_params: dict[str, Any]
    supported_outputs: tuple[str, ...]

    def calculate(
        self,
        candles: list[Candle],
        params: dict[str, Any],
        context: IndicatorContext,
    ) -> dict[str, Any]:
        ...
