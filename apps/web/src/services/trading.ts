import { apiRequest } from "./apiClient";


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
    risk_acknowledged?: boolean;
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
  position: PositionRead | null;
  order: (OrderRead & {
    mt5_position_ticket?: number | null;
    source?: string;
    strategy_key?: string | null;
    strategy_signal_id?: number | null;
  }) | null;
  executed_price: number | null;
  final_tp: number | null;
  tp_status: "NONE" | "PENDING" | "UPDATED" | "FAILED";
  mt5_position_ticket: number | null;
  meta: Record<string, unknown>;
}

export interface RiskPreviewResponse {
  balance: number | null;
  potential_loss: number | null;
  projected_balance: number | null;
  breaches_bot_limit: boolean;
  positions_count: number;
  message: string | null;
}

export interface AthLevel {
  internal_symbol: string;
  ath_price: number | null;
  mode: "auto" | "manual";
  source: string;
  calculated_at: string | null;
  updated_at: string | null;
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
  account_login?: number | null;
  account_server?: string | null;
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
  fee?: number | null;
  status: "OPEN" | "CLOSED";
  mt5_position_ticket: number | null;
  mt5_position_identifier?: number | null;
  closing_deal_ticket: number | null;
  opened_at: string;
  closed_at: string | null;
  open_time_msc?: number | null;
  close_time_msc?: number | null;
  enrichment_status?: string;
  net_profit?: number | null;
  tp_percent: number | null;
}

export interface TradeHistoryItem {
  id: number;
  position_id: number;
  order_id: number | null;
  account_login?: number | null;
  account_server?: string | null;
  opened_at: string;
  closed_at: string | null;
  open_time_msc?: number | null;
  close_time_msc?: number | null;
  enrichment_status?: string;
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
  fee?: number | null;
  net_profit?: number | null;
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

export function getTradingSettings(): Promise<TradingSettings> {
  return apiRequest<TradingSettings>("/api/trading/settings");
}

export function patchTradingSettings(payload: Partial<TradingSettings>): Promise<TradingSettings> {
  return apiRequest<TradingSettings>("/api/trading/settings", {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

export function getMT5OrderExecutionSettings(): Promise<MT5OrderExecutionSettings> {
  return apiRequest<MT5OrderExecutionSettings>("/api/trading/mt5-order-execution");
}

export function getLotSize(symbol: string, multiplier = 1): Promise<LotSizeResponse> {
  const params = new URLSearchParams({ symbol, multiplier: String(multiplier) });
  return apiRequest<LotSizeResponse>(`/api/trading/lot-size?${params.toString()}`);
}

export function submitManualOrder(payload: ManualOrderPayload): Promise<ManualOrderResponse> {
  return apiRequest<ManualOrderResponse>("/api/orders/manual", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function getManualRiskPreview(payload: { internal_symbol: string; side: OrderSide; volume: number; price?: number | null }): Promise<RiskPreviewResponse> {
  return apiRequest<RiskPreviewResponse>("/api/trading/risk-preview", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function getAthLevels(): Promise<AthLevel[]> {
  return apiRequest<AthLevel[]>("/api/trading/ath-levels");
}

export function patchAthLevel(symbol: string, payload: { mode: AthLevel["mode"]; ath_price?: number | null }): Promise<AthLevel> {
  return apiRequest<AthLevel>(`/api/trading/ath-levels/${symbol}`, {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

export function getOrders(): Promise<OrderRead[]> {
  return apiRequest<OrderRead[]>("/api/orders?limit=50");
}

export function getPositions(params: { status?: "OPEN" | "CLOSED"; symbol?: string; limit?: number } = {}): Promise<PositionRead[]> {
  const query = new URLSearchParams();

  query.set("limit", String(params.limit ?? 100));

  if (params.status) {
    query.set("status", params.status);
  }

  if (params.symbol) {
    query.set("symbol", params.symbol);
  }

  return apiRequest<PositionRead[]>(`/api/positions?${query.toString()}`);
}

export function closePosition(id: number): Promise<PositionRead> {
  return apiRequest<PositionRead>(`/api/positions/${id}/close`, {
    method: "POST",
    body: JSON.stringify({ client_confirmation: { confirmed: true }, fetch_close_deal: false })
  });
}

export function modifyPositionTp(id: number, tp: number): Promise<PositionRead> {
  return apiRequest<PositionRead>(`/api/positions/${id}/tp`, {
    method: "PATCH",
    body: JSON.stringify({ tp })
  });
}

export function getTradeHistory(params: {
  symbol?: string;
  status?: "OPEN" | "CLOSED";
  mode?: TradingMode;
  accountLogin?: number | null;
  accountServer?: string | null;
} = {}): Promise<TradeHistoryItem[]> {
  const query = new URLSearchParams();
  if (params.symbol) query.set("symbol", params.symbol);
  if (params.status) query.set("status", params.status);
  if (params.mode) query.set("mode", params.mode);
  if (typeof params.accountLogin === "number") query.set("account_login", String(params.accountLogin));
  if (params.accountServer) query.set("account_server", params.accountServer);
  query.set("limit", "300");
  return apiRequest<TradeHistoryItem[]>(`/api/trade-history?${query.toString()}`);
}
