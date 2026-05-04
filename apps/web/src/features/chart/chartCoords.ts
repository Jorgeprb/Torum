import { type CandlestickData, type IChartApi, type ISeriesApi, type LineData, type UTCTimestamp } from "lightweight-charts";

import type { NoTradeZone } from "../../services/news";
import { timeToNumber, timeframeToSeconds, utcToBrokerChartTime } from "./chartTime";
import { clampNumber } from "./chartStyle";

// ── Constants ────────────────────────────────────────────────────────────────
export const desiredCandleSpacingPx = 18;
export const initialCandleBarSpacing = 18;
export const minVisibleBars = 22;

export const maxVisibleBarsByTimeframe: Record<string, number> = {
  M1: 120,
  M5: 110,
  H1: 100,
  H2: 95,
  H3: 92,
  H4: 90,
  D1: 80,
  W1: 70
};

// ── Pixel helpers ────────────────────────────────────────────────────────────
export function cssPixelValue(element: HTMLElement, name: string, fallback = 0): number {
  const raw = window.getComputedStyle(element).getPropertyValue(name).trim();
  const value = Number.parseFloat(raw);
  return Number.isFinite(value) ? value : fallback;
}

// ── Time → coord helpers ─────────────────────────────────────────────────────
export function chartTimeToUnix(time: import("lightweight-charts").Time | null): number | null {
  if (time === null) {
    return null;
  }

  if (typeof time === "number") {
    return Math.floor(time);
  }

  if (typeof time === "string") {
    const parsed = Date.parse(time);
    return Number.isNaN(parsed) ? null : Math.floor(parsed / 1000);
  }

  return Math.floor(Date.UTC(time.year, time.month - 1, time.day) / 1000);
}

export function candleTimeValues(candles: CandlestickData[]): number[] {
  return candles.map((candle) => timeToNumber(candle.time)).filter((time) => Number.isFinite(time) && time > 0);
}

function lowerBound(values: number[], target: number): number {
  let low = 0;
  let high = values.length;

  while (low < high) {
    const mid = Math.floor((low + high) / 2);
    if (values[mid] < target) {
      low = mid + 1;
    } else {
      high = mid;
    }
  }

  return low;
}

export function timeToChartX(chart: IChartApi, candles: CandlestickData[], time: number, fallback: number): number {
  const direct = chart.timeScale().timeToCoordinate(time as UTCTimestamp);
  if (direct !== null) {
    return direct;
  }

  const times = candleTimeValues(candles);
  if (times.length < 2) {
    return fallback;
  }

  const index = lowerBound(times, time);
  const leftIndex = clampNumber(index - 1, 0, times.length - 2);
  const rightIndex = leftIndex + 1;
  const leftTime = times[leftIndex];
  const rightTime = times[rightIndex];
  const leftX = chart.timeScale().timeToCoordinate(leftTime as UTCTimestamp);
  const rightX = chart.timeScale().timeToCoordinate(rightTime as UTCTimestamp);

  if (leftX === null || rightX === null || rightTime === leftTime) {
    return fallback;
  }

  const ratio = (time - leftTime) / (rightTime - leftTime);
  return leftX + (rightX - leftX) * ratio;
}

export function chartXToTime(
  chart: IChartApi,
  candles: CandlestickData[],
  x: number,
  fallback: number | null = null
): number | null {
  const times = candleTimeValues(candles);
  if (times.length < 2) {
    return chartTimeToUnix(chart.timeScale().coordinateToTime(x)) ?? fallback;
  }

  const points = times
    .map((time): { time: number; x: number } | null => {
      const coordinate = chart.timeScale().timeToCoordinate(time as UTCTimestamp);
      return coordinate === null ? null : { time, x: Number(coordinate) };
    })
    .filter((point): point is { time: number; x: number } => point !== null)
    .sort((left, right) => left.x - right.x);

  if (points.length < 2) {
    return chartTimeToUnix(chart.timeScale().coordinateToTime(x)) ?? fallback;
  }

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

  if (right.x === left.x) {
    return fallback;
  }

  const ratio = (x - left.x) / (right.x - left.x);
  return Math.floor(left.time + (right.time - left.time) * ratio);
}

