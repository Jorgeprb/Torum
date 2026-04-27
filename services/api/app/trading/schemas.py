from typing import Literal

from pydantic import BaseModel, Field, model_validator

TradingMode = Literal["PAPER", "DEMO", "LIVE"]
MarketDataSource = Literal["MT5", "MOCK"]
OrderSide = Literal["BUY", "SELL"]
OrderType = Literal["MARKET"]
OrderStatus = Literal["CREATED", "VALIDATING", "REJECTED", "SENT", "EXECUTED", "FAILED", "CANCELLED", "CLOSED"]
PositionStatus = Literal["OPEN", "CLOSED"]


class ClientConfirmation(BaseModel):
    confirmed: bool = False
    mode_acknowledged: TradingMode | None = None
    live_text: str | None = None
    no_stop_loss_acknowledged: bool = False


class ManualOrderRequest(BaseModel):
    internal_symbol: str = Field(min_length=3, max_length=32)
    side: OrderSide
    order_type: OrderType = "MARKET"
    volume: float
    sl: float | None = Field(default=None, gt=0)
    tp: float | None = Field(default=None, gt=0)
    tp_percent: float | None = Field(default=None, gt=0, le=20)
    comment: str | None = Field(default="Manual order from Torum", max_length=240)
    magic_number: int | None = None
    deviation_points: int | None = Field(default=None, ge=0)
    client_confirmation: ClientConfirmation | None = None

    @model_validator(mode="after")
    def normalize_symbol(self) -> "ManualOrderRequest":
        self.internal_symbol = self.internal_symbol.upper()
        return self


class ManualOrderResponse(BaseModel):
    ok: bool
    order_id: int
    status: OrderStatus
    mode: TradingMode
    message: str
    warnings: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class TradingSettingsRead(BaseModel):
    id: int
    user_id: int | None
    trading_mode: TradingMode
    live_trading_enabled: bool
    require_live_confirmation: bool
    default_volume: float
    default_magic_number: int
    default_deviation_points: int
    max_order_volume: float | None
    allow_market_orders: bool
    allow_pending_orders: bool
    is_paused: bool
    long_only: bool
    default_take_profit_percent: float
    use_stop_loss: bool
    lot_per_equity_enabled: bool
    equity_per_0_01_lot: float
    minimum_lot: float
    allow_manual_lot_adjustment: bool
    show_bid_line: bool
    show_ask_line: bool
    mt5_order_execution_enabled: bool
    market_data_source: MarketDataSource

    model_config = {"from_attributes": True}


class TradingSettingsUpdate(BaseModel):
    trading_mode: TradingMode | None = None
    live_trading_enabled: bool | None = None
    require_live_confirmation: bool | None = None
    default_volume: float | None = Field(default=None, gt=0)
    default_magic_number: int | None = None
    default_deviation_points: int | None = Field(default=None, ge=0)
    max_order_volume: float | None = Field(default=None, gt=0)
    allow_market_orders: bool | None = None
    allow_pending_orders: bool | None = None
    is_paused: bool | None = None
    long_only: bool | None = None
    default_take_profit_percent: float | None = Field(default=None, gt=0, le=20)
    use_stop_loss: bool | None = None
    lot_per_equity_enabled: bool | None = None
    equity_per_0_01_lot: float | None = Field(default=None, gt=0)
    minimum_lot: float | None = Field(default=None, gt=0)
    allow_manual_lot_adjustment: bool | None = None
    show_bid_line: bool | None = None
    show_ask_line: bool | None = None
    mt5_order_execution_enabled: bool | None = None
    market_data_source: MarketDataSource | None = None


class LotSizeResponse(BaseModel):
    available_equity: float | None
    equity_per_0_01_lot: float
    base_lot: float
    multiplier: int
    effective_lot: float
    min_lot: float
    lot_step: float
    source: str


class MT5OrderExecutionSettingsRead(BaseModel):
    torum_enabled: bool
    bridge_configured: bool
    bridge_connected: bool
    bridge_enabled: bool | None = None
    bridge_message: str | None = None
