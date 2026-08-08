import { apiRequest } from "./apiClient";

export type CapitalMovementKind = "INITIAL" | "DEPOSIT" | "WITHDRAWAL" | "ADJUSTMENT";

export interface CapitalMovement {
  id: number;
  occurred_at: string;
  amount: number;
  kind: string;
  source: string;
  currency: string | null;
  account_login: number | null;
  account_server: string | null;
  note: string | null;
  external_id: number | null;
  deletable: boolean;
}

export interface PerformancePoint {
  time: string;
  return_pct: number;
  cumulative_profit: number;
  capital: number | null;
}

export interface MonthlyPerformance {
  key: string;
  label: string;
  from_time: string;
  to_time: string;
  return_pct: number | null;
  net_profit: number;
  cash_flow: number;
  trades: number;
  wins: number;
  losses: number;
}

export interface PerformanceSummary {
  from_time: string;
  to_time: string;
  currency: string;
  return_pct: number | null;
  net_profit: number;
  gross_profit: number;
  gross_loss: number;
  cash_flow: number;
  capital_start: number | null;
  capital_end: number | null;
  current_balance: number | null;
  reconciliation_difference: number | null;
  trades: number;
  wins: number;
  losses: number;
  win_rate_pct: number | null;
  max_drawdown_pct: number | null;
  best_month_key: string | null;
  best_month_return_pct: number | null;
  basis_source: string;
  basis_note: string;
  pending_trades: number;
  points: PerformancePoint[];
  months: MonthlyPerformance[];
  capital_movements: CapitalMovement[];
}

export interface CapitalMovementInput {
  kind: CapitalMovementKind;
  amount: number;
  occurred_at: string;
  note?: string | null;
}

export function getStrategyPerformance(from: string, to: string): Promise<PerformanceSummary> {
  const params = new URLSearchParams({ from, to });
  return apiRequest<PerformanceSummary>(`/api/performance?${params.toString()}`);
}

export function createCapitalMovement(payload: CapitalMovementInput): Promise<CapitalMovement> {
  return apiRequest<CapitalMovement>("/api/performance/capital-movements", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function deleteCapitalMovement(id: number): Promise<void> {
  return apiRequest<void>(`/api/performance/capital-movements/${id}`, { method: "DELETE" });
}
