import { apiRequest } from "./apiClient";
import type { PositionRead } from "./trading";
import { getAuthToken } from "./authSession";
import { resolveWsBaseUrl } from "./runtime";

const WS_BASE_URL = resolveWsBaseUrl();
export type Timeframe = "M1" | "M5" | "H1" | "H2" | "H3" | "H4" | "D1" | "W1";

export interface SymbolMapping {
  id: number;
  internal_symbol: string;
  broker_symbol: string;
  display_name: string;
  enabled: boolean;
  asset_class: string;
  tradable: boolean;
  analysis_only: boolean;
  digits: number;
  point: number;
  contract_size: number;
  profit_currency?: string | null;
  risk_conversion_rate?: number;
}

export interface Candle {
  time: number;
  internal_symbol: string;
  timeframe: Timeframe;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number | null;
  tick_count: number | null;
  source: string;
  price_source: string;
}

export interface Tick {
  time: string;
  time_msc: number;
  internal_symbol: string;
  broker_symbol: string;
  bid: number | null;
  ask: number | null;
  last: number | null;
  volume: number | null;
  source: string;
}

export interface LatestTickDiagnostic extends Tick {
  symbol: string;
  time_msc: number;
  mid: number | null;
  spread: number | null;
  age_ms: number;
  created_at: string;
}

export interface MockMarketStatus {
  running: boolean;
  source: "MOCK";
  last_tick_time: string | null;
  interval_seconds: number;
  symbols: string[];
}

export interface MT5Account {
  login: number | null;
  server: string | null;
  name: string | null;
  company: string | null;
  currency: string | null;
  balance: number | null;
  equity: number | null;
  margin: number | null;
  margin_free: number | null;
  margin_level: number | null;
  margin_so_mode: number | null;
  margin_so_call: number | null;
  margin_so_so: number | null;
  leverage: number | null;
  trade_mode: "DEMO" | "REAL" | "UNKNOWN";
}

export interface MT5Status {
  connected_to_mt5: boolean;
  connected_to_backend: boolean;
  account_trade_mode: "DEMO" | "REAL" | "UNKNOWN";
  account: MT5Account | null;
  terminal_trade_allowed: boolean | null;
  terminal_tradeapi_disabled: boolean | null;
  active_symbols: string[];
  last_tick_time_by_symbol: Record<string, string>;
  ticks_sent_total: number;
  last_batch_sent_at: string | null;
  errors_count: number;
  message: string | null;
  updated_at: string | null;
}


export interface SavedMT5Account {
  id: number;
  alias: string;
  login: number;
  server: string;
  last_trade_mode: "DEMO" | "REAL" | "UNKNOWN" | null;
  last_company: string | null;
  last_currency: string | null;
  last_connected_at: string | null;
  active: boolean;
  created_at: string;
  updated_at: string;
}

export interface MT5DiscoveredAccount {
  login: number;
  server: string;
  active: boolean;
  already_saved: boolean;
  source: "CURRENT" | "TERMINAL_DATA";
}

export interface MT5AccountSwitchResult {
  ok: boolean;
  account: SavedMT5Account;
  mt5_status: MT5Status;
  message: string;
}

export type MarketMessage =
  | {
      type: "candle_update";
      symbol: string;
      timeframe: Timeframe;
      candle: Candle;
    }
  | {
      type: "market_status";
      connected: boolean;
      source: string;
      last_tick_time: string | null;
    }
  | {
      type: "latest_tick_update" | "market_tick";
      symbol: string;
      broker_symbol: string | null;
      time: string;
      time_msc: number | null;
      bid: number | null;
      ask: number | null;
      last: number | null;
      mid?: number | null;
      spread?: number | null;
      volume: number | null;
      source: string | null;
    }
  | {
      type: "pong";
      ts: number;
      server_time: string;
    }
  | {
      type: "price_alert_triggered";
      alert_id: string;
      symbol: string;
      target_price: number;
      triggered_price: number;
      triggered_at: string;
    }
  | {
      type: "price_alert_updated";
      alert_id: string;
      symbol: string;
    }
  | {
      type: "position_opened" | "position_closed" | "position_updated";
      position_id: number;
      symbol: string;
      position?: PositionRead;
      closed_at?: string | null;
      close_price?: number | null;
      profit?: number | null;
    };

