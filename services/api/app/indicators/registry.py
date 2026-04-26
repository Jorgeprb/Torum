from app.indicators.plugins.base import IndicatorPlugin
from app.indicators.plugins.custom_zone_example import CustomZoneExamplePlugin
from app.indicators.plugins.sma import SMAPlugin


class IndicatorRegistry:
    def __init__(self) -> None:
        self._plugins: dict[str, IndicatorPlugin] = {}

    def register(self, plugin: IndicatorPlugin) -> None:
        self._plugins[plugin.key.upper()] = plugin

    def get(self, plugin_key: str) -> IndicatorPlugin:
        key = plugin_key.upper()
        if key not in self._plugins:
            raise KeyError(f"Indicator plugin not registered: {plugin_key}")
        return self._plugins[key]

    def list(self) -> list[IndicatorPlugin]:
        return list(self._plugins.values())


indicator_registry = IndicatorRegistry()
indicator_registry.register(SMAPlugin())
indicator_registry.register(CustomZoneExamplePlugin())
