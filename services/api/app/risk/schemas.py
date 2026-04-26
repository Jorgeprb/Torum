from pydantic import BaseModel, Field


class RiskDecision(BaseModel):
    allowed: bool
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
