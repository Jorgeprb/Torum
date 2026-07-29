import { apiRequest } from "./apiClient";


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

export function getAdminSystemStatus(): Promise<SystemStatusResponse> {
  return apiRequest<SystemStatusResponse>("/api/admin/system/status");
}

export function restartSystemTarget(target: RestartTarget, confirmation: string): Promise<SystemRestartAction> {
  return apiRequest<SystemRestartAction>(`/api/admin/system/restart/${target}`, {
    method: "POST",
    body: JSON.stringify({ confirmation })
  });
}
