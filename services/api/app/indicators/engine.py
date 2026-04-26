from sqlalchemy import select
from sqlalchemy.orm import Session

from app.candles.models import Candle
from app.indicators.models import IndicatorConfig
from app.indicators.plugins.base import IndicatorContext
from app.indicators.registry import indicator_registry


class IndicatorEngine:
    def __init__(self, db: Session) -> None:
        self.db = db

    def calculate(
        self,
        plugin_key: str,
        symbol: str,
        timeframe: str,
        params: dict[str, object] | None = None,
        limit: int = 300,
        config_id: int | None = None,
    ) -> dict[str, object]:
        plugin = indicator_registry.get(plugin_key)
        candles = self._load_candles(symbol=symbol, timeframe=timeframe, limit=limit)
        merged_params = {**plugin.default_params, **(params or {})}
        output = plugin.calculate(
            candles,
            merged_params,
            IndicatorContext(symbol=symbol.upper(), timeframe=timeframe, config_id=config_id),
        )
        return {
            "indicator": plugin.key,
            "params": merged_params,
            "symbol": symbol.upper(),
            "timeframe": timeframe,
            "output": output,
        }

    def calculate_config(self, config: IndicatorConfig, plugin_key: str, limit: int = 500) -> dict[str, object]:
        result = self.calculate(
            plugin_key=plugin_key,
            symbol=config.internal_symbol,
            timeframe=config.timeframe,
            params=config.params_json,
            limit=limit,
            config_id=config.id,
        )
        output = result.get("output")
        if isinstance(output, dict):
            output["style"] = {**dict(output.get("style") or {}), **dict(config.display_settings_json or {})}
        return result

    def _load_candles(self, symbol: str, timeframe: str, limit: int) -> list[Candle]:
        rows = list(
            self.db.scalars(
                select(Candle)
                .where(Candle.internal_symbol == symbol.upper(), Candle.timeframe == timeframe)
                .order_by(Candle.time.desc())
                .limit(limit)
            )
        )
        rows.reverse()
        return rows
