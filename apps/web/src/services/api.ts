import { apiRequest } from "./apiClient";


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
  session_token: string;
  token_type: "bearer";
  user: User;
}

export interface SessionBootstrapResponse {
  session_token: string;
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

export function login(username: string, password: string): Promise<LoginResponse> {
  return apiRequest<LoginResponse>("/api/v1/auth/login", {
    method: "POST",
    token: null,
    body: JSON.stringify({ username, password })
  });
}

export function getMe(): Promise<User> {
  return apiRequest<User>("/api/v1/auth/me");
}

export function bootstrapPersistentSession(): Promise<SessionBootstrapResponse> {
  return apiRequest<SessionBootstrapResponse>("/api/v1/auth/session", { method: "POST" });
}

export function revokePersistentSession(sessionToken: string): Promise<void> {
  return apiRequest<void>("/api/v1/auth/logout", {
    method: "POST",
    token: null,
    timeoutMs: 3_000,
    keepalive: true,
    body: JSON.stringify({ session_token: sessionToken })
  });
}

export function getSystemStatus(token?: string | null): Promise<SystemStatus> {
  return apiRequest<SystemStatus>("/api/v1/system/status", { token });
}
