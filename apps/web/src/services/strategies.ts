import type { TradingMode } from "./trading";
import { apiRequest } from "./apiClient";

export interface StrategyDefinition {
  id: number;
  key: string;
  name: string;
  version: string;
  description: string;
  enabled: boolean;
  default_params_json: Record<string, unknown>;
}

export interface StrategyConfig {
  id: number;
  user_id: number | null;
  strategy_key: string;
  internal_symbol: string;
  timeframe: string;
  enabled: boolean;
  mode: TradingMode;
  params_json: Record<string, unknown>;
  risk_profile_json: Record<string, unknown> | null;
  schedule_json: Record<string, unknown> | null;
  revision: number;
  created_at?: string;
  updated_at?: string;
}

export interface StrategySettings {
  id: number;
  user_id: number | null;
  strategies_enabled: boolean;
  strategy_live_enabled: boolean;
  default_mode: TradingMode;
  max_signals_per_run: number | null;
}

export interface StrategySignal {
  id: number;
  strategy_config_id: number | null;
  strategy_key: string;
  internal_symbol: string;
  timeframe: string;
  signal_type: "ENTRY" | "EXIT" | "MODIFY" | "NONE";
  side: "BUY" | "SELL" | "NONE";
  status: string;
  reason: string;
  order_id: number | null;
  created_at: string;
}

export interface StrategyRun {
  id: number;
  strategy_config_id: number | null;
  strategy_key: string;
  started_at: string;
  finished_at: string | null;
  status: "STARTED" | "FINISHED" | "FAILED";
  candles_used: number;
  error_message: string | null;
}

export interface StrategyRunResult {
  ok: boolean;
  run: StrategyRun;
  signal: StrategySignal | null;
  message: string;
  order_id: number | null;
  reasons: string[];
  warnings: string[];
}

export interface TorumV1AssetStatus {
  symbol: string;
  enabled: boolean;
  status: "LOCKED" | "UNLOCKED";
  reason: string;
  timeframe: string;
  session_start: string;
  session_end: string;
  unlocked_at: string | null;
  blocked_by_news: boolean;
  active_config_id: number | null;
  manual_override: "LOCKED" | "UNLOCKED" | null;
}

export interface TorumV1Status {
  strategy_key: "torum_v1";
  enabled: boolean;
  use_news: boolean;
  server_time: string;
  madrid_time: string;
  assets: Record<string, TorumV1AssetStatus>;
}

export interface TorumFieldDescriptor {
  key: string;
  label: string;
  group: string;
  type: "boolean" | "number" | "select" | "time" | "multiselect" | "text";
  description: string;
  unit: string | null;
  minimum: number | null;
  maximum: number | null;
  step: number | null;
  options: Array<{ value: string; label: string }>;
  advanced: boolean;
  per_symbol: boolean;
}

export interface TorumGroupDescriptor {
  key: string;
  label: string;
  description: string;
  order: number;
}

export interface TorumConfigurationSchema {
  groups: TorumGroupDescriptor[];
  fields: TorumFieldDescriptor[];
  defaults: Record<string, Record<string, unknown>>;
}

export interface TorumV1Configuration {
  strategy_key: "torum_v1";
  base_params: Record<string, unknown>;
  asset_overrides: Record<string, Record<string, unknown>>;
  configs: Record<string, StrategyConfig>;
  enabled_by_symbol: Record<string, boolean>;
  mode_by_symbol: Record<string, TradingMode>;
  schema: TorumConfigurationSchema;
  common_revision: number;
}

export interface StrategyTraceStep {
  id: string;
  label: string;
  status: "PASS" | "FAIL" | "WAIT" | "SKIP" | "WARN";
  summary: string;
  actual: unknown;
  required: unknown;
  details: Record<string, unknown>;
}

export interface TorumV1Simulation {
  symbol: string;
  evaluated_at: string;
  decision: "BUY" | "WAIT" | "BLOCKED" | "ERROR";
  reason_code: string;
  summary: string;
  current_price: number | null;
  steps: StrategyTraceStep[];
  metadata: Record<string, unknown>;
  config_revision: number | null;
}


