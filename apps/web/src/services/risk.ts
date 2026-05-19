import { getAuthToken } from "../stores/authStore";
import { resolveApiBaseUrl } from "./runtime";

const API_BASE_URL = resolveApiBaseUrl();

export interface RiskPositionExposure {
  position_id: number;
  internal_symbol: string;
  side: string;
  volume: number;
  open_price: number;
  loss_at_stress: number;
}

export interface RiskSnapshot {
  symbol: string;
  mode: string;
  source: string;
  ath_price: number | null;
  stress_price: number | null;
  balance: number | null;
  contract_size: number;
  current_loss: number | null;
  risk_limit: number | null;
  remaining_risk: number | null;
  positions_count: number;
  positions: RiskPositionExposure[];
  updated_at: string | null;
  valid: boolean;
  dirty: boolean;
  message: string | null;
}

export interface RiskCandidateProjection {
  candidate_loss: number | null;
  projected_loss: number | null;
  projected_balance: number | null;
  projected_balance_pct: number | null;
  breaches_limit: boolean;
}

interface RequestOptions extends RequestInit {
  token?: string | null;
}

const riskSnapshotCache = new Map<string, RiskSnapshot>();

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

export function readCachedRiskSnapshot(symbol: string): RiskSnapshot | null {
  return riskSnapshotCache.get(symbol.toUpperCase()) ?? null;
}

export async function getRiskSnapshot(symbol: string): Promise<RiskSnapshot> {
  const normalizedSymbol = symbol.toUpperCase();
  const params = new URLSearchParams({ symbol: normalizedSymbol });
  const snapshot = await request<RiskSnapshot>(`/api/risk/snapshot?${params.toString()}`);
  riskSnapshotCache.set(normalizedSymbol, snapshot);
  return snapshot;
}

export async function recomputeRiskSnapshot(symbol: string): Promise<RiskSnapshot> {
  const normalizedSymbol = symbol.toUpperCase();
  const params = new URLSearchParams({ symbol: normalizedSymbol });
  const snapshot = await request<RiskSnapshot>(`/api/risk/recompute?${params.toString()}`, { method: "POST" });
  riskSnapshotCache.set(normalizedSymbol, snapshot);
  return snapshot;
}

export function projectRiskCandidate(snapshot: RiskSnapshot | null, volume: number | null, price: number | null | undefined): RiskCandidateProjection | null {
  if (
    snapshot === null ||
    !snapshot.valid ||
    snapshot.current_loss === null ||
    snapshot.balance === null ||
    snapshot.stress_price === null ||
    snapshot.risk_limit === null ||
    volume === null ||
    !Number.isFinite(volume) ||
    volume <= 0 ||
    typeof price !== "number" ||
    !Number.isFinite(price) ||
    price <= 0
  ) {
    return null;
  }
  const candidateLoss = Math.max(0, price - snapshot.stress_price) * volume * snapshot.contract_size;
  const projectedLoss = snapshot.current_loss + candidateLoss;
  return {
    candidate_loss: roundMoney(candidateLoss),
    projected_loss: roundMoney(projectedLoss),
    projected_balance: roundMoney(snapshot.balance - projectedLoss),
    projected_balance_pct: roundMoney((projectedLoss / snapshot.balance) * 100),
    breaches_limit: projectedLoss > snapshot.risk_limit
  };
}

function roundMoney(value: number): number {
  return Math.round(value * 100) / 100;
}
