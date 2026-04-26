import type { TradingMode } from "./trading";
import { getAuthToken } from "../stores/authStore";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ||
  (window.location.protocol === "https:"
    ? window.location.origin
    : "http://localhost:8000");

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

interface RequestOptions extends RequestInit {
  token?: string | null;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");
  const token = options.token ?? getAuthToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(`${API_BASE_URL}${path}`, { ...options, headers });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail ?? `HTTP ${response.status}`);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export function getStrategies(): Promise<StrategyDefinition[]> {
  return request<StrategyDefinition[]>("/api/strategies");
}

export function registerDefaultStrategies(): Promise<StrategyDefinition[]> {
  return request<StrategyDefinition[]>("/api/strategies/register-defaults", { method: "POST" });
}

export function getStrategyConfigs(): Promise<StrategyConfig[]> {
  return request<StrategyConfig[]>("/api/strategy-configs");
}

export function createStrategyConfig(payload: Partial<StrategyConfig>): Promise<StrategyConfig> {
  return request<StrategyConfig>("/api/strategy-configs", { method: "POST", body: JSON.stringify(payload) });
}

export function patchStrategyConfig(id: number, payload: Partial<StrategyConfig>): Promise<StrategyConfig> {
  return request<StrategyConfig>(`/api/strategy-configs/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
}

export function getStrategySettings(): Promise<StrategySettings> {
  return request<StrategySettings>("/api/strategy-settings");
}

export function patchStrategySettings(payload: Partial<StrategySettings>): Promise<StrategySettings> {
  return request<StrategySettings>("/api/strategy-settings", { method: "PATCH", body: JSON.stringify(payload) });
}

export function runStrategyConfig(id: number): Promise<StrategyRunResult> {
  return request<StrategyRunResult>(`/api/strategies/run/${id}`, { method: "POST" });
}

export function getStrategySignals(): Promise<StrategySignal[]> {
  return request<StrategySignal[]>("/api/strategy-signals?limit=20");
}

export function getStrategyRuns(): Promise<StrategyRun[]> {
  return request<StrategyRun[]>("/api/strategy-runs?limit=20");
}
