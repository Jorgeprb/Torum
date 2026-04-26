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