export interface TorumV1ReplaySignal {
  confirmation_time: string;
  price: number;
  pullback_pct: number | null;
  pullback_low: number | null;
  pullback_low_time: string | null;
  operation_zone_id: number | string | null;
  support_level: number | null;
  desired_multiplier: number;
  reason: string;
}

export interface TorumV1Replay {
  symbol: string;
  generated_at: string;
  from_time: string | null;
  to_time: string | null;
  candles_analyzed: number;
  signals: TorumV1ReplaySignal[];
  signal_count: number;
  coverage: Record<string, string>;
  notes: string[];
  config_revision: number | null;
}


export type TorumBacktestDebugLevel = "SUMMARY" | "SIGNALS" | "FULL";
export type TorumBacktestEntryModel = "CONFIRMATION_CLOSE" | "NEXT_OPEN";

export interface TorumV1BacktestRequest {
  symbol: string;
  params?: Record<string, unknown>;
  candle_limit: number;
  from_time?: string | null;
  to_time?: string | null;
  initial_balance: number;
  use_session: boolean;
  use_unlock: boolean;
  use_news: boolean;
  use_dxy: boolean;
  use_operation_zones: boolean;
  use_supports: boolean;
  use_ath_capacity: boolean;
  use_risk: boolean;
  selected_operation_zone_ids: string[];
  selected_support_zone_ids: string[];
  entry_model: TorumBacktestEntryModel;
  spread_points: number;
  slippage_points: number;
  commission_per_lot: number;
  close_open_trades_at_end: boolean;
  debug_level: TorumBacktestDebugLevel;
  max_debug_events: number;
}

export interface TorumV1BacktestCandle {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number | null;
}

export interface TorumV1BacktestZone {
  id: string;
  name: string | null;
  direction: string;
  time1: string;
  time2: string | null;
  price_min: number;
  price_max: number;
  selected: boolean;
}

export interface TorumV1BacktestSupport {
  id: string;
  name: string | null;
  level: number;
  price: number;
  lower_price: number;
  upper_price: number;
  enabled: boolean;
  selected: boolean;
}

export interface TorumV1BacktestPullback {
  swing_high_time: string;
  swing_high: number;
  pullback_low_time: string;
  pullback_low: number;
  pullback_pct: number;
  is_live: boolean;
}

export interface TorumV1BacktestTrade {
  id: string;
  entry_time: string;
  entry_price: number;
  exit_time: string | null;
  exit_price: number | null;
  tp_price: number;
  volume: number;
  multiplier: number;
  support_level: number | null;
  support_zone_id: string | null;
  operation_zone_id: string | null;
  pullback_pct: number | null;
  pullback_low: number | null;
  pullback_low_time: string | null;
  exit_reason: string | null;
  status: "OPEN" | "CLOSED";
  bars_held: number;
  gross_profit: number;
  commission: number;
  net_profit: number;
  return_pct: number;
  mfe_pct: number;
  mae_pct: number;
  balance_before: number;
  balance_after: number | null;
  risk_at_entry: number | null;
  ath_zone: string | null;
}

export interface TorumV1BacktestEquityPoint {
  time: string;
  balance: number;
  equity: number;
  drawdown: number;
  drawdown_pct: number;
  open_trades: number;
}

export interface TorumV1BacktestDebugEvent {
  time: string;
  candle_index: number;
  stage: string;
  status: "PASS" | "REJECT" | "ENTRY" | "EXIT" | "INFO" | "WARN";
  reason_code: string;
  summary: string;
  price: number | null;
  details: Record<string, unknown>;
}

