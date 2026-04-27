from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.market_data.timeframes import Timeframe

IndicatorOutputType = Literal["line", "histogram", "band", "zone", "marker", "shape"]


class IndicatorPoint(BaseModel):
    time: int
    value: float


class IndicatorLineOutput(BaseModel):
    type: Literal["line"] = "line"
    name: str
    symbol: str
    timeframe: Timeframe
    points: list[IndicatorPoint]
    style: dict[str, Any] = Field(default_factory=dict)


class IndicatorZoneItem(BaseModel):
    start_time: int
    end_time: int
    price_min: float | None = None
    price_max: float | None = None
    label: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class IndicatorZoneOutput(BaseModel):
    type: Literal["zone"] = "zone"
    name: str
    symbol: str
    timeframe: Timeframe
    zones: list[IndicatorZoneItem]
    style: dict[str, Any] = Field(default_factory=dict)


class IndicatorMarkerItem(BaseModel):
    time: int
    position: str
    shape: str
    text: str | None = None


class IndicatorMarkerOutput(BaseModel):
    type: Literal["marker"] = "marker"
    name: str
    symbol: str
    timeframe: Timeframe
    markers: list[IndicatorMarkerItem]
    style: dict[str, Any] = Field(default_factory=dict)


class IndicatorCalculationResponse(BaseModel):
    indicator: str
    params: dict[str, Any]
    symbol: str
    timeframe: Timeframe
    output: dict[str, Any]


class IndicatorRead(BaseModel):
    id: int
    name: str
    plugin_key: str
    version: str
    description: str
    output_type: str
    enabled: bool
    default_params_json: dict[str, Any]

    model_config = ConfigDict(from_attributes=True)


class IndicatorConfigCreate(BaseModel):
    indicator_id: int
    internal_symbol: str = Field(min_length=3, max_length=32)
    timeframe: Timeframe
    enabled: bool = True
    params_json: dict[str, Any] = Field(default_factory=dict)
    display_settings_json: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def normalize_symbol(self) -> "IndicatorConfigCreate":
        self.internal_symbol = self.internal_symbol.upper()
        return self


class IndicatorConfigUpdate(BaseModel):
    enabled: bool | None = None
    params_json: dict[str, Any] | None = None
    display_settings_json: dict[str, Any] | None = None


class IndicatorConfigRead(BaseModel):
    id: int
    user_id: int | None
    indicator_id: int
    internal_symbol: str
    timeframe: Timeframe
    enabled: bool
    params_json: dict[str, Any]
    display_settings_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChartOverlaysResponse(BaseModel):
    symbol: str
    timeframe: Timeframe
    indicators: list[dict[str, Any]]
    no_trade_zones: list[dict[str, Any]]
    drawings: list[dict[str, Any]] = Field(default_factory=list)
    price_alerts: list[dict[str, Any]] = Field(default_factory=list)
    positions: list[dict[str, Any]] = Field(default_factory=list)