// ── Drawing time span ────────────────────────────────────────────────────────
export function drawingTimeSpanFromPoints(
  firstTime: number,
  secondTime: number,
  timeframe: string
): { time1: number; time2: number } {
  const timeframeSeconds = timeframeToSeconds(timeframe);
  const firstStart = timeframeToSeconds(timeframe) > 0
    ? Math.floor(firstTime / timeframeSeconds) * timeframeSeconds
    : firstTime;
  const secondStart = timeframeToSeconds(timeframe) > 0
    ? Math.floor(secondTime / timeframeSeconds) * timeframeSeconds
    : secondTime;
  const left = Math.min(firstStart, secondStart);
  const right = Math.max(firstStart, secondStart) + timeframeSeconds;

  return {
    time1: left,
    time2: right <= left ? left + timeframeSeconds : right
  };
}

// ── Visible bars helpers ─────────────────────────────────────────────────────
export function barsWithCandleSpacing(baseBars: number, candleCount: number): number {
  return Math.min(Math.max(minVisibleBars, baseBars), candleCount);
}

export function calculateVisibleBarsForWidth(
  containerWidth: number,
  timeframe: string,
  candleCount: number
): number {
  if (candleCount <= 0) {
    return 0;
  }

  const safeWidth = Number.isFinite(containerWidth) && containerWidth > 0 ? containerWidth : 360;
  const barsByPixelSpacing = Math.floor(safeWidth / desiredCandleSpacingPx);
  const maxBars = maxVisibleBarsByTimeframe[timeframe] ?? 90;

  return Math.min(
    candleCount,
    Math.max(minVisibleBars, Math.min(barsByPixelSpacing, maxBars))
  );
}

// ── Last candle helpers ──────────────────────────────────────────────────────
export function lastRealCandleTime(candles: CandlestickData[]): number | null {
  const lastCandle = candles[candles.length - 1];
  return lastCandle ? timeToNumber(lastCandle.time) : null;
}

export function lastRealCandleClose(candles: CandlestickData[]): number | null {
  const lastCandle = candles[candles.length - 1];
  return lastCandle && Number.isFinite(lastCandle.close) ? lastCandle.close : null;
}

// ── Price scale helpers ──────────────────────────────────────────────────────
export function resetPriceScale(chart: IChartApi, series: ISeriesApi<"Candlestick">) {
  /*
   * Fuerza a Lightweight Charts a olvidar cualquier zoom/scroll vertical previo.
   */
  chart.priceScale("right").applyOptions({
    autoScale: true,
    scaleMargins: { top: 0.18, bottom: 0.18 }
  });

  series.priceScale().applyOptions({
    autoScale: true,
    scaleMargins: { top: 0.18, bottom: 0.18 }
  });
}

export function disablePriceAutoScale(chart: IChartApi, series: ISeriesApi<"Candlestick">) {
  /*
   * Permite que el usuario mantenga su ajuste manual del eje vertical.
   */
  chart.priceScale("right").applyOptions({ autoScale: false });
  series.priceScale().applyOptions({ autoScale: false });
}

// ── Chart view resets ────────────────────────────────────────────────────────
export function centerRecentBars(
  chart: IChartApi,
  candleCount: number,
  timeframe: string,
  preferredVisibleBars?: number
) {
  if (candleCount <= 0) {
    return;
  }

  if (candleCount <= 2) {
    chart.timeScale().setVisibleLogicalRange({ from: 0, to: candleCount + 4 });
    return;
  }

  const bars = preferredVisibleBars ?? barsWithCandleSpacing(maxVisibleBarsByTimeframe[timeframe] ?? 90, candleCount);
  const from = Math.max(0, candleCount - bars);
  const to = candleCount + 4;

  chart.timeScale().setVisibleLogicalRange({ from, to });
}

export function scrollToLatestRealCandle(
  chart: IChartApi,
  candleCount: number,
  timeframe: string,
  preferredVisibleBars?: number
) {
  if (candleCount <= 0) {
    return;
  }

  const currentRange = chart.timeScale().getVisibleLogicalRange();
  const fallbackBars = preferredVisibleBars ?? barsWithCandleSpacing(maxVisibleBarsByTimeframe[timeframe] ?? 90, candleCount);
  const visibleSpan = currentRange
    ? Math.max(8, currentRange.to - currentRange.from)
    : Math.max(8, fallbackBars + 4);

  const to = candleCount + 4;
  const from = Math.max(0, to - visibleSpan);

  chart.timeScale().setVisibleLogicalRange({ from, to });
}

