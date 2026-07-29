import { apiRequest } from "./apiClient";


export type PriceAlertStatus = "ACTIVE" | "TRIGGERED" | "CANCELLED" | "EXPIRED";

export interface PriceAlertRead {
  id: string;
  user_id: number;
  internal_symbol: string;
  timeframe: string | null;
  condition_type: "BELOW";
  target_price: number;
  status: PriceAlertStatus;
  source: "CHART" | "MANUAL" | "IMPORT";
  message: string | null;
  triggered_at: string | null;
  triggered_price: number | null;
  last_checked_price: number | null;
  created_at: string;
  updated_at: string;
}

export interface PriceAlertCreate {
  internal_symbol: string;
  timeframe?: string | null;
  condition_type?: "BELOW";
  target_price: number;
  message?: string | null;
  source?: "CHART" | "MANUAL" | "IMPORT";
}

export interface PriceAlertUpdate {
  target_price?: number;
  message?: string | null;
  status?: "ACTIVE" | "CANCELLED";
}

export interface PushSubscriptionRead {
  id: string;
  user_id: number;
  endpoint: string;
  user_agent: string | null;
  device_name: string | null;
  enabled: boolean;
  created_at: string;
  updated_at: string;
  last_used_at: string | null;
}

export interface PushTestResponse {
  ok: boolean;
  sent: number;
  failed: number;
  message: string;
}

export function getPriceAlerts(symbol: string, status: PriceAlertStatus = "ACTIVE"): Promise<PriceAlertRead[]> {
  const params = new URLSearchParams({ symbol, status });
  return apiRequest<PriceAlertRead[]>(`/api/alerts/price?${params.toString()}`);
}

export function getPriceAlertHistory(symbol: string): Promise<PriceAlertRead[]> {
  const params = new URLSearchParams({ symbol });
  return apiRequest<PriceAlertRead[]>(`/api/alerts/price/history?${params.toString()}`);
}

export function createPriceAlert(payload: PriceAlertCreate): Promise<PriceAlertRead> {
  return apiRequest<PriceAlertRead>("/api/alerts/price", {
    method: "POST",
    body: JSON.stringify({ ...payload, condition_type: "BELOW" })
  });
}

export function patchPriceAlert(id: string, payload: PriceAlertUpdate): Promise<PriceAlertRead> {
  return apiRequest<PriceAlertRead>(`/api/alerts/price/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

export function cancelPriceAlert(id: string): Promise<void> {
  return apiRequest<void>(`/api/alerts/price/${id}`, { method: "DELETE" });
}

export function getVapidPublicKey(): Promise<{ public_key: string | null }> {
  return apiRequest<{ public_key: string | null }>("/api/push/vapid-public-key");
}

export function subscribePush(payload: PushSubscriptionJSON & { user_agent?: string; device_name?: string }): Promise<PushSubscriptionRead> {
  return apiRequest<PushSubscriptionRead>("/api/push/subscribe", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function getPushSubscriptions(): Promise<PushSubscriptionRead[]> {
  return apiRequest<PushSubscriptionRead[]>("/api/push/subscriptions");
}

export function sendPushTest(): Promise<PushTestResponse> {
  return apiRequest<PushTestResponse>("/api/push/test", { method: "POST" });
}
