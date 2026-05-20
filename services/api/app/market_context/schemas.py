from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


DollarStrengthState = Literal["WEAK", "STRONG", "NEUTRAL", "UNKNOWN"]


class DollarStrengthRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    symbol: str = "DXY"
    dxy_value: float | None = None
    sma30: float | None = None
    difference: float | None = None
    state: DollarStrengthState = "UNKNOWN"
    trading_allowed: bool = True
    reason: str = "usd_strength_unknown"
    slope_days: int = 3
    slope_pct: float | None = None
    strong_drop_override_active: bool = False
    source: str = "synthetic_mt5"
    updated_at: datetime | None = None
    valid_until: datetime | None = None
    missing_symbols: list[str] = []
    symbols_used: list[str] = []
    error_message: str | None = None
    stale: bool = False


class DollarStrengthRecomputeRead(BaseModel):
    ok: bool
    snapshot: DollarStrengthRead
    message: str
