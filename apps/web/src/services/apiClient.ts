import { getAuthToken } from "../stores/authStore";
import { createRequestId } from "./requestId";
import { resolveApiBaseUrl } from "./runtime";

const API_BASE_URL = resolveApiBaseUrl();

export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;
  readonly requestId: string;

  constructor(message: string, status: number, detail: unknown, requestId: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.requestId = requestId;
  }
}

export interface ApiRequestOptions extends RequestInit {
  token?: string | null;
  timeoutMs?: number;
  retry?: number;
}

export async function apiRequest<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
  const requestId = createRequestId();
  const controller = new AbortController();
  const externalSignal = options.signal;
  const timeoutMs = options.timeoutMs ?? 15_000;
  const timeout = window.setTimeout(() => controller.abort("timeout"), timeoutMs);
  const onAbort = () => controller.abort(externalSignal?.reason ?? "aborted");
  externalSignal?.addEventListener("abort", onAbort, { once: true });

  const headers = new Headers(options.headers);
  headers.set("X-Request-ID", requestId);
  if (!(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const token = options.token === undefined ? getAuthToken() : options.token;
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const attempts = Math.max(1, (options.retry ?? 0) + 1);
  try {
    for (let attempt = 1; attempt <= attempts; attempt += 1) {
      try {
        const response = await fetch(`${API_BASE_URL}${path}`, {
          ...options,
          headers,
          signal: controller.signal,
        });
        if (!response.ok) {
          const detail = await response.json().catch(() => null);
          const message =
            detail && typeof detail === "object" && "detail" in detail
              ? String((detail as { detail?: unknown }).detail ?? `HTTP ${response.status}`)
              : `HTTP ${response.status}`;
          throw new ApiError(message, response.status, detail, requestId);
        }
        if (response.status === 204) return undefined as T;
        return (await response.json()) as T;
      } catch (error) {
        if (attempt >= attempts || error instanceof ApiError || controller.signal.aborted) throw error;
        await new Promise((resolve) => window.setTimeout(resolve, 200 * attempt));
      }
    }
    throw new Error("Unreachable API retry state");
  } finally {
    window.clearTimeout(timeout);
    externalSignal?.removeEventListener("abort", onAbort);
  }
}
