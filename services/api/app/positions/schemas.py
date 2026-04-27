from datetime import datetime

from pydantic import BaseModel

from app.trading.schemas import OrderSide, PositionStatus, TradingMode


class PositionCloseRequest(BaseModel):
    client_confirmation: dict[str, object] | None = None


class PositionTpUpdate(BaseModel):
    tp: float


class PositionRead(BaseModel):
    id: int
    user_id: int | None
    order_id: int | None
    internal_symbol: str
    broker_symbol: str
    mode: TradingMode
    account_login: int | None
    account_server: str | None
    side: OrderSide
    volume: float
    open_price: float
    current_price: float | None
    close_price: float | None = None
    sl: float | None
    tp: float | None
    profit: float | None
    swap: float | None = None
    commission: float | None = None
    status: PositionStatus
    mt5_position_ticket: int | None
    closing_deal_ticket: int | None = None
    magic_number: int | None
    opened_at: datetime
    closed_at: datetime | None
    updated_at: datetime
    tp_percent: float | None = None

    model_config = {"from_attributes": True}
