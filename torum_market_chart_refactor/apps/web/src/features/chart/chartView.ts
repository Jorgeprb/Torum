import type { CandlestickData, IChartApi, ISeriesApi, LineData, UTCTimestamp } from "lightweight-charts";
import type { NoTradeZone } from "../../services/news";
import { timeToNumber, timeframeToSeconds, utcToBrokerChartTime } from "./chartTime";

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
  W1: 70,
};

export function barsWithCandleSpacing(baseBars: number, candleCount: number): number {
  return Math.min(Math.max(minVisibleBars, baseBars), candleCount);
}

export function calculateVisibleBarsForWidth(containerWidth: number, timeframe: string, candleCount: number): number {
  if (candleCount <= 0) return 0;
  const safeWidth = Number.isFinite(containerWidth) && containerWidth > 0 ? containerWidth : 360;
  const barsByPixelSpacing = Math.floor(safeWidth / desiredCandleSpacingPx);
  const maxBars = maxVisibleBarsByTimeframe[timeframe] ?? 90;
  return Math.min(candleCount, Math.max(minVisibleBars, Math.min(barsByPixelSpacing, maxBars)));
}

export function centerRecentBars(
  chart: IChartApi,
  candleCount: number,
  timeframe: string,
  preferredVisibleBars?: number,
) {
  if (candleCount <= 0) return;
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
  preferredVisibleBars?: number,
) {
  if (candleCount <= 0) return;
  const currentRange = chart.timeScale().getVisibleLogicalRange();
  const fallbackBars = preferredVisibleBars ?? barsWithCandleSpacing(maxVisibleBarsByTimeframe[timeframe] ?? 90, candleCount);
  const visibleSpan = currentRange ? Math.max(8, currentRange.to - currentRange.from) : Math.max(8, fallbackBars + 4);
  const to = candleCount + 4;
  const from = Math.max(0, to - visibleSpan);
  chart.timeScale().setVisibleLogicalRange({ from, to });
}

export function lastRealCandleTime(candles: CandlestickData[]): number | null {
  const lastCandle = candles[candles.length - 1];
  return lastCandle ? timeToNumber(lastCandle.time) : null;
}

export function lastRealCandleClose(candles: CandlestickData[]): number | null {
  const lastCandle = candles[candles.length - 1];
  return lastCandle && Number.isFinite(lastCandle.close) ? lastCandle.close : null;
}

export function resetPriceScale(chart: IChartApi, series: ISeriesApi<"Candlestick">) {
  chart.priceScale("right").applyOptions({ autoScale: true, scaleMargins: { top: 0.18, bottom: 0.18 } });
  series.priceScale().applyOptions({ autoScale: true, scaleMargins: { top: 0.18, bottom: 0.18 } });
}

export function disablePriceAutoScale(chart: IChartApi, series: ISeriesApi<"Candlestick">) {
  chart.priceScale("right").applyOptions({ autoScale: false });
  series.priceScale().applyOptions({ autoScale: false });
}

export function hardResetChartView(
  chart: IChartApi,
  series: ISeriesApi<"Candlestick">,
  candleCount: number,
  timeframe: string,
  preferredVisibleBars?: number,
) {
  resetPriceScale(chart, series);

  if (candleCount <= 0) {
    chart.timeScale().fitContent();
    window.requestAnimationFrame(() => resetPriceScale(chart, series));
    return;
  }

  if (candleCount <= 2) {
    chart.timeScale().setVisibleLogicalRange({ from: 0, to: candleCount + 4 });
    window.requestAnimationFrame(() => resetPriceScale(chart, series));
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
  preferredVisibleBars?: number,
) {
  if (candleCount <= 0) {
    resetPriceScale(chart, series);
    return;
  }

  resetPriceScale(chart, series);

  if (candleCount <= 2) {
    chart.timeScale().setVisibleLogicalRange({ from: 0, to: candleCount + 4 });
    window.requestAnimationFrame(() => resetPriceScale(chart, series));
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
  });
}

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

export function buildFuturePaddingData(candles: CandlestickData[], noTradeZones: NoTradeZone[], timeframe: string): LineData[] {
  const lastTime = lastRealCandleTime(candles);
  const lastClose = lastRealCandleClose(candles);
  if (lastTime === null || lastClose === null) return [];

  const futureZones = noTradeZones.filter((zone) => isNewsZoneVisibleNow(zone) && newsZoneEnd(zone) > lastTime);
  if (futureZones.length === 0) return [];

  const timeframeSeconds = timeframeToSeconds(timeframe);
  const maxZoneEnd = Math.max(...futureZones.map(newsZoneEnd));
  const marginSeconds = Math.max(timeframeSeconds * 12, 60 * 60);
  const maxFutureTime = lastTime + Math.ceil(Math.max(timeframeSeconds, maxZoneEnd + marginSeconds - lastTime) / timeframeSeconds) * timeframeSeconds;

  const times: number[] = [];
  for (let time = lastTime + timeframeSeconds; time <= maxFutureTime; time += timeframeSeconds) {
    times.push(time);
  }

  return times.map((time) => ({ time: time as UTCTimestamp, value: lastClose }));
}
