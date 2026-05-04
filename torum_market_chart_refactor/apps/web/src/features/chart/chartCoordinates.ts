import type { CandlestickData, IChartApi, Time } from "lightweight-charts";
import { candleTimeValues, chartTimeToUnix } from "./chartData";
import { clampNumber } from "./chartStyle";
import { timeToNumber } from "./chartTime";

export function cssPixelValue(element: HTMLElement, name: string, fallback = 0): number {
  const raw = window.getComputedStyle(element).getPropertyValue(name).trim();
  const value = Number.parseFloat(raw);
  return Number.isFinite(value) ? value : fallback;
}

export function lowerBound(values: number[], target: number): number {
  let low = 0;
  let high = values.length;
  while (low < high) {
    const mid = Math.floor((low + high) / 2);
    if (values[mid] < target) low = mid + 1;
    else high = mid;
  }
  return low;
}

export function timeToChartX(chart: IChartApi, candles: CandlestickData[], time: number, fallback: number): number {
  const direct = chart.timeScale().timeToCoordinate(time as Time);
  if (direct !== null) return direct;

  const times = candleTimeValues(candles);
  if (times.length < 2) return fallback;

  const index = lowerBound(times, time);
  const leftIndex = clampNumber(index - 1, 0, times.length - 2);
  const rightIndex = leftIndex + 1;
  const leftTime = times[leftIndex];
  const rightTime = times[rightIndex];
  const leftX = chart.timeScale().timeToCoordinate(leftTime as Time);
  const rightX = chart.timeScale().timeToCoordinate(rightTime as Time);

  if (leftX === null || rightX === null || rightTime === leftTime) return fallback;

  const ratio = (time - leftTime) / (rightTime - leftTime);
  return leftX + (rightX - leftX) * ratio;
}

export function chartXToTime(
  chart: IChartApi,
  candles: CandlestickData[],
  x: number,
  fallback: number | null = null,
): number | null {
  const times = candleTimeValues(candles);
  if (times.length < 2) return chartTimeToUnix(chart.timeScale().coordinateToTime(x)) ?? fallback;

  const points = times
    .map((time): { time: number; x: number } | null => {
      const coordinate = chart.timeScale().timeToCoordinate(time as Time);
      return coordinate === null ? null : { time, x: Number(coordinate) };
    })
    .filter((point): point is { time: number; x: number } => point !== null)
    .sort((left, right) => left.x - right.x);

  if (points.length < 2) return chartTimeToUnix(chart.timeScale().coordinateToTime(x)) ?? fallback;

  let left = points[0];
  let right = points[1];
  if (x <= points[0].x) {
    left = points[0];
    right = points[1];
  } else if (x >= points[points.length - 1].x) {
    left = points[points.length - 2];
    right = points[points.length - 1];
  } else {
    for (let index = 1; index < points.length; index += 1) {
      if (points[index].x >= x) {
        left = points[index - 1];
        right = points[index];
        break;
      }
    }
  }

  if (right.x === left.x) return fallback;

  const ratio = (x - left.x) / (right.x - left.x);
  return Math.floor(left.time + (right.time - left.time) * ratio);
}
