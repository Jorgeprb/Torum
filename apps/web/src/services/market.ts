import { getAuthToken } from "../stores/authStore";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ||
  (window.location.protocol === "https:"
    ? window.location.origin
    : "http://localhost:8000");
const WS_BASE_URL =
  import.meta.env.VITE_WS_BASE_URL ||
  (window.location.protocol === "https:"
    ? window.location.origin.replace(/^https:/, "wss:")
    : "ws://localhost:8000");
export type Timeframe = "M1" | "M5" | "H1" | "H2" | "H4" | "D1" | "W1";

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
  leverage: number | null;
  trade_mode: "DEMO" | "REAL" | "UNKNOWN";
}

export interface MT5Status {
  connected_to_mt5: boolean;
  connected_to_backend: boolean;
  account_trade_mode: "DEMO" | "REAL" | "UNKNOWN";
  account: MT5Account | null;
  active_symbols: string[];
  last_tick_time_by_symbol: Record<string, string>;
  ticks_sent_total: number;
  last_batch_sent_at: string | null;
  errors_count: number;
  message: string | null;
  updated_at: string | null;
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
      bid: number | null;
      ask: number | null;
      last: number | null;
      mid?: number | null;
      spread?: number | null;
      volume: number | null;
      source: string | null;
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
    };

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

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers
  });

  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail ?? `HTTP ${response.status}`);
  }

  return (await response.json()) as T;
}

export function getSymbols(): Promise<SymbolMapping[]> {
  return request<SymbolMapping[]>("/api/symbols");
}

export function getCandles(symbol: string, timeframe: Timeframe, limit = 500): Promise<Candle[]> {
  const params = new URLSearchParams({ symbol, timeframe, limit: String(limit) });
  return request<Candle[]>(`/api/candles?${params.toString()}`);
}

export function getTicks(symbol: string, limit = 1000): Promise<Tick[]> {
  const params = new URLSearchParams({ symbol, limit: String(limit) });
  return request<Tick[]>(`/api/ticks?${params.toString()}`);
}

export function getLatestTick(symbol: string): Promise<LatestTickDiagnostic> {
  const params = new URLSearchParams({ symbol });
  return request<LatestTickDiagnostic>(`/api/market/latest-tick?${params.toString()}`);
}

export function getMockMarketStatus(): Promise<MockMarketStatus> {
  return request<MockMarketStatus>("/api/mock-market/status");
}

export function getMt5Status(): Promise<MT5Status> {
  return request<MT5Status>("/api/mt5/status");
}

export function startMockMarket(): Promise<MockMarketStatus> {
  return request<MockMarketStatus>("/api/mock-market/start", { method: "POST" });
}

export function stopMockMarket(): Promise<MockMarketStatus> {
  return request<MockMarketStatus>("/api/mock-market/stop", { method: "POST" });
}

export function createMarketWebSocket(symbol: string, timeframe: Timeframe): WebSocket {
  return new WebSocket(`${WS_BASE_URL}/ws/market/${symbol}/${timeframe}`);
}
