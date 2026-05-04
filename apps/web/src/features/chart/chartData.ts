import { type CandlestickData, type LineData, type UTCTimestamp } from "lightweight-charts";

import type { Candle } from "../../services/market";
import { normalizeUnixSeconds, timeToNumber } from "./chartTime";

export function isValidOhlc(candle: Candle): boolean {
  return (
    Number.isFinite(candle.open) &&
    Number.isFinite(candle.high) &&
    Number.isFinite(candle.low) &&
    Number.isFinite(candle.close)
  );
}

export function toChartCandle(candle: Candle): CandlestickData | null {
  const time = normalizeUnixSeconds(candle.time);

  if (time === null || !isValidOhlc(candle)) {
    return null;
  }

  return {
    time,
    open: candle.open,
    high: candle.high,
    low: candle.low,
    close: candle.close
  };
}

export function sortCandlesByTimeAsc(candles: CandlestickData[]): CandlestickData[] {
  const byTime = new Map<number, CandlestickData>();

  for (const candle of candles) {
    if (candle.time === undefined || candle.time === null) {
      continue;
    }

    const numericTime = timeToNumber(candle.time);

    if (!Number.isFinite(numericTime) || numericTime <= 0) {
      continue;
    }

    // Si hay varias velas con el mismo timestamp, nos quedamos con la última recibida.
    byTime.set(numericTime, {
      ...candle,
      time: numericTime as UTCTimestamp
    });
  }

  return [...byTime.values()].sort((a, b) => timeToNumber(a.time) - timeToNumber(b.time));
}

export function normalizeCandlesForChart(candles: Candle[]): CandlestickData[] {
  return sortCandlesByTimeAsc(
    candles
      .map(toChartCandle)
      .filter((candle): candle is CandlestickData => candle !== null)
  );
}

export function sortLineDataByTimeAsc(data: LineData[]): LineData[] {
  return [...data]
    .filter((point) => point.time !== undefined && point.time !== null)
    .sort((a, b) => timeToNumber(a.time) - timeToNumber(b.time));
}

export function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function payloadsEqual(
  left: Record<string, unknown> | undefined,
  right: Record<string, unknown> | undefined
): boolean {
  if (!left || !right) {
    return false;
  }

  return JSON.stringify(left) === JSON.stringify(right);
}