export function getSymbols(): Promise<SymbolMapping[]> {
  return apiRequest<SymbolMapping[]>("/api/symbols");
}

export function getCandles(
  symbol: string,
  timeframe: Timeframe,
  limit = 500,
  options: { signal?: AbortSignal; after?: number; before?: number } = {}
): Promise<Candle[]> {
  const params = new URLSearchParams({ symbol, timeframe, limit: String(limit) });
  if (typeof options.after === "number" && Number.isFinite(options.after)) {
    params.set("after", String(Math.floor(options.after)));
  }
  if (typeof options.before === "number" && Number.isFinite(options.before)) {
    params.set("before", String(Math.floor(options.before)));
  }
  return apiRequest<Candle[]>(`/api/candles?${params.toString()}`, { signal: options.signal });
}

export function getTicks(symbol: string, limit = 1000): Promise<Tick[]> {
  const params = new URLSearchParams({ symbol, limit: String(limit) });
  return apiRequest<Tick[]>(`/api/ticks?${params.toString()}`);
}

export function getLatestTick(symbol: string): Promise<LatestTickDiagnostic> {
  const params = new URLSearchParams({ symbol });
  return apiRequest<LatestTickDiagnostic>(`/api/market/latest-tick?${params.toString()}`);
}

export function getMockMarketStatus(): Promise<MockMarketStatus> {
  return apiRequest<MockMarketStatus>("/api/mock-market/status");
}

export function getMt5Status(): Promise<MT5Status> {
  return apiRequest<MT5Status>("/api/mt5/status");
}


export function getSavedMt5Accounts(): Promise<SavedMT5Account[]> {
  return apiRequest<SavedMT5Account[]>("/api/mt5/accounts");
}

export function discoverMt5Accounts(): Promise<MT5DiscoveredAccount[]> {
  return apiRequest<MT5DiscoveredAccount[]>("/api/mt5/accounts/discover");
}

export function saveMt5Account(payload: { alias?: string | null; login: number; server: string }): Promise<SavedMT5Account> {
  return apiRequest<SavedMT5Account>("/api/mt5/accounts", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function renameSavedMt5Account(id: number, alias: string): Promise<SavedMT5Account> {
  return apiRequest<SavedMT5Account>(`/api/mt5/accounts/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ alias })
  });
}

export function deleteSavedMt5Account(id: number): Promise<void> {
  return apiRequest<void>(`/api/mt5/accounts/${id}`, { method: "DELETE" });
}

export function switchMt5Account(id: number): Promise<MT5AccountSwitchResult> {
  return apiRequest<MT5AccountSwitchResult>(`/api/mt5/accounts/${id}/switch`, { method: "POST" });
}

export function startMockMarket(): Promise<MockMarketStatus> {
  return apiRequest<MockMarketStatus>("/api/mock-market/start", { method: "POST" });
}

export function stopMockMarket(): Promise<MockMarketStatus> {
  return apiRequest<MockMarketStatus>("/api/mock-market/stop", { method: "POST" });
}

export function marketWebSocketUrl(symbol: string, timeframe: Timeframe): string {
  const token = getAuthToken();
  const suffix = token ? `?token=${encodeURIComponent(token)}` : "";
  return `${WS_BASE_URL}/ws/market/${encodeURIComponent(symbol)}/${encodeURIComponent(timeframe)}${suffix}`;
}

export function createMarketWebSocket(symbol: string, timeframe: Timeframe): WebSocket {
  return new WebSocket(marketWebSocketUrl(symbol, timeframe));
}