export interface TorumV1BacktestMetrics {
  initial_balance: number;
  final_balance: number;
  final_equity: number;
  net_profit: number;
  total_return_pct: number;
  gross_profit: number;
  gross_loss: number;
  total_commission: number;
  total_trades: number;
  closed_trades: number;
  open_trades: number;
  winning_trades: number;
  losing_trades: number;
  breakeven_trades: number;
  win_rate_pct: number;
  profit_factor: number | null;
  payoff_ratio: number | null;
  recovery_factor: number | null;
  expectancy: number;
  average_trade: number;
  average_win: number;
  average_loss: number;
  best_trade: number;
  worst_trade: number;
  max_drawdown: number;
  max_drawdown_pct: number;
  max_consecutive_wins: number;
  max_consecutive_losses: number;
  average_bars_held: number;
  exposure_pct: number;
  max_concurrent_trades: number;
  trading_days: number;
  trades_per_day: number;
  average_pullback_pct: number;
  average_risk_at_entry: number;
  average_mfe_pct: number;
  average_mae_pct: number;
  signals_detected: number;
  blocked_signals: number;
  rejection_counts: Record<string, number>;
  support_breakdown: Record<string, { trades: number; wins: number; net_profit: number }>;
  zone_breakdown: Record<string, { trades: number; wins: number; net_profit: number }>;
}

export interface TorumV1Backtest {
  symbol: string;
  timeframe: "M5";
  generated_at: string;
  from_time: string | null;
  to_time: string | null;
  candles_analyzed: number;
  candles: TorumV1BacktestCandle[];
  trades: TorumV1BacktestTrade[];
  equity_curve: TorumV1BacktestEquityPoint[];
  operation_zones: TorumV1BacktestZone[];
  supports: TorumV1BacktestSupport[];
  pullbacks: TorumV1BacktestPullback[];
  debug_events: TorumV1BacktestDebugEvent[];
  metrics: TorumV1BacktestMetrics;
  configuration: Record<string, unknown>;
  coverage: Record<string, string>;
  warnings: string[];
  config_revision: number | null;
  elapsed_ms: number;
}

export type TorumV1BacktestJobStatus = "QUEUED" | "RUNNING" | "CANCELLING" | "COMPLETED" | "FAILED" | "CANCELLED";

export interface TorumV1BacktestJob {
  job_id: string;
  status: TorumV1BacktestJobStatus;
  progress: number;
  stage: string;
  message: string;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  result: TorumV1Backtest | null;
  error: string | null;
}

export interface StrategyConfigVersion {
  id: number;
  strategy_config_id: number;
  user_id: number | null;
  revision: number;
  enabled: boolean;
  mode: TradingMode;
  timeframe: string;
  params_json: Record<string, unknown>;
  risk_profile_json: Record<string, unknown> | null;
  schedule_json: Record<string, unknown> | null;
  change_note: string | null;
  created_at: string;
}

