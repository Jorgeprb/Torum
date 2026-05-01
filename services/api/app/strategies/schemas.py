from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.market_data.timeframes import Timeframe
from app.strategies.signals import SignalSide, SignalStatus, SignalType
from app.trading.schemas import TradingMode


class StrategyDefinitionRead(BaseModel):
    id: int
    key: str
    name: str
    version: str
    description: str
    enabled: bool
    default_params_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class StrategyConfigCreate(BaseModel):
    strategy_key: str = Field(min_length=3, max_length=100)
    internal_symbol: str = Field(min_length=3, max_length=32)
    timeframe: Timeframe
    enabled: bool = False
    mode: TradingMode = "PAPER"
    params_json: dict[str, Any] = Field(default_factory=dict)
    risk_profile_json: dict[str, Any] | None = None
    schedule_json: dict[str, Any] | None = None

    @model_validator(mode="after")
    def normalize(self) -> "StrategyConfigCreate":
        self.strategy_key = self.strategy_key.lower()
        self.internal_symbol = self.internal_symbol.upper()
        return self


class StrategyConfigUpdate(BaseModel):
    enabled: bool | None = None
    mode: TradingMode | None = None
    params_json: dict[str, Any] | None = None
    risk_profile_json: dict[str, Any] | None = None
    schedule_json: dict[str, Any] | None = None


class StrategyConfigRead(BaseModel):
    id: int
    user_id: int | None
    strategy_key: str
    internal_symbol: str
    timeframe: Timeframe
    enabled: bool
    mode: TradingMode
    params_json: dict[str, Any]
    risk_profile_json: dict[str, Any] | None
    schedule_json: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class StrategySettingsRead(BaseModel):
    id: int
    user_id: int | None
    strategies_enabled: bool
    strategy_live_enabled: bool
    default_mode: TradingMode
    max_signals_per_run: int | None

    model_config = ConfigDict(from_attributes=True)


class StrategySettingsUpdate(BaseModel):
    strategies_enabled: bool | None = None
    strategy_live_enabled: bool | None = None
    default_mode: TradingMode | None = None
    max_signals_per_run: int | None = Field(default=None, ge=1, le=100)


class StrategySignalRead(BaseModel):
    id: int
    strategy_config_id: int | None
    strategy_key: str
    user_id: int | None
    internal_symbol: str
    timeframe: Timeframe
    signal_type: SignalType
    side: SignalSide
    entry_type: str
    confidence: float
    suggested_volume: float | None
    sl: float | None
    tp: float | None
    reason: str
    metadata_json: dict[str, Any]
    status: SignalStatus
    risk_result_json: dict[str, Any] | None
    order_id: int | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class StrategyRunRead(BaseModel):
    id: int
    strategy_config_id: int | None
    strategy_key: str
    started_at: datetime
    finished_at: datetime | None
    status: Literal["STARTED", "FINISHED", "FAILED"]
    candles_used: int
    indicators_used_json: dict[str, Any]
    context_summary_json: dict[str, Any]
    error_message: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class StrategyRunResult(BaseModel):
    ok: bool
    run: StrategyRunRead
    signal: StrategySignalRead | None = None
    message: str
    order_id: int | None = None
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class TorumV1AssetStatusRead(BaseModel):
    symbol: str
    enabled: bool
    status: Literal["LOCKED", "UNLOCKED"]
    reason: str
    timeframe: str
    session_start: str
    session_end: str
    unlocked_at: datetime | None
    blocked_by_news: bool
    active_config_id: int | None


class TorumV1StatusRead(BaseModel):
    strategy_key: str
    enabled: bool
    use_news: bool
    server_time: datetime
    madrid_time: datetime
    assets: dict[str, TorumV1AssetStatusRead]
