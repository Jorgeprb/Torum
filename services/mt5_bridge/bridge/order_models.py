from typing import Any, Literal

from pydantic import BaseModel, Field

TradingMode = Literal["PAPER", "DEMO", "LIVE"]
OrderSide = Literal["BUY", "SELL"]
OrderType = Literal["MARKET"]


class MarketOrderRequest(BaseModel):
    internal_symbol: str = Field(min_length=3, max_length=32)
    broker_symbol: str = Field(min_length=1, max_length=64)
    mode: TradingMode
    side: OrderSide
    order_type: OrderType = "MARKET"
    volume: float = Field(gt=0)
    sl: float | None = Field(default=None, gt=0)
    tp: float | None = Field(default=None, gt=0)
    deviation_points: int = Field(default=20, ge=0)
    magic_number: int = 260426
    comment: str | None = None


class BridgeOrderResponse(BaseModel):
    ok: bool
    retcode: int | None = None
    comment: str | None = None
    order: int | None = None
    deal: int | None = None
    position: int | None = None
    price: float | None = None
    volume: float | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class ClosePositionRequest(BaseModel):
    internal_symbol: str
    broker_symbol: str
    side: OrderSide
    volume: float = Field(gt=0)
    mode: TradingMode
    magic_number: int | None = None


class OrderExecutionSettingsRequest(BaseModel):
    enabled: bool


class OrderExecutionSettingsResponse(BaseModel):
    enabled: bool
    allowed_account_modes: list[str]
    enable_real_trading: bool
    message: str
