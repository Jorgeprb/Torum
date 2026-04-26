from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.candles.models import Candle
from app.drawings.models import ChartDrawing
from app.no_trade_zones.models import NoTradeZone
from app.strategies.models import StrategyConfig
from app.ticks.models import Tick


@dataclass(slots=True)
class StrategyContext:
    strategy_key: str
    config: StrategyConfig
    symbol: str
    timeframe: str
    mode: str
    now: datetime
    candles: list[Candle]
    latest_tick: Tick | None
    indicators: dict[str, Any] = field(default_factory=dict)
    no_trade_zones: list[NoTradeZone] = field(default_factory=list)
    manual_zones: list[ChartDrawing] = field(default_factory=list)
    open_positions: list[Any] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)

    @property
    def latest_close(self) -> float | None:
        return self.candles[-1].close if self.candles else None

    @property
    def latest_price(self) -> float | None:
        if self.latest_tick is None:
            return self.latest_close
        if self.latest_tick.last:
            return self.latest_tick.last
        if self.latest_tick.bid is not None and self.latest_tick.ask is not None:
            return (self.latest_tick.bid + self.latest_tick.ask) / 2
        return self.latest_tick.bid or self.latest_tick.ask or self.latest_close

    def summary(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "mode": self.mode,
            "candles": len(self.candles),
            "latest_price": self.latest_price,
            "manual_zones": len(self.manual_zones),
            "no_trade_zones": len(self.no_trade_zones),
            "indicators": list(self.indicators.keys()),
        }
