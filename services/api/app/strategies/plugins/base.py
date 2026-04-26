from typing import Any, Protocol

from app.strategies.context import StrategyContext
from app.strategies.signals import StrategySignalData


class StrategyPlugin(Protocol):
    key: str
    name: str
    version: str
    description: str
    default_params: dict[str, Any]
    supported_symbols: tuple[str, ...]
    supported_timeframes: tuple[str, ...]
    required_indicators: tuple[str, ...]
    required_context: tuple[str, ...]

    def generate_signal(self, context: StrategyContext) -> StrategySignalData:
        ...
