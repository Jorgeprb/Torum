import { apiRequest } from "./apiClient";

export type NewsImpact = "HIGH" | "MEDIUM" | "LOW";
export type NewsRuleAction = "DISPLAY" | "WARN" | "BLOCK_BOT" | "BLOCK_ALL";

export interface NewsImpactRule {
  enabled: boolean;
  minutes_before: number;
  minutes_after: number;
  action: NewsRuleAction;
}

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
  provider: "TORUM" | "MANUAL";
  auto_sync_enabled: boolean;
  sync_interval_minutes: number;
  days_ahead: number;
  last_sync_at: string | null;
  last_sync_status: string | null;
  last_sync_error: string | null;
  impact_rules_json: Record<string, NewsImpactRule>;
  manual_trade_policy: "ALLOW" | "WARN" | "REQUIRE_ACCEPTANCE" | "BLOCK";
  revision: number;
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

export interface NewsImportResponse { received: number; saved: number; zones_generated: number; errors: string[] }
export interface NewsProviderSyncResponse extends NewsImportResponse { provider: string; started_at: string; finished_at: string; status: string }
export interface NewsProviderStatus {
  provider: "TORUM" | "MANUAL";
  provider_enabled: boolean;
  auto_sync_enabled: boolean;
  sync_interval_minutes: number;
  days_ahead: number;
  block_trading_during_news: boolean;
  draw_news_zones_enabled: boolean;
  minutes_before: number;
  minutes_after: number;
  last_sync_at: string | null;
  last_sync_status: string | null;
  last_sync_error: string | null;
  impact_rules_json: Record<string, NewsImpactRule>;
  manual_trade_policy: string;
  revision: number;
  next_event: NewsEvent | null;
  imported_events: number;
  generated_zones: number;
}

export function getNewsSettings(): Promise<NewsSettings> { return apiRequest<NewsSettings>("/api/news/settings"); }
export function patchNewsSettings(payload: Partial<NewsSettings> & { expected_revision?: number }): Promise<NewsSettings> {
  return apiRequest<NewsSettings>("/api/news/settings", { method: "PATCH", body: JSON.stringify(payload) });
}
export function importNewsJson(source: string, events: unknown[]): Promise<NewsImportResponse> {
  return apiRequest<NewsImportResponse>("/api/news/import/json", { method: "POST", body: JSON.stringify({ source, events }) });
}
export function importNewsCsv(source: string, csvText: string): Promise<NewsImportResponse> {
  return apiRequest<NewsImportResponse>("/api/news/import/csv", { method: "POST", body: JSON.stringify({ source, csv_text: csvText }) });
}
export function getNewsEvents(params: { from?: string; to?: string; currency?: string; impact?: string; limit?: number } = {}): Promise<NewsEvent[]> {
  const query = new URLSearchParams();
  if (params.from) query.set("from", params.from);
  if (params.to) query.set("to", params.to);
  if (params.currency) query.set("currency", params.currency);
  if (params.impact) query.set("impact", params.impact);
  query.set("limit", String(params.limit ?? 500));
  return apiRequest<NewsEvent[]>(`/api/news/events?${query.toString()}`);
}
export function updateNewsEvent(id: number, payload: Partial<NewsEvent>): Promise<NewsEvent> {
  return apiRequest<NewsEvent>(`/api/news/events/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
}
export function deleteNewsEvent(id: number): Promise<void> { return apiRequest<void>(`/api/news/events/${id}`, { method: "DELETE" }); }
export function getNoTradeZones(symbol: string | null | undefined, from: string, to: string): Promise<NoTradeZone[]> {
  const params = new URLSearchParams({ from, to }); if (symbol) params.set("symbol", symbol);
  return apiRequest<NoTradeZone[]>(`/api/no-trade-zones?${params.toString()}`);
}
export function regenerateNoTradeZones(): Promise<{ regenerated: number }> { return apiRequest<{ regenerated: number }>("/api/no-trade-zones/regenerate", { method: "POST" }); }
export function getNewsProviderStatus(): Promise<NewsProviderStatus> { return apiRequest<NewsProviderStatus>("/api/news/providers/status"); }
export function syncNewsProvider(): Promise<NewsProviderSyncResponse> { return apiRequest<NewsProviderSyncResponse>("/api/news/providers/sync", { method: "POST", timeoutMs: 90_000 }); }
