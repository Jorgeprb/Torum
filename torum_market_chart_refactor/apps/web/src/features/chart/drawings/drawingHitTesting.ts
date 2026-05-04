import type { DrawingShape } from "../../drawings/drawingTypes";
import { distancePointToSegment } from "./drawingGeometry";

export function isPointInsideDrawingShape(shape: DrawingShape, x: number, y: number): boolean {
  const tolerance = 18;

  if (shape.kind === "horizontal_line") return Math.abs(y - shape.y) <= tolerance;
  if (shape.kind === "vertical_line") return Math.abs(x - shape.x) <= tolerance;

  if (shape.kind === "trend_line") {
    return distancePointToSegment(x, y, shape.x1, shape.y1, shape.x2, shape.y2) <= tolerance;
  }

  if (shape.kind === "rectangle" || shape.kind === "manual_zone") {
    const left = Math.min(shape.x, shape.x + shape.width);
    const right = Math.max(shape.x, shape.x + shape.width);
    const top = Math.min(shape.y, shape.y + shape.height);
    const bottom = Math.max(shape.y, shape.y + shape.height);
    return x >= left && x <= right && y >= top && y <= bottom;
  }

  if (shape.kind === "text") {
    const width = Math.max(54, shape.text.length * shape.fontSize * 0.58 + 28);
    const height = shape.fontSize + 20;
    const left = shape.x - 12;
    const top = shape.y - shape.fontSize - 14;
    return x >= left && x <= left + width && y >= top && y <= top + height;
  }

  return false;
}
