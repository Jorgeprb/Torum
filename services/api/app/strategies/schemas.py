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
    expected_revision: int | None = Field(default=None, ge=1)
    change_note: str | None = Field(default=None, max_length=240)


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
    revision: int
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
    manual_override: Literal["LOCKED", "UNLOCKED"] | None = None


class TorumV1ManualLockStateUpdate(BaseModel):
    symbol: Literal["XAUEUR", "XAUUSD"]
    # True = force H2/H3 unlocked, False = force locked, None = remove the
    # manual override and return to the normal automatic H2/H3 decision.
    unlocked: bool | None


class TorumV1StatusRead(BaseModel):
    strategy_key: str
    enabled: bool
    use_news: bool
    server_time: datetime
    madrid_time: datetime
    assets: dict[str, TorumV1AssetStatusRead]


class StrategyConfigVersionRead(BaseModel):
    id: int
    strategy_config_id: int
    user_id: int | None
    revision: int
    enabled: bool
    mode: TradingMode
    timeframe: Timeframe
    params_json: dict[str, Any]
    risk_profile_json: dict[str, Any] | None
    schedule_json: dict[str, Any] | None
    change_note: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TorumV1ConfigurationRead(BaseModel):
    strategy_key: Literal["torum_v1"] = "torum_v1"
    base_params: dict[str, Any]
    asset_overrides: dict[str, dict[str, Any]]
    configs: dict[str, StrategyConfigRead]
    enabled_by_symbol: dict[str, bool]
    mode_by_symbol: dict[str, TradingMode]
    schema: dict[str, Any]
    common_revision: int


class TorumV1ConfigurationUpdate(BaseModel):
    base_params: dict[str, Any]
    asset_overrides: dict[str, dict[str, Any]] = Field(default_factory=dict)
    enabled_by_symbol: dict[str, bool] = Field(default_factory=dict)
    mode_by_symbol: dict[str, TradingMode] = Field(default_factory=dict)
    expected_revisions: dict[str, int] = Field(default_factory=dict)
    change_note: str | None = Field(default=None, max_length=240)


class StrategyTraceStep(BaseModel):
    id: str
    label: str
    status: Literal["PASS", "FAIL", "WAIT", "SKIP", "WARN"]
    summary: str
    actual: Any | None = None
    required: Any | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class TorumV1SimulationRequest(BaseModel):
    symbol: str = Field(default="XAUUSD", min_length=3, max_length=32)
    params: dict[str, Any] | None = None
    candle_limit: int = Field(default=600, ge=100, le=5000)

    @model_validator(mode="after")
    def normalize_symbol(self) -> "TorumV1SimulationRequest":
        self.symbol = self.symbol.upper()
        return self


class TorumV1SimulationRead(BaseModel):
    symbol: str
    evaluated_at: datetime
    decision: Literal["BUY", "WAIT", "BLOCKED", "ERROR"]
    reason_code: str
    summary: str
    current_price: float | None
    steps: list[StrategyTraceStep]
    metadata: dict[str, Any] = Field(default_factory=dict)
    config_revision: int | None = None


class TorumV1ReplayRequest(BaseModel):
    symbol: str = Field(default="XAUUSD", min_length=3, max_length=32)
    params: dict[str, Any] | None = None
    candle_limit: int = Field(default=500, ge=100, le=2000)

    @model_validator(mode="after")
    def normalize_symbol(self) -> "TorumV1ReplayRequest":
        self.symbol = self.symbol.upper()
        return self


class TorumV1ReplaySignalRead(BaseModel):
    confirmation_time: datetime
    price: float
    pullback_pct: float | None = None
    pullback_low: float | None = None
    pullback_low_time: datetime | None = None
    operation_zone_id: int | str | None = None
    support_level: int | None = None
    desired_multiplier: int = 1
    reason: str


class TorumV1ReplayRead(BaseModel):
    symbol: str
    generated_at: datetime
    from_time: datetime | None
    to_time: datetime | None
    candles_analyzed: int
    signals: list[TorumV1ReplaySignalRead]
    signal_count: int
    coverage: dict[str, str]
    notes: list[str] = Field(default_factory=list)
    config_revision: int | None = None

class TorumV1BacktestRequest(BaseModel):
    symbol: str = Field(default="XAUUSD", min_length=3, max_length=32)
    params: dict[str, Any] | None = None
    candle_limit: int = Field(default=1500, ge=100, le=10000)
    from_time: datetime | None = None
    to_time: datetime | None = None
    initial_balance: float = Field(default=10000.0, gt=0.0, le=1_000_000_000.0)
    use_session: bool = True
    use_unlock: bool = True
    use_news: bool = True
    use_dxy: bool = True
    use_operation_zones: bool = True
    use_supports: bool = True
    use_ath_capacity: bool = True
    use_risk: bool = True
    selected_operation_zone_ids: list[str] = Field(default_factory=list, max_length=200)
    selected_support_zone_ids: list[str] = Field(default_factory=list, max_length=200)
    entry_model: Literal["CONFIRMATION_CLOSE", "NEXT_OPEN"] = "NEXT_OPEN"
    spread_points: float = Field(default=0.0, ge=0.0, le=100000.0)
    slippage_points: float = Field(default=0.0, ge=0.0, le=100000.0)
    commission_per_lot: float = Field(default=0.0, ge=0.0, le=100000.0)
    close_open_trades_at_end: bool = True
    debug_level: Literal["SUMMARY", "SIGNALS", "FULL"] = "SIGNALS"
    max_debug_events: int = Field(default=1500, ge=50, le=10000)

    @model_validator(mode="after")
    def normalize(self) -> "TorumV1BacktestRequest":
        self.symbol = self.symbol.upper()
        if self.from_time is not None and self.to_time is not None and self.from_time >= self.to_time:
            raise ValueError("from_time must be earlier than to_time")
        self.selected_operation_zone_ids = list(dict.fromkeys(str(item) for item in self.selected_operation_zone_ids))
        self.selected_support_zone_ids = list(dict.fromkeys(str(item) for item in self.selected_support_zone_ids))
        return self


