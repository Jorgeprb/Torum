import type { DrawingShape } from "../../drawings/drawingTypes";

export function distancePointToSegment(
  px: number,
  py: number,
  x1: number,
  y1: number,
  x2: number,
  y2: number
): number {
  const dx = x2 - x1;
  const dy = y2 - y1;

  if (dx === 0 && dy === 0) {
    return Math.hypot(px - x1, py - y1);
  }

  const t = Math.max(
    0,
    Math.min(
      1,
      ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
    )
  );

  const nearestX = x1 + t * dx;
  const nearestY = y1 + t * dy;

  return Math.hypot(px - nearestX, py - nearestY);
}

export function isPointInsideDrawingShape(
  shape: DrawingShape,
  x: number,
  y: number
): boolean {
  const tolerance = 18;

  if (shape.kind === "horizontal_line") {
    return Math.abs(y - shape.y) <= tolerance;
  }

  if (shape.kind === "vertical_line") {
    return Math.abs(x - shape.x) <= tolerance;
  }

  if (shape.kind === "text") {
    const width = Math.max(54, shape.text.length * shape.fontSize * 0.58 + 28);
    const left = shape.x - 12;
    const top = shape.y - shape.fontSize - 14;

    return (
      x >= left &&
      x <= left + width &&
      y >= top &&
      y <= top + shape.fontSize + 20
    );
  }

  if (shape.kind === "trend_line") {
    const distance = distancePointToSegment(x, y, shape.x1, shape.y1, shape.x2, shape.y2);
    return distance <= tolerance;
  }

  if (shape.kind === "rectangle" || shape.kind === "manual_zone") {
    return (
      x >= shape.x &&
      x <= shape.x + shape.width &&
      y >= shape.y &&
      y <= shape.y + shape.height
    );
  }

  return false;
}
