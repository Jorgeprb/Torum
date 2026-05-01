import type { ChartDrawingCreate, ChartDrawingRead, DrawingTool } from "../../services/drawings";

export function styleValue(style: Record<string, unknown>, key: string, fallback: string): string {
  const value = style[key];
  return typeof value === "string" && value ? value : fallback;
}

export function numericStyleValue(style: Record<string, unknown>, key: string, fallback: number): number {
  const value = style[key];
  return typeof value === "number" ? value : fallback;
}

export function drawingLabel(drawing: ChartDrawingRead): string {
  const label = drawing.payload.label;
  if (typeof label === "string" && label.trim()) {
    return label;
  }
  if (drawing.name) {
    return drawing.name;
  }
  return drawing.drawing_type.replace("_", " ");
}

export function defaultDrawingStyle(tool: DrawingTool): Record<string, unknown> {
  if (tool === "manual_zone") {
    return {
      color: "#62d995",
      lineWidth: 2,
      lineStyle: "solid",
      glow: 0,
      opacity: 0.16,
      backgroundColor: "rgba(98,217,149,0.16)",
      textColor: "#edf2ef"
    };
  }
  if (tool === "rectangle") {
    return {
      color: "#d6b25e",
      lineWidth: 2,
      lineStyle: "solid",
      glow: 0,
      opacity: 0.13,
      backgroundColor: "rgba(214,178,94,0.13)",
      textColor: "#edf2ef"
    };
  }
  if (tool === "text") {
    return {
      color: "#edf2ef",
      lineWidth: 2,
      lineStyle: "solid",
      glow: 0,
      backgroundColor: "rgba(245,197,66,0.12)",
      textColor: "#edf2ef",
      fontSize: 14
    };
  }
  return {
    color: "#f5c542",
    lineWidth: 2,
    lineStyle: "solid",
    glow: 0,
    backgroundColor: "rgba(245,197,66,0.12)",
    textColor: "#edf2ef"
  };
}

export function toolName(tool: DrawingTool): string {
  const names: Record<DrawingTool, string> = {
    select: "Cursor",
    horizontal_line: "Horizontal",
    vertical_line: "Vertical",
    trend_line: "Tendencia",
    rectangle: "Rectangulo",
    text: "Texto",
    manual_zone: "Zona manual"
  };
  return names[tool];
}

export function createBaseDrawing(
  symbol: string,
  timeframe: string | null,
  tool: Exclude<DrawingTool, "select">,
  payload: Record<string, unknown>,
  name?: string | null
): ChartDrawingCreate {
  return {
    internal_symbol: symbol,
    timeframe: null,
    drawing_type: tool,
    name: name ?? null,
    payload,
    style: defaultDrawingStyle(tool),
    metadata: {},
    source: "MANUAL"
  };
}