export function getStrategies(): Promise<StrategyDefinition[]> {
  return apiRequest<StrategyDefinition[]>("/api/strategies");
}
export function registerDefaultStrategies(): Promise<StrategyDefinition[]> {
  return apiRequest<StrategyDefinition[]>("/api/strategies/register-defaults", { method: "POST" });
}
export function getStrategyConfigs(): Promise<StrategyConfig[]> {
  return apiRequest<StrategyConfig[]>("/api/strategy-configs");
}
export function createStrategyConfig(payload: Partial<StrategyConfig>): Promise<StrategyConfig> {
  return apiRequest<StrategyConfig>("/api/strategy-configs", { method: "POST", body: JSON.stringify(payload) });
}
export function patchStrategyConfig(id: number, payload: Partial<StrategyConfig> & { expected_revision?: number; change_note?: string }): Promise<StrategyConfig> {
  return apiRequest<StrategyConfig>(`/api/strategy-configs/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
}
export function getStrategySettings(): Promise<StrategySettings> {
  return apiRequest<StrategySettings>("/api/strategy-settings");
}
export function patchStrategySettings(payload: Partial<StrategySettings>): Promise<StrategySettings> {
  return apiRequest<StrategySettings>("/api/strategy-settings", { method: "PATCH", body: JSON.stringify(payload) });
}
export function runStrategyConfig(id: number): Promise<StrategyRunResult> {
  return apiRequest<StrategyRunResult>(`/api/strategies/run/${id}`, { method: "POST" });
}
export function getStrategySignals(): Promise<StrategySignal[]> {
  return apiRequest<StrategySignal[]>("/api/strategy-signals?limit=20");
}
export function getStrategyRuns(): Promise<StrategyRun[]> {
  return apiRequest<StrategyRun[]>("/api/strategy-runs?limit=20");
}
export function getTorumV1Status(): Promise<TorumV1Status> {
  return apiRequest<TorumV1Status>("/api/strategies/torum-v1/status");
}

export type TorumV1ManualControlAction = "AUTO" | "UNLOCKED" | "LOCKED";

export function setTorumV1ManualLockState(
  symbol: "XAUUSD" | "XAUEUR",
  action: TorumV1ManualControlAction
): Promise<TorumV1Status> {
  const unlocked = action === "AUTO" ? null : action === "UNLOCKED";
  return apiRequest<TorumV1Status>("/api/strategies/torum-v1/manual-lock-state", {
    method: "POST",
    body: JSON.stringify({ symbol, unlocked })
  });
}
export function getTorumV1Configuration(): Promise<TorumV1Configuration> {
  return apiRequest<TorumV1Configuration>("/api/strategies/torum-v1/configuration");
}
export function patchTorumV1Configuration(payload: {
  base_params: Record<string, unknown>;
  asset_overrides: Record<string, Record<string, unknown>>;
  enabled_by_symbol: Record<string, boolean>;
  mode_by_symbol: Record<string, TradingMode>;
  expected_revisions: Record<string, number>;
  change_note?: string;
}): Promise<TorumV1Configuration> {
  return apiRequest<TorumV1Configuration>("/api/strategies/torum-v1/configuration", {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}
export function simulateTorumV1(symbol: string, params?: Record<string, unknown>, signal?: AbortSignal): Promise<TorumV1Simulation> {
  return apiRequest<TorumV1Simulation>("/api/strategies/torum-v1/simulate", {
    method: "POST",
    body: JSON.stringify({ symbol, params, candle_limit: 600 }),
    signal,
    timeoutMs: 30_000,
  });
}

export function replayTorumV1(symbol: string, params?: Record<string, unknown>, candleLimit = 500, signal?: AbortSignal): Promise<TorumV1Replay> {
  return apiRequest<TorumV1Replay>("/api/strategies/torum-v1/simulate/history", {
    method: "POST",
    body: JSON.stringify({ symbol, params, candle_limit: candleLimit }),
    signal,
    timeoutMs: 60_000,
  });
}

export function backtestTorumV1(payload: TorumV1BacktestRequest, signal?: AbortSignal): Promise<TorumV1Backtest> {
  return apiRequest<TorumV1Backtest>("/api/strategies/torum-v1/backtest", {
    method: "POST",
    body: JSON.stringify(payload),
    signal,
    timeoutMs: 120_000,
  });
}

export function startTorumV1BacktestJob(payload: TorumV1BacktestRequest, signal?: AbortSignal): Promise<TorumV1BacktestJob> {
  return apiRequest<TorumV1BacktestJob>("/api/strategies/torum-v1/backtest/jobs", {
    method: "POST",
    body: JSON.stringify(payload),
    signal,
    timeoutMs: 30_000,
  });
}

export function getTorumV1BacktestJob(jobId: string, includeResult = true, signal?: AbortSignal): Promise<TorumV1BacktestJob> {
  return apiRequest<TorumV1BacktestJob>(`/api/strategies/torum-v1/backtest/jobs/${encodeURIComponent(jobId)}?include_result=${includeResult ? "true" : "false"}`, {
    signal,
    timeoutMs: 30_000,
  });
}

export function cancelTorumV1BacktestJob(jobId: string): Promise<TorumV1BacktestJob> {
  return apiRequest<TorumV1BacktestJob>(`/api/strategies/torum-v1/backtest/jobs/${encodeURIComponent(jobId)}`, {
    method: "DELETE",
    timeoutMs: 30_000,
  });
}

export function getStrategyConfigVersions(configId: number): Promise<StrategyConfigVersion[]> {
  return apiRequest<StrategyConfigVersion[]>(`/api/strategy-configs/${configId}/versions?limit=50`);
}
export function restoreStrategyConfigVersion(configId: number, revision: number): Promise<StrategyConfig> {
  return apiRequest<StrategyConfig>(`/api/strategy-configs/${configId}/versions/${revision}/restore`, { method: "POST" });
}
