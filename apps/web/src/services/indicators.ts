import type { NoTradeZone } from "./news";
import type { ChartDrawingRead } from "./drawings";
import { getAuthToken } from "../stores/authStore";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export interface IndicatorPoint {
  time: number;
  value: number;
}

export interface IndicatorLineOutput {
  type: "line";
  name: string;
  symbol: string;
  timeframe: string;
  points: IndicatorPoint[];
  style: {
    color?: string;
    lineWidth?: number;
  };
}

export type IndicatorOutput = IndicatorLineOutput | Record<string, unknown>;

export interface IndicatorRead {
  id: number;
  name: string;
  plugin_key: string;
  version: string;
  description: string;
  output_type: string;
  enabled: boolean;
  default_params_json: Record<string, unknown>;
}

export interface IndicatorConfigRead {
  id: number;
  user_id: number | null;
  indicator_id: number;
  internal_symbol: string;
  timeframe: string;
  enabled: boolean;
  params_json: Record<string, unknown>;
  display_settings_json: Record<string, unknown>;
}

export interface ChartOverlays {
  symbol: string;
  timeframe: string;
  indicators: IndicatorOutput[];
  no_trade_zones: NoTradeZone[];
  drawings: ChartDrawingRead[];
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
  return (await response.json()) as T;
}

export function getIndicators(): Promise<IndicatorRead[]> {
  return request<IndicatorRead[]>("/api/indicators");
}

export function registerDefaultIndicators(): Promise<IndicatorRead[]> {
  return request<IndicatorRead[]>("/api/indicators/register-defaults", { method: "POST" });
}

export function getIndicatorConfigs(symbol: string, timeframe: string): Promise<IndicatorConfigRead[]> {
  const params = new URLSearchParams({ symbol, timeframe });
  return request<IndicatorConfigRead[]>(`/api/indicator-configs?${params.toString()}`);
}

export function patchIndicatorConfig(id: number, payload: Partial<IndicatorConfigRead>): Promise<IndicatorConfigRead> {
  return request<IndicatorConfigRead>(`/api/indicator-configs/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

export function getChartOverlays(symbol: string, timeframe: string, from: string, to: string): Promise<ChartOverlays> {
  const params = new URLSearchParams({ symbol, timeframe, from, to });
  return request<ChartOverlays>(`/api/chart/overlays?${params.toString()}`);
}

export function isLineOutput(output: IndicatorOutput): output is IndicatorLineOutput {
  return output.type === "line" && Array.isArray((output as IndicatorLineOutput).points);
}
