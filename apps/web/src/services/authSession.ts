import { createRequestId } from "./requestId";
import { resolveApiBaseUrl } from "./runtime";

const API_BASE_URL = resolveApiBaseUrl();
const ACCESS_TOKEN_STORAGE_KEY = "torum.access_token";
const SESSION_TOKEN_STORAGE_KEY = "torum.session_token";
const USER_STORAGE_KEY = "torum.auth_user";

export const AUTH_SESSION_INVALID_EVENT = "torum:auth-session-invalid";
export const AUTH_ACCESS_TOKEN_UPDATED_EVENT = "torum:auth-access-token-updated";

interface RefreshResponse {
  access_token: string;
  token_type: "bearer";
}

let refreshPromise: Promise<string | null> | null = null;

export function getAuthToken(): string | null {
  return window.localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY);
}

export function getPersistentSessionToken(): string | null {
  return window.localStorage.getItem(SESSION_TOKEN_STORAGE_KEY);
}

export function getCachedAuthUser<T>(): T | null {
  const raw = window.localStorage.getItem(USER_STORAGE_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as T;
  } catch {
    window.localStorage.removeItem(USER_STORAGE_KEY);
    return null;
  }
}

export function setCachedAuthUser(user: unknown) {
  window.localStorage.setItem(USER_STORAGE_KEY, JSON.stringify(user));
}

export function setPersistentSessionToken(token: string) {
  window.localStorage.setItem(SESSION_TOKEN_STORAGE_KEY, token);
}

export function setAuthToken(token: string, notify = false) {
  window.localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, token);
  if (notify) window.dispatchEvent(new Event(AUTH_ACCESS_TOKEN_UPDATED_EVENT));
}

export function storeAuthenticatedSession(accessToken: string, sessionToken: string, user: unknown) {
  setAuthToken(accessToken);
  setPersistentSessionToken(sessionToken);
  setCachedAuthUser(user);
}

export function clearAuthenticatedSession(notify = false) {
  window.localStorage.removeItem(ACCESS_TOKEN_STORAGE_KEY);
  window.localStorage.removeItem(SESSION_TOKEN_STORAGE_KEY);
  window.localStorage.removeItem(USER_STORAGE_KEY);
  if (notify) window.dispatchEvent(new Event(AUTH_SESSION_INVALID_EVENT));
}

function tokenExpiresWithin(token: string, seconds: number): boolean {
  try {
    const parts = token.split(".");
    if (parts.length !== 3) return true;
    const normalized = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, "=");
    const payload = JSON.parse(window.atob(padded)) as { exp?: unknown };
    if (typeof payload.exp !== "number") return true;
    return payload.exp * 1000 - Date.now() <= seconds * 1000;
  } catch {
    return true;
  }
}

export async function refreshStoredAccessToken(): Promise<string | null> {
  const sessionToken = getPersistentSessionToken();
  if (!sessionToken) return null;
  if (refreshPromise) return refreshPromise;

  refreshPromise = (async () => {
    const requestId = createRequestId();
    let response: Response;
    try {
      response = await fetch(`${API_BASE_URL}/api/v1/auth/refresh`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Request-ID": requestId,
        },
        body: JSON.stringify({ session_token: sessionToken }),
      });
    } catch (error) {
      // A transient network problem must never destroy a persistent session.
      throw error;
    }

    if (response.status === 401 || response.status === 403) {
      clearAuthenticatedSession(true);
      return null;
    }
    if (!response.ok) {
      throw new Error(`No se pudo renovar la sesión (HTTP ${response.status})`);
    }

    const payload = (await response.json()) as RefreshResponse;
    setAuthToken(payload.access_token, true);
    return payload.access_token;
  })().finally(() => {
    refreshPromise = null;
  });

  return refreshPromise;
}

export async function ensureFreshStoredAccessToken(minValiditySeconds = 60 * 60): Promise<string | null> {
  const token = getAuthToken();
  if (token && !tokenExpiresWithin(token, minValiditySeconds)) return token;
  if (!getPersistentSessionToken()) return token;
  return refreshStoredAccessToken();
}
