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
  pending: number;
  wins: number;
  losses: number;
}

export interface DailyTradePerformance {
  position_id: number;
  symbol: string;
  multiplier: 1 | 2 | 3;
  volume: number;
  side: string;
  opened_at: string;
  closed_at: string;
  open_price: number;
  close_price: number | null;
  net_profit: number | null;
  pending: boolean;
  duration_minutes: number | null;
}

export interface DailyPerformance {
  date: string;
  return_pct: number | null;
  net_profit: number;
  trades: number;
  pending: number;
  wins: number;
  losses: number;
  x1: number;
  x2: number;
  x3: number;
  xauusd: number;
  xaueur: number;
  trades_detail: DailyTradePerformance[];
}

export interface PerformanceBreakdown {
  key: string;
  label: string;
  trades: number;
  pending: number;
  wins: number;
  losses: number;
  win_rate_pct: number | null;
  net_profit: number;
  average_profit: number;
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
  profit_factor: number | null;
  expectancy: number | null;
  average_win: number | null;
  average_loss: number | null;
  best_trade: number | null;
  worst_trade: number | null;
  profitable_days: number;
  losing_days: number;
  best_day_pct: number | null;
  worst_day_pct: number | null;
  best_day_profit: number | null;
  worst_day_profit: number | null;
  max_win_streak: number;
  max_loss_streak: number;
  current_streak_type: "WIN" | "LOSS" | null;
  current_streak: number;
  best_month_key: string | null;
  best_month_return_pct: number | null;
  basis_source: string;
  basis_note: string;
  pending_trades: number;
  points: PerformancePoint[];
  days: DailyPerformance[];
  months: MonthlyPerformance[];
  multiplier_breakdown: PerformanceBreakdown[];
  symbol_breakdown: PerformanceBreakdown[];
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
