import { getAuthToken } from "../stores/authStore";
import { resolveApiBaseUrl } from "./runtime";

const API_BASE_URL = resolveApiBaseUrl();

export type DollarStrengthState = "WEAK" | "STRONG" | "NEUTRAL" | "UNKNOWN";

export interface DollarStrengthSnapshot {
  id: number | null;
  symbol: "DXY";
  dxy_value: number | null;
  sma30: number | null;
  difference: number | null;
  state: DollarStrengthState;
  trading_allowed: boolean;
  reason: string;
  slope_days: number;
  slope_pct: number | null;
  strong_drop_override_active: boolean;
  source: string;
  updated_at: string | null;
  valid_until: string | null;
  missing_symbols: string[];
  symbols_used: string[];
  error_message: string | null;
  stale: boolean;
}

interface DollarStrengthRecomputeResponse {
  ok: boolean;
  snapshot: DollarStrengthSnapshot;
  message: string;
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

export function getDollarStrength(): Promise<DollarStrengthSnapshot> {
  return request<DollarStrengthSnapshot>("/api/market-context/dollar-strength");
}

export function recomputeDollarStrength(): Promise<DollarStrengthRecomputeResponse> {
  return request<DollarStrengthRecomputeResponse>("/api/market-context/dollar-strength/recompute", { method: "POST" });
}
