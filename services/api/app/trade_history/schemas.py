from datetime import datetime

from pydantic import BaseModel


class TradeHistoryItem(BaseModel):
    id: int
    position_id: int
    order_id: int | None
    account_login: int | None = None
    account_server: str | None = None
    opened_at: datetime
    closed_at: datetime | None
    open_time_msc: int | None = None
    close_time_msc: int | None = None
    enrichment_status: str = "CONFIRMED"
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
    fee: float | None = None
    net_profit: float | None = None
    mode: str
    mt5_position_ticket: int | None
    closing_deal_ticket: int | None = None
    status: str
