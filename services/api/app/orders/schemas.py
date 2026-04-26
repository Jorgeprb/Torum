from datetime import datetime

from pydantic import BaseModel

from app.trading.schemas import OrderSide, OrderStatus, OrderType, TradingMode


class OrderRead(BaseModel):
    id: int
    user_id: int | None
    internal_symbol: str
    broker_symbol: str
    mode: TradingMode
    account_login: int | None
    account_server: str | None
    side: OrderSide
    order_type: OrderType
    volume: float
    requested_price: float | None
    executed_price: float | None
    sl: float | None
    tp: float | None
    status: OrderStatus
    rejection_reason: str | None
    mt5_order_ticket: int | None
    mt5_deal_ticket: int | None
    mt5_position_ticket: int | None
    magic_number: int | None
    comment: str | None
    source: str
    strategy_signal_id: int | None = None
    strategy_key: str | None = None
    created_at: datetime
    updated_at: datetime
    executed_at: datetime | None

    model_config = {"from_attributes": True}
