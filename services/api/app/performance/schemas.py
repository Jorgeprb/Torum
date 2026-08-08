from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

CapitalMovementKind = Literal["INITIAL", "DEPOSIT", "WITHDRAWAL", "ADJUSTMENT"]


class CapitalMovementCreate(BaseModel):
    kind: CapitalMovementKind
    amount: float
    occurred_at: datetime
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_amount(self) -> "CapitalMovementCreate":
        if not float(self.amount):
            raise ValueError("Capital movement amount cannot be zero")
        if self.kind in {"INITIAL", "DEPOSIT"} and self.amount < 0:
            self.amount = abs(self.amount)
        elif self.kind == "WITHDRAWAL" and self.amount > 0:
            self.amount = -self.amount
        return self


class CapitalMovementRead(BaseModel):
    id: int
    occurred_at: datetime
    amount: float
    kind: str
    source: str
    currency: str | None = None
    account_login: int | None = None
    account_server: str | None = None
    note: str | None = None
    external_id: int | None = None
    deletable: bool = False


class PerformancePoint(BaseModel):
    time: datetime
    return_pct: float
    cumulative_profit: float
    capital: float | None = None


class MonthlyPerformance(BaseModel):
    key: str
    label: str
    from_time: datetime
    to_time: datetime
    return_pct: float | None
    net_profit: float
    cash_flow: float
    trades: int
    wins: int
    losses: int


class PerformanceSummary(BaseModel):
    from_time: datetime
    to_time: datetime
    currency: str
    return_pct: float | None
    net_profit: float
    gross_profit: float
    gross_loss: float
    cash_flow: float
    capital_start: float | None
    capital_end: float | None
    current_balance: float | None
    reconciliation_difference: float | None
    trades: int
    wins: int
    losses: int
    win_rate_pct: float | None
    max_drawdown_pct: float | None
    best_month_key: str | None = None
    best_month_return_pct: float | None = None
    basis_source: str
    basis_note: str
    pending_trades: int = 0
    points: list[PerformancePoint] = Field(default_factory=list)
    months: list[MonthlyPerformance] = Field(default_factory=list)
    capital_movements: list[CapitalMovementRead] = Field(default_factory=list)
