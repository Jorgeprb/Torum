function localBackendHost(): string {
  const hostname = window.location.hostname || "localhost";
  return hostname === "localhost" || hostname === "127.0.0.1" ? hostname : hostname;
}

export function resolveApiBaseUrl(): string {
  const envUrl = import.meta.env.VITE_API_BASE_URL;

  if (typeof window === "undefined") {
    return envUrl || "http://localhost:8000";
  }

  if (window.location.protocol === "http:") {
    return `http://${localBackendHost()}:8000`;
  }

  return envUrl || window.location.origin;
}

export function resolveWsBaseUrl(): string {
  const envUrl = import.meta.env.VITE_WS_BASE_URL;

  if (typeof window === "undefined") {
    return envUrl || "ws://localhost:8000";
  }

  if (window.location.protocol === "http:") {
    return `ws://${localBackendHost()}:8000`;
  }

  return envUrl || window.location.origin.replace(/^https:/, "wss:");
}
