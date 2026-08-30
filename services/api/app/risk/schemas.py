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


class GoldCorrelationRead(BaseModel):
    timeframe: str = "H1"
    samples: int = 0
    pearson: float | None = None
    beta_xaueur_from_xauusd: float = 1.0
    beta_xauusd_from_xaueur: float = 1.0
    source: str = "FALLBACK_1_TO_1"


class StopOutLineRead(BaseModel):
    symbol: str
    visible: bool
    price: float | None = None
    account_currency: str | None = None
    current_equity: float | None = None
    current_margin: float | None = None
    threshold_equity: float | None = None
    stop_out_mode: str | None = None
    stop_out_value: float | None = None
    positions_on_symbol: int = 0
    gold_positions_total: int = 0
    correlated_other_symbol: str | None = None
    projected_other_price: float | None = None
    correlation: GoldCorrelationRead = Field(default_factory=GoldCorrelationRead)
    estimated: bool = True
    message: str | None = None
