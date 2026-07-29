from datetime import datetime

from pydantic import BaseModel

from app.trading.schemas import OrderSide, PositionStatus, TradingMode


class PositionCloseRequest(BaseModel):
    client_confirmation: dict[str, object] | None = None
    fetch_close_deal: bool = False


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
    fee: float | None = None
    status: PositionStatus
    mt5_position_ticket: int | None
    mt5_position_identifier: int | None = None
    closing_deal_ticket: int | None = None
    magic_number: int | None
    opened_at: datetime
    closed_at: datetime | None
    open_time_msc: int | None = None
    close_time_msc: int | None = None
    enrichment_status: str = "CONFIRMED"
    missing_sync_count: int = 0
    last_seen_mt5_at: datetime | None = None
    sync_state: str = "CONFIRMED"
    updated_at: datetime
    tp_percent: float | None = None
    net_profit: float | None = None

    model_config = {"from_attributes": True}
