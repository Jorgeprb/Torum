from datetime import datetime

from pydantic import BaseModel, Field


class RiskDecision(BaseModel):
    allowed: bool
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class RiskPositionExposureRead(BaseModel):
    position_id: int
    internal_symbol: str
    side: str
    volume: float
    open_price: float
    loss_at_stress: float


class RiskSnapshotRead(BaseModel):
    symbol: str
    mode: str = "ALL"
    source: str = "ALL"
    account_login: int | None = None
    account_server: str | None = None
    account_currency: str | None = None
    profit_currency: str | None = None
    conversion_rate: float = 1.0
    ath_price: float | None
    stress_price: float | None
    balance: float | None
    contract_size: float
    current_loss: float | None
    risk_limit: float | None
    remaining_risk: float | None
    positions_count: int
    positions: list[RiskPositionExposureRead] = Field(default_factory=list)
    updated_at: datetime | None
    valid: bool
    dirty: bool
    message: str | None = None


class RiskCandidatePreviewRead(BaseModel):
    snapshot: RiskSnapshotRead
    side: str
    volume: float
    price: float | None
    candidate_loss: float | None
    projected_loss: float | None
    projected_balance: float | None
    projected_balance_pct: float | None
    breaches_limit: bool
    accepted_required: bool = True
