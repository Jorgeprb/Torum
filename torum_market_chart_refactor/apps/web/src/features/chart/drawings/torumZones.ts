import type { ChartDrawingRead } from "../../../services/drawings";

export function isTorumV1OperationZone(drawing: ChartDrawingRead): boolean {
  const metadata = drawing.metadata ?? {};
  const payload = drawing.payload ?? {};
  return metadata.torum_v1_zone_enabled === true || payload.torum_v1_zone_enabled === true;
}

export function canBeTorumV1OperationZone(drawing: ChartDrawingRead | null): drawing is ChartDrawingRead {
  return Boolean(drawing && (drawing.drawing_type === "rectangle" || drawing.drawing_type === "manual_zone"));
}
