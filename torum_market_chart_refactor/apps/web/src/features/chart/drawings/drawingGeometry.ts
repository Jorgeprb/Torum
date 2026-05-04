import { timeframeBucketStart, timeframeToSeconds } from "../chartTime";

export function drawingTimeSpanFromPoints(firstTime: number, secondTime: number, timeframe: string): { time1: number; time2: number } {
  const timeframeSeconds = timeframeToSeconds(timeframe);
  const firstStart = timeframeBucketStart(firstTime, timeframe);
  const secondStart = timeframeBucketStart(secondTime, timeframe);
  const left = Math.min(firstStart, secondStart);
  const right = Math.max(firstStart, secondStart) + timeframeSeconds;
  return { time1: left, time2: right <= left ? left + timeframeSeconds : right };
}

export function distancePointToSegment(
  px: number,
  py: number,
  x1: number,
  y1: number,
  x2: number,
  y2: number,
): number {
  const dx = x2 - x1;
  const dy = y2 - y1;

  if (dx === 0 && dy === 0) return Math.hypot(px - x1, py - y1);

  const t = Math.max(0, Math.min(1, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)));
  const nearestX = x1 + t * dx;
  const nearestY = y1 + t * dy;

  return Math.hypot(px - nearestX, py - nearestY);
}
