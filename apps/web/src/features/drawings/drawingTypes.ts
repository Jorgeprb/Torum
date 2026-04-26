import type { ChartDrawingRead, DrawingTool } from "../../services/drawings";

export type { ChartDrawingRead, DrawingTool };

export interface DrawingPoint {
  time: number;
  price: number;
}

export interface DrawingCoordinate {
  x: number;
  y: number;
}

export interface DrawingShapeBase {
  id: string;
  drawing: ChartDrawingRead;
  color: string;
  lineWidth: number;
  label?: string;
}

export type DrawingShape =
  | (DrawingShapeBase & { kind: "horizontal_line"; x1: number; x2: number; y: number })
  | (DrawingShapeBase & { kind: "vertical_line"; x: number; y1: number; y2: number })
  | (DrawingShapeBase & { kind: "trend_line"; x1: number; y1: number; x2: number; y2: number })
  | (DrawingShapeBase & { kind: "rectangle"; x: number; y: number; width: number; height: number; backgroundColor: string })
  | (DrawingShapeBase & { kind: "manual_zone"; x: number; y: number; width: number; height: number; backgroundColor: string; direction: string })
  | (DrawingShapeBase & { kind: "text"; x: number; y: number; text: string; textColor: string });
