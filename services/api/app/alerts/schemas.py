from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.market_data.timeframes import Timeframe

AlertConditionType = Literal["BELOW"]
AlertStatus = Literal["ACTIVE", "TRIGGERED", "CANCELLED", "EXPIRED"]
AlertSource = Literal["CHART", "MANUAL", "IMPORT"]


class PriceAlertCreate(BaseModel):
    internal_symbol: str = Field(min_length=3, max_length=32)
    timeframe: Timeframe | None = None
    condition_type: str = "BELOW"
    target_price: float = Field(gt=0)
    source: AlertSource = "CHART"
    message: str | None = Field(default=None, max_length=240)

    @model_validator(mode="after")
    def normalize_and_enforce_below(self) -> "PriceAlertCreate":
        self.internal_symbol = self.internal_symbol.upper()
        self.condition_type = self.condition_type.upper()
        if self.condition_type != "BELOW":
            raise ValueError("Only BELOW price alerts are supported in Phase 9")
        return self


class PriceAlertUpdate(BaseModel):
    condition_type: str | None = None
    target_price: float | None = Field(default=None, gt=0)
    message: str | None = Field(default=None, max_length=240)
    status: Literal["ACTIVE", "CANCELLED"] | None = None

    @model_validator(mode="after")
    def reject_non_below(self) -> "PriceAlertUpdate":
        if self.condition_type is not None and self.condition_type.upper() != "BELOW":
            raise ValueError("Only BELOW price alerts are supported in Phase 9")
        return self


class PriceAlertRead(BaseModel):
    id: str
    user_id: int
    internal_symbol: str
    timeframe: str | None
    condition_type: AlertConditionType
    target_price: float
    status: AlertStatus
    source: AlertSource
    message: str | None
    triggered_at: datetime | None
    triggered_price: float | None
    last_checked_price: float | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PriceAlertTriggeredEvent(BaseModel):
    type: Literal["price_alert_triggered"] = "price_alert_triggered"
    alert_id: str
    user_id: int
    symbol: str
    timeframe: str | None
    target_price: float
    triggered_price: float
    triggered_at: datetime


class PushSubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscriptionCreate(BaseModel):
    endpoint: str
    keys: PushSubscriptionKeys
    user_agent: str | None = None
    device_name: str | None = Field(default=None, max_length=120)


class PushSubscriptionRead(BaseModel):
    id: str
    user_id: int
    endpoint: str
    user_agent: str | None
    device_name: str | None
    enabled: bool
    created_at: datetime
    updated_at: datetime
    last_used_at: datetime | None

    model_config = {"from_attributes": True}


class PushTestResponse(BaseModel):
    ok: bool
    sent: int
    failed: int
    message: str
