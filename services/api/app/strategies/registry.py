from app.strategies.plugins.base import StrategyPlugin
from app.strategies.plugins.example_manual_zone_strategy import ExampleManualZoneStrategy
from app.strategies.plugins.example_sma_dxy_filter import ExampleSmaDxyFilter


class StrategyRegistry:
    def __init__(self) -> None:
        self._plugins: dict[str, StrategyPlugin] = {}

    def register(self, plugin: StrategyPlugin) -> None:
        self._plugins[plugin.key.lower()] = plugin

    def get(self, key: str) -> StrategyPlugin:
        normalized = key.lower()
        if normalized not in self._plugins:
            raise KeyError(f"Strategy plugin not registered: {key}")
        return self._plugins[normalized]

    def list(self) -> list[StrategyPlugin]:
        return list(self._plugins.values())


strategy_registry = StrategyRegistry()
strategy_registry.register(ExampleSmaDxyFilter())
strategy_registry.register(ExampleManualZoneStrategy())
