const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export type UserRole = "admin" | "trader";

export interface User {
  id: number;
  username: string;
  email: string;
  role: UserRole;
  is_active: boolean;
}

export interface LoginResponse {
  access_token: string;
  token_type: "bearer";
  user: User;
}

export interface SystemStatus {
  project: string;
  environment: string;
  tailscale_enabled: boolean;
  public_host: string;
  trading_mode: "PAPER" | "DEMO" | "LIVE";
  mt5_bridge_configured: boolean;
  roles: UserRole[];
}

interface RequestOptions extends RequestInit {
  token?: string | null;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");

  if (options.token) {
    headers.set("Authorization", `Bearer ${options.token}`);
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers
  });

  if (!response.ok) {
    const fallbackMessage = `HTTP ${response.status}`;
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail ?? fallbackMessage);
  }

  return (await response.json()) as T;
}

export function login(username: string, password: string): Promise<LoginResponse> {
  return request<LoginResponse>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password })
  });
}

export function getMe(token: string): Promise<User> {
  return request<User>("/api/v1/auth/me", { token });
}

export function getSystemStatus(token?: string | null): Promise<SystemStatus> {
  return request<SystemStatus>("/api/v1/system/status", { token });
}
