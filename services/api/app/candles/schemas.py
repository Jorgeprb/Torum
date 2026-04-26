from datetime import datetime

from pydantic import BaseModel, Field

from app.market_data.timeframes import Timeframe


class CandleRead(BaseModel):
    time: int
    internal_symbol: str
    timeframe: Timeframe
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None
    tick_count: int | None = None
    source: str


class CandleUpdateMessage(BaseModel):
    type: str = "candle_update"
    symbol: str
    timeframe: Timeframe
    candle: CandleRead


class CandleRow(BaseModel):
    time: datetime
    internal_symbol: str
    timeframe: Timeframe
    open: float
    high: float
    low: float
    close: float
    volume: float = 0
    tick_count: int = Field(default=0, ge=0)
    source: str = "TICK_AGGREGATOR"
