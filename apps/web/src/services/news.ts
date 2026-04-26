import { getAuthToken } from "../stores/authStore";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export interface NewsSettings {
  id: number;
  user_id: number | null;
  draw_news_zones_enabled: boolean;
  block_trading_during_news: boolean;
  minutes_before: number;
  minutes_after: number;
  currencies_filter: string[];
  countries_filter: string[];
  impact_filter: string[];
  affected_symbols: string[];
  provider_enabled: boolean;
  provider_name: string;
}

export interface NewsEvent {
  id: number;
  source: string;
  external_id: string | null;
  country: string;
  currency: string;
  impact: string;
  title: string;
  event_time: string;
  previous_value: string | null;
  forecast_value: string | null;
  actual_value: string | null;
  url: string | null;
}

export interface NoTradeZone {
  id: number;
  news_event_id: number | null;
  source: string;
  reason: string;
  internal_symbol: string;
  start_time: string;
  end_time: string;
  enabled: boolean;
  blocks_trading: boolean;
  visual_only: boolean;
}

export interface NewsImportResponse {
  received: number;
  saved: number;
  zones_generated: number;
  errors: string[];
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

export function getNewsSettings(): Promise<NewsSettings> {
  return request<NewsSettings>("/api/news/settings");
}

export function patchNewsSettings(payload: Partial<NewsSettings>): Promise<NewsSettings> {
  return request<NewsSettings>("/api/news/settings", {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

export function importNewsJson(source: string, events: unknown[]): Promise<NewsImportResponse> {
  return request<NewsImportResponse>("/api/news/import/json", {
    method: "POST",
    body: JSON.stringify({ source, events })
  });
}

export function importNewsCsv(source: string, csvText: string): Promise<NewsImportResponse> {
  return request<NewsImportResponse>("/api/news/import/csv", {
    method: "POST",
    body: JSON.stringify({ source, csv_text: csvText })
  });
}

export function getNewsEvents(): Promise<NewsEvent[]> {
  return request<NewsEvent[]>("/api/news/events?limit=100");
}

export function getNoTradeZones(symbol: string, from: string, to: string): Promise<NoTradeZone[]> {
  const params = new URLSearchParams({ symbol, from, to });
  return request<NoTradeZone[]>(`/api/no-trade-zones?${params.toString()}`);
}

export function regenerateNoTradeZones(): Promise<{ regenerated: number }> {
  return request<{ regenerated: number }>("/api/no-trade-zones/regenerate", { method: "POST" });
}