class TorumV1BacktestCandleRead(BaseModel):
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None


class TorumV1BacktestZoneRead(BaseModel):
    id: str
    name: str | None = None
    direction: str = "BUY"
    time1: datetime
    time2: datetime | None = None
    price_min: float
    price_max: float
    selected: bool = True


class TorumV1BacktestSupportRead(BaseModel):
    id: str
    name: str | None = None
    level: int
    price: float
    lower_price: float
    upper_price: float
    enabled: bool = True
    selected: bool = True


class TorumV1BacktestPullbackRead(BaseModel):
    swing_high_time: datetime
    swing_high: float
    pullback_low_time: datetime
    pullback_low: float
    pullback_pct: float
    is_live: bool = False


class TorumV1BacktestTradeRead(BaseModel):
    id: str
    entry_time: datetime
    entry_price: float
    exit_time: datetime | None = None
    exit_price: float | None = None
    tp_price: float
    volume: float
    multiplier: int
    support_level: int | None = None
    support_zone_id: str | None = None
    operation_zone_id: str | None = None
    pullback_pct: float | None = None
    pullback_low: float | None = None
    pullback_low_time: datetime | None = None
    exit_reason: str | None = None
    status: Literal["OPEN", "CLOSED"]
    bars_held: int = 0
    gross_profit: float = 0.0
    commission: float = 0.0
    net_profit: float = 0.0
    return_pct: float = 0.0
    mfe_pct: float = 0.0
    mae_pct: float = 0.0
    balance_before: float
    balance_after: float | None = None
    risk_at_entry: float | None = None
    ath_zone: str | None = None


class TorumV1BacktestEquityPointRead(BaseModel):
    time: datetime
    balance: float
    equity: float
    drawdown: float
    drawdown_pct: float
    open_trades: int


class TorumV1BacktestDebugEventRead(BaseModel):
    time: datetime
    candle_index: int
    stage: str
    status: Literal["PASS", "REJECT", "ENTRY", "EXIT", "INFO", "WARN"]
    reason_code: str
    summary: str
    price: float | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class TorumV1BacktestMetricsRead(BaseModel):
    initial_balance: float
    final_balance: float
    final_equity: float
    net_profit: float
    total_return_pct: float
    gross_profit: float
    gross_loss: float
    total_commission: float
    total_trades: int
    closed_trades: int
    open_trades: int
    winning_trades: int
    losing_trades: int
    breakeven_trades: int
    win_rate_pct: float
    profit_factor: float | None = None
    payoff_ratio: float | None = None
    recovery_factor: float | None = None
    expectancy: float
    average_trade: float
    average_win: float
    average_loss: float
    best_trade: float
    worst_trade: float
    max_drawdown: float
    max_drawdown_pct: float
    max_consecutive_wins: int
    max_consecutive_losses: int
    average_bars_held: float
    exposure_pct: float
    max_concurrent_trades: int
    trading_days: int
    trades_per_day: float
    average_pullback_pct: float
    average_risk_at_entry: float
    average_mfe_pct: float
    average_mae_pct: float
    signals_detected: int
    blocked_signals: int
    rejection_counts: dict[str, int] = Field(default_factory=dict)
    support_breakdown: dict[str, dict[str, float | int]] = Field(default_factory=dict)
    zone_breakdown: dict[str, dict[str, float | int]] = Field(default_factory=dict)


class TorumV1BacktestRead(BaseModel):
    symbol: str
    timeframe: Literal["M5"] = "M5"
    generated_at: datetime
    from_time: datetime | None
    to_time: datetime | None
    candles_analyzed: int
    candles: list[TorumV1BacktestCandleRead]
    trades: list[TorumV1BacktestTradeRead]
    equity_curve: list[TorumV1BacktestEquityPointRead]
    operation_zones: list[TorumV1BacktestZoneRead]
    supports: list[TorumV1BacktestSupportRead]
    pullbacks: list[TorumV1BacktestPullbackRead]
    debug_events: list[TorumV1BacktestDebugEventRead]
    metrics: TorumV1BacktestMetricsRead
    configuration: dict[str, Any] = Field(default_factory=dict)
    coverage: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    config_revision: int | None = None
    elapsed_ms: float


class TorumV1BacktestJobRead(BaseModel):
    job_id: str
    status: Literal[
        "QUEUED",
        "RUNNING",
        "CANCELLING",
        "COMPLETED",
        "FAILED",
        "CANCELLED",
    ]
    progress: float = Field(ge=0.0, le=1.0)
    stage: str
    message: str
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: TorumV1BacktestRead | None = None
    error: str | None = None
