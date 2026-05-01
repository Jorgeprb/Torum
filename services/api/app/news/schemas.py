from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.news.normalizer import ensure_utc_datetime, normalize_country, normalize_currency, normalize_impact


class NewsEventBase(BaseModel):
    source: str = Field(default="manual", min_length=1, max_length=80)
    external_id: str | None = Field(default=None, max_length=160)
    country: str = Field(min_length=1, max_length=80)
    currency: str = Field(min_length=1, max_length=16)
    impact: str = Field(min_length=1, max_length=24)
    title: str = Field(min_length=1, max_length=240)
    event_time: datetime
    previous_value: str | None = Field(default=None, max_length=120)
    forecast_value: str | None = Field(default=None, max_length=120)
    actual_value: str | None = Field(default=None, max_length=120)
    url: str | None = None
    raw_payload_json: dict[str, Any] | None = None

    @field_validator("country")
    @classmethod
    def normalize_country_field(cls, value: str) -> str:
        return normalize_country(value)

    @field_validator("currency")
    @classmethod
    def normalize_currency_field(cls, value: str) -> str:
        return normalize_currency(value)

    @field_validator("impact")
    @classmethod
    def normalize_impact_field(cls, value: str) -> str:
        return normalize_impact(value)

    @field_validator("event_time")
    @classmethod
    def normalize_time_field(cls, value: datetime) -> datetime:
        return ensure_utc_datetime(value)


class NewsEventCreate(NewsEventBase):
    pass


class NewsEventUpdate(BaseModel):
    source: str | None = Field(default=None, min_length=1, max_length=80)
    external_id: str | None = Field(default=None, max_length=160)
    country: str | None = Field(default=None, min_length=1, max_length=80)
    currency: str | None = Field(default=None, min_length=1, max_length=16)
    impact: str | None = Field(default=None, min_length=1, max_length=24)
    title: str | None = Field(default=None, min_length=1, max_length=240)
    event_time: datetime | None = None
    previous_value: str | None = Field(default=None, max_length=120)
    forecast_value: str | None = Field(default=None, max_length=120)
    actual_value: str | None = Field(default=None, max_length=120)
    url: str | None = None
    raw_payload_json: dict[str, Any] | None = None

    @model_validator(mode="after")
    def normalize_optional_fields(self) -> "NewsEventUpdate":
        if self.country is not None:
            self.country = normalize_country(self.country)
        if self.currency is not None:
            self.currency = normalize_currency(self.currency)
        if self.impact is not None:
            self.impact = normalize_impact(self.impact)
        if self.event_time is not None:
            self.event_time = ensure_utc_datetime(self.event_time)
        return self


class NewsEventRead(NewsEventBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NewsSettingsRead(BaseModel):
    id: int
    user_id: int | None
    draw_news_zones_enabled: bool
    block_trading_during_news: bool
    minutes_before: int
    minutes_after: int
    currencies_filter: list[str]
    countries_filter: list[str]
    impact_filter: list[str]
    affected_symbols: list[str]
    provider_enabled: bool
    provider_name: str
    provider: str
    auto_sync_enabled: bool
    sync_interval_minutes: int
    days_ahead: int
    last_sync_at: datetime | None
    last_sync_status: str | None
    last_sync_error: str | None

    model_config = ConfigDict(from_attributes=True)


class NewsSettingsUpdate(BaseModel):
    draw_news_zones_enabled: bool | None = None
    block_trading_during_news: bool | None = None
    minutes_before: int | None = Field(default=None, ge=0, le=1440)
    minutes_after: int | None = Field(default=None, ge=0, le=1440)
    currencies_filter: list[str] | None = None
    countries_filter: list[str] | None = None
    impact_filter: list[str] | None = None
    affected_symbols: list[str] | None = None
    provider_enabled: bool | None = None
    provider_name: str | None = Field(default=None, min_length=1, max_length=80)
    provider: str | None = Field(default=None, min_length=3, max_length=24)
    auto_sync_enabled: bool | None = None
    sync_interval_minutes: int | None = Field(default=None, ge=15, le=10080)
    days_ahead: int | None = Field(default=None, ge=1, le=90)

    @model_validator(mode="after")
    def normalize_filters(self) -> "NewsSettingsUpdate":
        if self.currencies_filter is not None:
            self.currencies_filter = [normalize_currency(value) for value in self.currencies_filter if value.strip()]
        if self.countries_filter is not None:
            self.countries_filter = [normalize_country(value) for value in self.countries_filter if value.strip()]
        if self.impact_filter is not None:
            self.impact_filter = [normalize_impact(value) for value in self.impact_filter if value.strip()]
        if self.affected_symbols is not None:
            self.affected_symbols = [value.strip().upper() for value in self.affected_symbols if value.strip()]
        if self.provider is not None:
            self.provider = self.provider.strip().upper()
            if self.provider not in {"FINNHUB", "MANUAL"}:
                raise ValueError("provider must be FINNHUB or MANUAL")
        return self


class NewsJsonImportRequest(BaseModel):
    source: str = Field(default="manual", min_length=1, max_length=80)
    events: list[dict[str, Any]]


class NewsCsvImportRequest(BaseModel):
    source: str = Field(default="manual_csv", min_length=1, max_length=80)
    csv_text: str = Field(min_length=1)


class NewsImportResponse(BaseModel):
    received: int
    saved: int
    zones_generated: int
    errors: list[str] = Field(default_factory=list)


class NewsProviderSyncResponse(NewsImportResponse):
    provider: str
    started_at: datetime
    finished_at: datetime
    status: str


class NewsProviderStatusRead(BaseModel):
    provider: str
    provider_enabled: bool
    auto_sync_enabled: bool
    sync_interval_minutes: int
    days_ahead: int
    block_trading_during_news: bool
    draw_news_zones_enabled: bool
    minutes_before: int
    minutes_after: int
    last_sync_at: datetime | None
    last_sync_status: str | None
    last_sync_error: str | None
    next_event: NewsEventRead | None = None
    imported_events: int
    generated_zones: int