export function hardResetChartView(
  chart: IChartApi,
  series: ISeriesApi<"Candlestick">,
  candleCount: number,
  timeframe: string,
  preferredVisibleBars?: number
) {
  /*
   * Reset fuerte de escala vertical y horizontal.
   */
  resetPriceScale(chart, series);

  if (candleCount <= 0) {
    chart.timeScale().fitContent();
    window.requestAnimationFrame(() => { resetPriceScale(chart, series); });
    return;
  }

  if (candleCount <= 2) {
    chart.timeScale().setVisibleLogicalRange({ from: 0, to: candleCount + 4 });
    window.requestAnimationFrame(() => { resetPriceScale(chart, series); });
    return;
  }

  const bars = preferredVisibleBars ?? barsWithCandleSpacing(maxVisibleBarsByTimeframe[timeframe] ?? 90, candleCount);
  const rightOffset = 4;
  const from = Math.max(0, candleCount - bars);
  const to = candleCount + rightOffset;

  chart.timeScale().setVisibleLogicalRange({ from, to });

  window.requestAnimationFrame(() => {
    resetPriceScale(chart, series);
    chart.timeScale().setVisibleLogicalRange({ from, to });

    window.requestAnimationFrame(() => {
      resetPriceScale(chart, series);
      chart.timeScale().setVisibleLogicalRange({ from, to });
    });
  });
}

export function centerSymbolChange(
  chart: IChartApi,
  series: ISeriesApi<"Candlestick">,
  candleCount: number,
  timeframe: string,
  preferredVisibleBars?: number
) {
  if (candleCount <= 0) {
    resetPriceScale(chart, series);
    return;
  }

  resetPriceScale(chart, series);

  if (candleCount <= 2) {
    chart.timeScale().setVisibleLogicalRange({ from: 0, to: candleCount + 4 });
    window.requestAnimationFrame(() => { resetPriceScale(chart, series); });
    return;
  }

  const bars = preferredVisibleBars ?? barsWithCandleSpacing(maxVisibleBarsByTimeframe[timeframe] ?? 90, candleCount);
  const rightOffset = 4;
  const from = Math.max(0, candleCount - bars);
  const to = candleCount + rightOffset;

  chart.timeScale().setVisibleLogicalRange({ from, to });

  window.requestAnimationFrame(() => { resetPriceScale(chart, series); });
}

// ── News zone helpers ────────────────────────────────────────────────────────
export function newsZoneStartUtc(zone: NoTradeZone): number {
  return Math.floor(new Date(zone.start_time).getTime() / 1000);
}

export function newsZoneEndUtc(zone: NoTradeZone): number {
  return Math.floor(new Date(zone.end_time).getTime() / 1000);
}

export function newsZoneStart(zone: NoTradeZone): number {
  return utcToBrokerChartTime(newsZoneStartUtc(zone));
}

export function newsZoneEnd(zone: NoTradeZone): number {
  return utcToBrokerChartTime(newsZoneEndUtc(zone));
}

export function isNewsZoneVisibleNow(zone: NoTradeZone, nowMs = Date.now()): boolean {
  return newsZoneEndUtc(zone) * 1000 >= nowMs;
}

export function snapFutureChartTime(
  time: number,
  lastTime: number | null,
  timeframeSeconds: number,
  mode: "floor" | "ceil"
): number {
  if (lastTime === null || time <= lastTime) {
    return time;
  }

  const rawSteps = (time - lastTime) / timeframeSeconds;
  const steps = mode === "floor" ? Math.floor(rawSteps) : Math.ceil(rawSteps);
  return lastTime + Math.max(1, steps) * timeframeSeconds;
}

export function buildFuturePaddingData(
  candles: CandlestickData[],
  noTradeZones: NoTradeZone[],
  timeframe: string
): LineData[] {
  const lastTime = lastRealCandleTime(candles);
  const lastClose = lastRealCandleClose(candles);

  if (lastTime === null || lastClose === null) {
    return [];
  }

  const futureZones = noTradeZones.filter((zone) => isNewsZoneVisibleNow(zone) && newsZoneEnd(zone) > lastTime);

  if (futureZones.length === 0) {
    return [];
  }

  const timeframeSeconds = timeframeToSeconds(timeframe);
  const maxZoneEnd = Math.max(...futureZones.map(newsZoneEnd));
  const marginSeconds = Math.max(timeframeSeconds * 12, 60 * 60);
  const maxFutureTime =
    lastTime + Math.ceil(Math.max(timeframeSeconds, maxZoneEnd + marginSeconds - lastTime) / timeframeSeconds) * timeframeSeconds;
  const times: number[] = [];

  for (let time = lastTime + timeframeSeconds; time <= maxFutureTime; time += timeframeSeconds) {
    times.push(time);
  }

  return times.map((time) => ({
    time: time as UTCTimestamp,
    value: lastClose
  }));
}
