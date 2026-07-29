import { apiRequest } from "./apiClient";


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

export function getDollarStrength(): Promise<DollarStrengthSnapshot> {
  return apiRequest<DollarStrengthSnapshot>("/api/market-context/dollar-strength");
}

export function recomputeDollarStrength(): Promise<DollarStrengthRecomputeResponse> {
  return apiRequest<DollarStrengthRecomputeResponse>("/api/market-context/dollar-strength/recompute", { method: "POST" });
}
