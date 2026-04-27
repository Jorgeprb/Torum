from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.mt5.schemas import MT5AccountPayload


class TickInput(BaseModel):
    internal_symbol: str | None = Field(default=None, min_length=3, max_length=32)
    symbol: str | None = Field(default=None, min_length=3, max_length=32)
    broker_symbol: str = Field(min_length=1, max_length=64)
    time: datetime
    time_msc: int | None = Field(default=None, ge=0)
    bid: float | None = Field(default=None, gt=0)
    ask: float | None = Field(default=None, gt=0)
    last: float | None = Field(default=None, gt=0)
    volume: float | None = Field(default=0, ge=0)
    source: str | None = Field(default=None, min_length=1, max_length=32)

    @model_validator(mode="after")
    def validate_symbol_and_price(self) -> "TickInput":
        if self.internal_symbol is None and self.symbol is None:
            raise ValueError("internal_symbol or symbol is required")
        if self.bid is None and self.ask is None and self.last is None:
            raise ValueError("At least one of bid, ask or last is required")
        return self

    @property
    def resolved_internal_symbol(self) -> str:
        return self.internal_symbol or self.symbol or ""


class TickBatchRequest(BaseModel):
    source: str = Field(default="MT5", min_length=1, max_length=32)
    account: MT5AccountPayload | None = None
    ticks: list[TickInput] = Field(min_length=1, max_length=10000)


class TickRead(BaseModel):
    time: datetime
    time_msc: int
    internal_symbol: str
    broker_symbol: str
    bid: float | None = None
    ask: float | None = None
    last: float | None = None
    volume: float | None = None
    source: str


class TickBatchResponse(BaseModel):
    received: int
    inserted: int
    duplicates_ignored: int
    candles_updated: int
    errors: list[str] = Field(default_factory=list)
    accepted_ticks: int
    updated_candles: int
    source: str | None = None
    min_time: datetime | None = None
    max_time: datetime | None = None
    max_time_msc: int | None = None
    last_bid: float | None = None
    last_ask: float | None = None
    last_broker_symbol: str | None = None
