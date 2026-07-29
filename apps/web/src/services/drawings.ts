import { apiRequest } from "./apiClient";


export type DrawingTool = "select" | "horizontal_line" | "vertical_line" | "trend_line" | "rectangle" | "text" | "manual_zone";

export interface ChartDrawingRead {
  id: string;
  user_id: number;
  internal_symbol: string;
  timeframe: string | null;
  drawing_type: DrawingTool | string;
  name: string | null;
  payload: Record<string, unknown>;
  style: Record<string, unknown>;
  metadata: Record<string, unknown>;
  locked: boolean;
  visible: boolean;
  source: string;
  revision: number;
  created_at: string;
  updated_at: string;
}

export interface ChartDrawingCreate {
  internal_symbol: string;
  timeframe?: string | null;
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
  expected_revision?: number;
  name?: string | null;
  payload?: Record<string, unknown>;
  style?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  locked?: boolean;
  visible?: boolean;
}

export function getDrawings(symbol: string, timeframe?: string | null, includeHidden = true): Promise<ChartDrawingRead[]> {
  const params = new URLSearchParams({ symbol, include_hidden: includeHidden ? "true" : "false" });
  if (timeframe) {
    params.set("timeframe", timeframe);
  }
  return apiRequest<ChartDrawingRead[]>(`/api/drawings?${params.toString()}`);
}

export function createDrawing(payload: ChartDrawingCreate): Promise<ChartDrawingRead> {
  return apiRequest<ChartDrawingRead>("/api/drawings", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function patchDrawing(id: string, payload: ChartDrawingUpdate): Promise<ChartDrawingRead> {
  return apiRequest<ChartDrawingRead>(`/api/drawings/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

export function deleteDrawing(id: string): Promise<void> {
  return apiRequest<void>(`/api/drawings/${id}`, { method: "DELETE" });
}
