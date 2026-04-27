from datetime import datetime

from pydantic import BaseModel


class TradeHistoryItem(BaseModel):
    id: int
    position_id: int
    order_id: int | None
    opened_at: datetime
    closed_at: datetime | None
    internal_symbol: str
    broker_symbol: str
    side: str
    volume: float
    open_price: float
    close_price: float | None
    tp: float | None
    profit: float | None
    swap: float | None = None
    commission: float | None = None
    mode: str
    mt5_position_ticket: int | None
    closing_deal_ticket: int | None = None
    status: str
