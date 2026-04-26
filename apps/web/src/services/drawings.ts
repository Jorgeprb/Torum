import { getAuthToken } from "../stores/authStore";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ||
  (window.location.protocol === "https:"
    ? window.location.origin
    : "http://localhost:8000");

export type DrawingTool = "select" | "horizontal_line" | "vertical_line" | "trend_line" | "rectangle" | "text" | "manual_zone";

export interface ChartDrawingRead {
  id: string;
  user_id: number;
  internal_symbol: string;
  timeframe: string;
  drawing_type: DrawingTool | string;
  name: string | null;
  payload: Record<string, unknown>;
  style: Record<string, unknown>;
  metadata: Record<string, unknown>;
  locked: boolean;
  visible: boolean;
  source: string;
  created_at: string;
  updated_at: string;
}

export interface ChartDrawingCreate {
  internal_symbol: string;
  timeframe: string;
  drawing_type: Exclude<DrawingTool, "select">;
  name?: string | null;
  payload: Record<string, unknown>;
  style?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  locked?: boolean;
  visible?: boolean;
  source?: string;
}

export interface ChartDrawingUpdate {
  name?: string | null;
  payload?: Record<string, unknown>;
  style?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  locked?: boolean;
  visible?: boolean;
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
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export function getDrawings(symbol: string, timeframe: string, includeHidden = true): Promise<ChartDrawingRead[]> {
  const params = new URLSearchParams({ symbol, timeframe, include_hidden: includeHidden ? "true" : "false" });
  return request<ChartDrawingRead[]>(`/api/drawings?${params.toString()}`);
}

export function createDrawing(payload: ChartDrawingCreate): Promise<ChartDrawingRead> {
  return request<ChartDrawingRead>("/api/drawings", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function patchDrawing(id: string, payload: ChartDrawingUpdate): Promise<ChartDrawingRead> {
  return request<ChartDrawingRead>(`/api/drawings/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

export function deleteDrawing(id: string): Promise<void> {
  return request<void>(`/api/drawings/${id}`, { method: "DELETE" });
}
