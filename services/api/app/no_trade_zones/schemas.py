from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.news.normalizer import ensure_utc_datetime


class NoTradeZoneCreate(BaseModel):
    news_event_id: int | None = None
    source: str = Field(default="manual", min_length=1, max_length=80)
    reason: str = Field(min_length=1, max_length=320)
    internal_symbol: str = Field(min_length=3, max_length=32)
    start_time: datetime
    end_time: datetime
    enabled: bool = True
    blocks_trading: bool = False
    visual_only: bool = True

    @model_validator(mode="after")
    def normalize_and_validate(self) -> "NoTradeZoneCreate":
        self.internal_symbol = self.internal_symbol.upper()
        self.start_time = ensure_utc_datetime(self.start_time)
        self.end_time = ensure_utc_datetime(self.end_time)
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self


class NoTradeZoneUpdate(BaseModel):
    reason: str | None = Field(default=None, min_length=1, max_length=320)
    start_time: datetime | None = None
    end_time: datetime | None = None
    enabled: bool | None = None
    blocks_trading: bool | None = None
    visual_only: bool | None = None

    @model_validator(mode="after")
    def validate_window(self) -> "NoTradeZoneUpdate":
        if self.start_time is not None:
            self.start_time = ensure_utc_datetime(self.start_time)
        if self.end_time is not None:
            self.end_time = ensure_utc_datetime(self.end_time)
        if self.start_time is not None and self.end_time is not None and self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self


class NoTradeZoneRead(BaseModel):
    id: int
    news_event_id: int | None
    source: str
    reason: str
    internal_symbol: str
    start_time: datetime
    end_time: datetime
    enabled: bool
    blocks_trading: bool
    visual_only: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NoTradeZoneCheckResponse(BaseModel):
    blocked: bool
    symbol: str
    time: datetime
    zones: list[NoTradeZoneRead]


class NoTradeZoneRegenerateResponse(BaseModel):
    regenerated: int
