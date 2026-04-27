from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

AccountTradeMode = Literal["DEMO", "REAL", "UNKNOWN"]


class MT5AccountPayload(BaseModel):
    login: int | None = None
    server: str | None = None
    name: str | None = None
    company: str | None = None
    currency: str | None = None
    balance: float | None = None
    equity: float | None = None
    margin: float | None = None
    margin_free: float | None = None
    leverage: int | None = None
    trade_mode: AccountTradeMode = "UNKNOWN"


class MT5StatusPayload(BaseModel):
    connected_to_mt5: bool = False
    connected_to_backend: bool = True
    account_trade_mode: AccountTradeMode = "UNKNOWN"
    account: MT5AccountPayload | None = None
    active_symbols: list[str] = Field(default_factory=list)
    last_tick_time_by_symbol: dict[str, datetime] = Field(default_factory=dict)
    ticks_sent_total: int = 0
    last_batch_sent_at: datetime | None = None
    errors_count: int = 0
    message: str | None = None


class MT5StatusRead(MT5StatusPayload):
    updated_at: datetime | None = None


class MT5PositionPayload(BaseModel):
    ticket: int | None = None
    identifier: int | None = None
    symbol: str
    type: int | None = None
    side: str | None = None
    volume: float | None = None
    price_open: float | None = None
    price_current: float | None = None
    sl: float | None = None
    tp: float | None = None
    profit: float | None = None
    magic: int | None = None
    time: int | float | None = None
    comment: str | None = None
    raw: dict | None = None


class MT5PositionsSyncPayload(BaseModel):
    account: MT5AccountPayload | None = None
    positions: list[dict] = Field(default_factory=list)
    closed_deals: list[dict] = Field(default_factory=list)


class MT5PositionsSyncRead(BaseModel):
    ok: bool = True
    received: int
    deals_received: int = 0
    created: int
    updated: int
    closed: int
