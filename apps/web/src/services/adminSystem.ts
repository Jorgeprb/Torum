import { getAuthToken } from "../stores/authStore";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ||
  (window.location.protocol === "https:"
    ? window.location.origin
    : `http://${window.location.hostname === "localhost" ? "localhost" : window.location.hostname}:8000`);

export type SystemHealthStatus = "OK" | "WARN" | "FAIL" | "RESTARTING" | "UNKNOWN";
export type RestartTarget = "mt5" | "api" | "frontend" | "bridge" | "all" | "pc";

export interface SystemStatusItem {
  key: string;
  label: string;
  status: SystemHealthStatus;
  message: string;
  updated_at: string;
  details: Record<string, unknown>;
}

export interface SystemRestartAction {
  action_id: string;
  target: RestartTarget;
  status: string;
  updated_at: string;
  log_tail: string;
}

export interface SystemStatusResponse {
  status: SystemHealthStatus;
  message: string;
  items: SystemStatusItem[];
  account_mode: "DEMO" | "REAL" | "UNKNOWN" | string;
  last_tick_at: string | null;
  last_tick_age_seconds: number | null;
  action_running: boolean;
  actions: SystemRestartAction[];
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");
  const token = getAuthToken();
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

export function getAdminSystemStatus(): Promise<SystemStatusResponse> {
  return request<SystemStatusResponse>("/api/admin/system/status");
}

export function restartSystemTarget(target: RestartTarget, confirmation: string): Promise<SystemRestartAction> {
  return request<SystemRestartAction>(`/api/admin/system/restart/${target}`, {
    method: "POST",
    body: JSON.stringify({ confirmation })
  });
}
