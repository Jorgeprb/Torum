import { getAuthToken } from "../stores/authStore";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ||
  (window.location.protocol === "https:"
    ? window.location.origin
    : "http://localhost:8000");

export type TradingMode = "PAPER" | "DEMO" | "LIVE";
export type OrderSide = "BUY" | "SELL";
export type OrderStatus = "CREATED" | "VALIDATING" | "REJECTED" | "SENT" | "EXECUTED" | "FAILED" | "CANCELLED" | "CLOSED";

export interface TradingSettings {
  id: number;
  user_id: number | null;
  trading_mode: TradingMode;
  live_trading_enabled: boolean;
  require_live_confirmation: boolean;
  default_volume: number;
  default_magic_number: number;
  default_deviation_points: number;
  max_order_volume: number | null;
  allow_market_orders: boolean;
  allow_pending_orders: boolean;
  is_paused: boolean;
  long_only: boolean;
  default_take_profit_percent: number;
  use_stop_loss: boolean;
  lot_per_equity_enabled: boolean;
  equity_per_0_01_lot: number;
  minimum_lot: number;
  allow_manual_lot_adjustment: boolean;
  show_bid_line: boolean;
  show_ask_line: boolean;
  mt5_order_execution_enabled: boolean;
  market_data_source: "MT5" | "MOCK";
}

export interface MT5OrderExecutionSettings {
  torum_enabled: boolean;
  bridge_configured: boolean;
  bridge_connected: boolean;
  bridge_enabled: boolean | null;
  bridge_message: string | null;
}

export interface ManualOrderPayload {
  internal_symbol: string;
  side: OrderSide;
  order_type: "MARKET";
  volume: number;
  sl?: number | null;
  tp?: number | null;
  tp_percent?: number | null;
  comment?: string | null;
  client_confirmation?: {
    confirmed: boolean;
    mode_acknowledged: TradingMode;
    live_text?: string | null;
    no_stop_loss_acknowledged?: boolean;
  };
}

export interface ManualOrderResponse {
  ok: boolean;
  order_id: number;
  status: OrderStatus;
  mode: TradingMode;
  message: string;
  warnings: string[];
  reasons: string[];
}

export interface OrderRead {
  id: number;
  internal_symbol: string;
  broker_symbol: string;
  mode: TradingMode;
  side: OrderSide;
  order_type: "MARKET";
  volume: number;
  requested_price: number | null;
  executed_price: number | null;
  sl: number | null;
  tp: number | null;
  status: OrderStatus;
  rejection_reason: string | null;
  created_at: string;
  executed_at: string | null;
}

export interface PositionRead {
  id: number;
  order_id: number | null;
  internal_symbol: string;
  broker_symbol: string;
  mode: TradingMode;
  side: OrderSide;
  volume: number;
  open_price: number;
  current_price: number | null;
  close_price: number | null;
  sl: number | null;
  tp: number | null;
  profit: number | null;
  swap: number | null;
  commission: number | null;
  status: "OPEN" | "CLOSED";
  mt5_position_ticket: number | null;
  closing_deal_ticket: number | null;
  opened_at: string;
  closed_at: string | null;
  tp_percent: number | null;
}

export interface TradeHistoryItem {
  id: number;
  position_id: number;
  order_id: number | null;
  opened_at: string;
  closed_at: string | null;
  internal_symbol: string;
  broker_symbol: string;
  side: OrderSide;
  volume: number;
  open_price: number;
  close_price: number | null;
  tp: number | null;
  profit: number | null;
  swap: number | null;
  commission: number | null;
  mode: TradingMode;
  mt5_position_ticket: number | null;
  closing_deal_ticket: number | null;
  status: "OPEN" | "CLOSED";
}

export interface LotSizeResponse {
  available_equity: number | null;
  equity_per_0_01_lot: number;
  base_lot: number;
  multiplier: number;
  effective_lot: number;
  min_lot: number;
  lot_step: number;
  source: string;
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

export function getTradingSettings(): Promise<TradingSettings> {
  return request<TradingSettings>("/api/trading/settings");
}

export function patchTradingSettings(payload: Partial<TradingSettings>): Promise<TradingSettings> {
  return request<TradingSettings>("/api/trading/settings", {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

export function getMT5OrderExecutionSettings(): Promise<MT5OrderExecutionSettings> {
  return request<MT5OrderExecutionSettings>("/api/trading/mt5-order-execution");
}

export function getLotSize(symbol: string, multiplier = 1): Promise<LotSizeResponse> {
  const params = new URLSearchParams({ symbol, multiplier: String(multiplier) });
  return request<LotSizeResponse>(`/api/trading/lot-size?${params.toString()}`);
}

export function submitManualOrder(payload: ManualOrderPayload): Promise<ManualOrderResponse> {
  return request<ManualOrderResponse>("/api/orders/manual", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function getOrders(): Promise<OrderRead[]> {
  return request<OrderRead[]>("/api/orders?limit=50");
}

export function getPositions(): Promise<PositionRead[]> {
  return request<PositionRead[]>("/api/positions?limit=50");
}

export function closePosition(id: number): Promise<PositionRead> {
  return request<PositionRead>(`/api/positions/${id}/close`, {
    method: "POST",
    body: JSON.stringify({ client_confirmation: { confirmed: true } })
  });
}

export function modifyPositionTp(id: number, tp: number): Promise<PositionRead> {
  return request<PositionRead>(`/api/positions/${id}/tp`, {
    method: "PATCH",
    body: JSON.stringify({ tp })
  });
}

export function getTradeHistory(params: { symbol?: string; status?: "OPEN" | "CLOSED"; mode?: TradingMode } = {}): Promise<TradeHistoryItem[]> {
  const query = new URLSearchParams();
  if (params.symbol) query.set("symbol", params.symbol);
  if (params.status) query.set("status", params.status);
  if (params.mode) query.set("mode", params.mode);
  query.set("limit", "300");
  return request<TradeHistoryItem[]>(`/api/trade-history?${query.toString()}`);
}
