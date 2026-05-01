import { type CSSProperties, type PointerEvent, useCallback, useEffect, useRef, useState } from "react";
import { Bell, LocateFixed, SlidersHorizontal, Trash2 } from "lucide-react";
import {
  type CandlestickData,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type LineData,
  LineStyle,
  type Time,
  TickMarkType,
  type UTCTimestamp,
  createChart
} from "lightweight-charts";

import type { Candle } from "../../services/market";
import type { PriceAlertRead } from "../../services/alerts";
import type { NoTradeZone } from "../../services/news";
import { type IndicatorLineOutput } from "../../services/indicators";
import type { ChartDrawingCreate, ChartDrawingRead, ChartDrawingUpdate, DrawingTool } from "../../services/drawings";
import { DrawingLayer } from "../drawings/DrawingLayer";
import type { DrawingCoordinate, DrawingDragAction, DrawingPoint, DrawingShape } from "../drawings/drawingTypes";
import { createBaseDrawing, drawingLabel, numericStyleValue, styleValue } from "../drawings/drawingUtils";

interface MarketChartProps {
  candles: Candle[];
  loadingCandles?: boolean;
  symbolResetToken?: number;
  hardResetToken?: number;
  noTradeZones?: NoTradeZone[];
  indicatorLines?: IndicatorLineOutput[];
  drawings?: ChartDrawingRead[];
  drawingTool?: DrawingTool;
  selectedDrawingId?: string | null;
  symbol: string;
  timeframe: string;
  onCreateDrawing?: (drawing: ChartDrawingCreate) => void;
  onUpdateDrawing?: (drawing: ChartDrawingRead, patch: ChartDrawingUpdate) => void | Promise<void>;
  onDeleteDrawing?: (drawingId: string) => void;
  onSelectDrawing?: (drawingId: string | null) => void;
  tradeLines?: TradeLine[];
  tradeMarkers?: TradeMarker[];
  onSelectPosition?: (positionId: number) => void;
  onUpdatePositionTp?: (positionId: number, tp: number, closePrice?: number | null) => void | Promise<void>;
  alertToolActive?: boolean;
  priceAlerts?: PriceAlertRead[];
  onCreatePriceAlert?: (price: number) => void;
  onUpdatePriceAlert?: (alert: PriceAlertRead, targetPrice: number) => void;
  onCancelPriceAlert?: (alertId: string) => void;
  bidPrice?: number | null;
  askPrice?: number | null;
  showBidLine?: boolean;
  showAskLine?: boolean;
  autoFollowEnabled?: boolean;
  onAutoFollowChange?: (enabled: boolean) => void;
  recenterToken?: number;
  resetKey?: string;
  showFutureNewsZones?: boolean;
  autoExtendToFutureNews?: boolean;
}

interface ZoneOverlay {
  id: number;
  left: number;
  width: number;
  zone: NoTradeZone;
}

export interface TradeLine {
  id: string;
  positionId?: number;
  price: number;
  label: string;
  tone: "entry" | "tp" | "close";
  side?: "BUY" | "SELL";
  volume?: number;
  openPrice?: number;
  profit?: number;
  contractSize?: number;
  currency?: string;
  editable?: boolean;
  muted?: boolean;
  selected?: boolean;
}
export interface TradeMarker {
  id: string;
  time: Time;
  price: number;
  kind: "BUY" | "CLOSE";
  label: string;
}
type ChartLineStyle = "solid" | "dashed";

interface PriceAlertVisualStyle {
  color: string;
  lineStyle: ChartLineStyle;
}

const DEFAULT_ALERT_VISUAL_STYLE: PriceAlertVisualStyle = {
  color: "#f5c542",
  lineStyle: "dashed"
};

const ALERT_STYLE_STORAGE_KEY = "torum.priceAlertStyles.v1";

interface TradeLineOverlay extends TradeLine {
  y: number;
}
interface TradeMarkerOverlay extends TradeMarker {
  x: number;
  y: number;
}
interface PriceAlertOverlay {
  alert: PriceAlertRead;
  y: number;
  targetPrice: number;
}

function normalizeUnixSeconds(value: unknown): UTCTimestamp | null {
  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      return null;
    }

    // Si viene en milisegundos, lo convertimos a segundos.
    // Lightweight Charts trabaja bien con Unix seconds.
    const seconds = value > 10_000_000_000 ? Math.floor(value / 1000) : Math.floor(value);
    return seconds as UTCTimestamp;
  }

  if (typeof value === "string") {
    const parsedAsNumber = Number(value);

    if (Number.isFinite(parsedAsNumber)) {
      const seconds = parsedAsNumber > 10_000_000_000 ? Math.floor(parsedAsNumber / 1000) : Math.floor(parsedAsNumber);
      return seconds as UTCTimestamp;
    }

    const parsedDate = Date.parse(value);

    if (!Number.isNaN(parsedDate)) {
      return Math.floor(parsedDate / 1000) as UTCTimestamp;
    }
  }

  return null;
}

const chartDisplayTimeZone = "Europe/Madrid";
const defaultChartBrokerTimeZone = "Etc/GMT-3";
const chartBrokerTimeZoneStorageKey = "torum.chartBrokerTimeZone";
const chartTimeModeStorageKey = "torum.chartTimeMode";
const chartManualBrokerUtcOffsetStorageKey = "torum.chartManualBrokerUtcOffset";
const chartManualLocalUtcOffsetStorageKey = "torum.chartManualLocalUtcOffset";
const chartTimeSettingsChangedEvent = "torum-chart-time-settings-changed";
type ChartTimeMode = "auto" | "manual";

function isValidTimeZone(timeZone: string): boolean {
  try {
    new Intl.DateTimeFormat("en-US", { timeZone }).format(new Date(0));
    return true;
  } catch {
    return false;
  }
}

function validTimeZoneOrFallback(value: string | undefined, fallback: string): string {
  const candidate = value?.trim();
  return candidate && isValidTimeZone(candidate) ? candidate : fallback;
}

function readChartBrokerTimeZone(): string {
  const envValue = import.meta.env.VITE_CHART_BROKER_TIME_ZONE;

  if (typeof window === "undefined") {
    return validTimeZoneOrFallback(envValue, defaultChartBrokerTimeZone);
  }

  try {
    const storedValue = window.localStorage.getItem(chartBrokerTimeZoneStorageKey) ?? undefined;
    return validTimeZoneOrFallback(storedValue || envValue, defaultChartBrokerTimeZone);
  } catch {
    return validTimeZoneOrFallback(envValue, defaultChartBrokerTimeZone);
  }
}

function readChartTimeMode(): ChartTimeMode {
  if (typeof window === "undefined") {
    return "auto";
  }

  try {
    return window.localStorage.getItem(chartTimeModeStorageKey) === "manual" ? "manual" : "auto";
  } catch {
    return "auto";
  }
}

function currentUtcOffsetHours(timeZone: string): number {
  const value = new Intl.DateTimeFormat("en-US", {
    hour: "2-digit",
    hour12: false,
    hourCycle: "h23",
    timeZone
  }).format(new Date());
  const utcHour = new Date().getUTCHours();
  let offset = Number(value) - utcHour;

  if (offset > 12) {
    offset -= 24;
  }

  if (offset < -12) {
    offset += 24;
  }

  return offset;
}

function readStoredUtcOffset(key: string, fallback: number): number {
  if (typeof window === "undefined") {
    return fallback;
  }

  try {
    const parsed = Number(window.localStorage.getItem(key));
    return Number.isInteger(parsed) && parsed >= -12 && parsed <= 14 ? parsed : fallback;
  } catch {
    return fallback;
  }
}

function utcOffsetDifferenceSeconds(brokerUtcOffset: number, localUtcOffset: number): number {
  return (brokerUtcOffset - localUtcOffset) * 60 * 60;
}

function createTimeZonePartsFormatter(timeZone: string): Intl.DateTimeFormat {
  return new Intl.DateTimeFormat("en-US", {
    day: "2-digit",
    hour: "2-digit",
    hour12: false,
    hourCycle: "h23",
    minute: "2-digit",
    month: "2-digit",
    second: "2-digit",
    timeZone,
    year: "numeric"
  });
}

const chartBrokerTimeZone = readChartBrokerTimeZone();
const chartBrokerTimeZoneFormatter = createTimeZonePartsFormatter(chartBrokerTimeZone);
const chartDisplayTimeZoneFormatter = createTimeZonePartsFormatter(chartDisplayTimeZone);
const chartCrosshairTimeFormatter = new Intl.DateTimeFormat("es-ES", {
  day: "2-digit",
  hour: "2-digit",
  hour12: false,
  hourCycle: "h23",
  minute: "2-digit",
  month: "2-digit",
  timeZone: chartDisplayTimeZone,
  year: "numeric"
});
const chartTickYearFormatter = new Intl.DateTimeFormat("es-ES", {
  timeZone: chartDisplayTimeZone,
  year: "numeric"
});
const chartTickMonthFormatter = new Intl.DateTimeFormat("es-ES", {
  month: "short",
  timeZone: chartDisplayTimeZone
});
const chartTickDayFormatter = new Intl.DateTimeFormat("es-ES", {
  day: "2-digit",
  month: "2-digit",
  timeZone: chartDisplayTimeZone
});
const chartTickTimeFormatter = new Intl.DateTimeFormat("es-ES", {
  hour: "2-digit",
  hour12: false,
  hourCycle: "h23",
  minute: "2-digit",
  timeZone: chartDisplayTimeZone
});
const chartTickSecondsFormatter = new Intl.DateTimeFormat("es-ES", {
  hour: "2-digit",
  hour12: false,
  hourCycle: "h23",
  minute: "2-digit",
  second: "2-digit",
  timeZone: chartDisplayTimeZone
});

function timeZoneOffsetSeconds(formatter: Intl.DateTimeFormat, utcUnixSeconds: number): number {
  const parts = formatter.formatToParts(new Date(utcUnixSeconds * 1000));
  const values: Record<string, number> = {};

  for (const part of parts) {
    if (part.type === "year" || part.type === "month" || part.type === "day" || part.type === "hour" || part.type === "minute" || part.type === "second") {
      values[part.type] = Number(part.value);
    }
  }

  const hour = values.hour === 24 ? 0 : values.hour;
  const localAsUtcSeconds = Math.floor(
    Date.UTC(
      values.year ?? 1970,
      (values.month ?? 1) - 1,
      values.day ?? 1,
      hour ?? 0,
      values.minute ?? 0,
      values.second ?? 0
    ) / 1000
  );

  return localAsUtcSeconds - Math.floor(utcUnixSeconds);
}

function manualBrokerLocalOffsetSeconds(): number {
  return utcOffsetDifferenceSeconds(
    readStoredUtcOffset(chartManualBrokerUtcOffsetStorageKey, currentUtcOffsetHours(chartBrokerTimeZone)),
    readStoredUtcOffset(chartManualLocalUtcOffsetStorageKey, currentUtcOffsetHours(chartDisplayTimeZone))
  );
}

function chartBrokerOffsetSeconds(utcUnixSeconds: number): number {
  if (readChartTimeMode() === "manual") {
    return timeZoneOffsetSeconds(chartDisplayTimeZoneFormatter, utcUnixSeconds) + manualBrokerLocalOffsetSeconds();
  }

  return timeZoneOffsetSeconds(chartBrokerTimeZoneFormatter, utcUnixSeconds);
}

function utcToBrokerChartTime(utcUnixSeconds: number): number {
  return Math.floor(utcUnixSeconds + chartBrokerOffsetSeconds(utcUnixSeconds));
}

function brokerChartTimeToUtc(chartUnixSeconds: number): number {
  let utcUnixSeconds = chartUnixSeconds - chartBrokerOffsetSeconds(chartUnixSeconds);

  for (let iteration = 0; iteration < 3; iteration += 1) {
    utcUnixSeconds = chartUnixSeconds - chartBrokerOffsetSeconds(utcUnixSeconds);
  }

  return Math.floor(utcUnixSeconds);
}

function chartTimeToDisplayDate(time: Time): Date {
  return new Date(brokerChartTimeToUtc(timeToNumber(time)) * 1000);
}

function formatChartCrosshairTime(time: Time): string {
  return chartCrosshairTimeFormatter.format(chartTimeToDisplayDate(time));
}

function formatChartTickMark(time: Time, tickMarkType: TickMarkType): string {
  const displayDate = chartTimeToDisplayDate(time);

  if (tickMarkType === TickMarkType.Year) {
    return chartTickYearFormatter.format(displayDate);
  }

  if (tickMarkType === TickMarkType.Month) {
    return chartTickMonthFormatter.format(displayDate).replace(".", "");
  }

  if (tickMarkType === TickMarkType.DayOfMonth) {
    return chartTickDayFormatter.format(displayDate);
  }

  if (tickMarkType === TickMarkType.TimeWithSeconds) {
    return chartTickSecondsFormatter.format(displayDate);
  }

  return chartTickTimeFormatter.format(displayDate);
}

function isValidOhlc(candle: Candle): boolean {
  return (
    Number.isFinite(candle.open) &&
    Number.isFinite(candle.high) &&
    Number.isFinite(candle.low) &&
    Number.isFinite(candle.close)
  );
}

function toChartCandle(candle: Candle): CandlestickData | null {
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

function timeToNumber(time: Time): number {
  if (typeof time === "number") {
    return time;
  }

  if (typeof time === "string") {
    const parsed = Date.parse(time);
    return Number.isNaN(parsed) ? 0 : Math.floor(parsed / 1000);
  }

  return Math.floor(Date.UTC(time.year, time.month - 1, time.day) / 1000);
}
function timeframeToSeconds(timeframe: string): number {
  switch (timeframe) {
    case "M1":
      return 60;
    case "M5":
      return 5 * 60;
    case "H1":
      return 60 * 60;
    case "H2":
      return 2 * 60 * 60;
    case "H3":
      return 3 * 60 * 60;
    case "H4":
      return 4 * 60 * 60;
    case "D1":
      return 24 * 60 * 60;
    case "W1":
      return 7 * 24 * 60 * 60;
    default:
      return 60;
  }
}

function timeframeBucketStart(unixSeconds: number, timeframe: string): number {
  const date = new Date(unixSeconds * 1000);

  const year = date.getUTCFullYear();
  const month = date.getUTCMonth();
  const day = date.getUTCDate();
  const hour = date.getUTCHours();
  const minute = date.getUTCMinutes();

  if (timeframe === "M1") {
    return Math.floor(Date.UTC(year, month, day, hour, minute, 0, 0) / 1000);
  }

  if (timeframe === "M5") {
    const bucketMinute = Math.floor(minute / 5) * 5;
    return Math.floor(Date.UTC(year, month, day, hour, bucketMinute, 0, 0) / 1000);
  }

  if (timeframe === "H1") {
    return Math.floor(Date.UTC(year, month, day, hour, 0, 0, 0) / 1000);
  }

  if (timeframe === "H2") {
    const bucketHour = Math.floor(hour / 2) * 2;
    return Math.floor(Date.UTC(year, month, day, bucketHour, 0, 0, 0) / 1000);
  }

  if (timeframe === "H3") {
    const bucketHour = Math.floor(hour / 3) * 3;
    return Math.floor(Date.UTC(year, month, day, bucketHour, 0, 0, 0) / 1000);
  }

  if (timeframe === "H4") {
    const bucketHour = Math.floor(hour / 4) * 4;
    return Math.floor(Date.UTC(year, month, day, bucketHour, 0, 0, 0) / 1000);
  }

  if (timeframe === "D1") {
    return Math.floor(Date.UTC(year, month, day, 0, 0, 0, 0) / 1000);
  }

  if (timeframe === "W1") {
    const startOfDay = Date.UTC(year, month, day, 0, 0, 0, 0);
    const utcDay = new Date(startOfDay).getUTCDay();
    const daysFromMonday = utcDay === 0 ? 6 : utcDay - 1;
    return Math.floor((startOfDay - daysFromMonday * 24 * 60 * 60 * 1000) / 1000);
  }

  return unixSeconds;
}

function findNearestCandleTime(targetTime: number, candleTimes: number[]): number | null {
  if (candleTimes.length === 0) {
    return null;
  }

  let bestTime = candleTimes[0];
  let bestDistance = Math.abs(bestTime - targetTime);

  for (const candleTime of candleTimes) {
    const distance = Math.abs(candleTime - targetTime);

    if (distance < bestDistance) {
      bestTime = candleTime;
      bestDistance = distance;
    }
  }

  return bestTime;
}

function markerTimeToChartTime(markerTime: Time, timeframe: string, candleTimes: number[]): UTCTimestamp | null {
  const rawTime = timeToNumber(markerTime);

  if (!Number.isFinite(rawTime) || rawTime <= 0) {
    return null;
  }

  const bucketTime = timeframeBucketStart(rawTime, timeframe);

  if (candleTimes.includes(bucketTime)) {
    return bucketTime as UTCTimestamp;
  }

  const nearestTime = findNearestCandleTime(bucketTime, candleTimes);

  if (nearestTime === null) {
    return null;
  }

  const maxDistance = timeframeToSeconds(timeframe);

  if (Math.abs(nearestTime - bucketTime) > maxDistance) {
    return null;
  }

  return nearestTime as UTCTimestamp;
}
function sortCandlesByTimeAsc(candles: CandlestickData[]): CandlestickData[] {
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
function normalizeCandlesForChart(candles: Candle[]): CandlestickData[] {
  return sortCandlesByTimeAsc(
    candles
      .map(toChartCandle)
      .filter((candle): candle is CandlestickData => candle !== null)
  );
}

function sortLineDataByTimeAsc(data: LineData[]): LineData[] {
  return [...data]
    .filter((point) => point.time !== undefined && point.time !== null)
    .sort((a, b) => timeToNumber(a.time) - timeToNumber(b.time));
}

function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function payloadsEqual(left: Record<string, unknown> | undefined, right: Record<string, unknown> | undefined): boolean {
  if (!left || !right) {
    return false;
  }

  return JSON.stringify(left) === JSON.stringify(right);
}

function tradeLineLabel(line: TradeLine, price: number): string {
  if (
    line.tone === "tp" &&
    typeof line.openPrice === "number" &&
    Number.isFinite(line.openPrice) &&
    line.openPrice !== 0 &&
    typeof line.volume === "number" &&
    typeof line.contractSize === "number"
  ) {
    const direction = line.side === "SELL" ? -1 : 1;
    const tpPercent = ((price - line.openPrice) / line.openPrice) * 100 * direction;
    const profit = (price - line.openPrice) * line.volume * line.contractSize * direction;
    return `TP, ${profit >= 0 ? "+" : ""}${profit.toFixed(2)} ${line.currency ?? ""}, ${tpPercent.toFixed(2)}%`;
  }

  return line.label;
}

function clampNumber(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function clampedNumericStyleValue(style: Record<string, unknown>, key: string, fallback: number, min: number, max: number): number {
  return clampNumber(numericStyleValue(style, key, fallback), min, max);
}

function lineStyleValue(style: Record<string, unknown>, fallback: ChartLineStyle = "solid"): ChartLineStyle {
  return style.lineStyle === "dashed" ? "dashed" : fallback;
}

function cssLineStyle(lineStyle: ChartLineStyle): CSSProperties["borderTopStyle"] {
  return lineStyle === "dashed" ? "dashed" : "solid";
}

function hexToRgba(color: string, opacity: number): string {
  const normalized = color.trim();
  const match = /^#([0-9a-f]{6})$/i.exec(normalized);

  if (!match) {
    return normalized;
  }

  const value = match[1];
  const red = parseInt(value.slice(0, 2), 16);
  const green = parseInt(value.slice(2, 4), 16);
  const blue = parseInt(value.slice(4, 6), 16);
  return `rgba(${red}, ${green}, ${blue}, ${clampNumber(opacity, 0, 1)})`;
}

function colorInputValue(color: string, fallback: string): string {
  return /^#[0-9a-f]{6}$/i.test(color) ? color : fallback;
}

function normalizeAlertVisualStyle(value: unknown): PriceAlertVisualStyle {
  if (!value || typeof value !== "object") {
    return DEFAULT_ALERT_VISUAL_STYLE;
  }

  const source = value as Record<string, unknown>;
  return {
    color: typeof source.color === "string" && source.color ? source.color : DEFAULT_ALERT_VISUAL_STYLE.color,
    lineStyle: source.lineStyle === "solid" ? "solid" : "dashed"
  };
}

function loadAlertVisualStyles(): Record<string, PriceAlertVisualStyle> {
  try {
    if (typeof window === "undefined") {
      return {};
    }

    const raw = window.localStorage.getItem(ALERT_STYLE_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : null;

    if (!parsed || typeof parsed !== "object") {
      return {};
    }

    return Object.fromEntries(
      Object.entries(parsed as Record<string, unknown>).map(([id, value]) => [id, normalizeAlertVisualStyle(value)])
    );
  } catch {
    return {};
  }
}

function saveAlertVisualStyles(styles: Record<string, PriceAlertVisualStyle>) {
  try {
    if (typeof window === "undefined") {
      return;
    }

    window.localStorage.setItem(ALERT_STYLE_STORAGE_KEY, JSON.stringify(styles));
  } catch {
    // La app puede seguir sin persistencia local.
  }
}

function cssPixelValue(element: HTMLElement, name: string, fallback = 0): number {
  const raw = window.getComputedStyle(element).getPropertyValue(name).trim();
  const value = Number.parseFloat(raw);
  return Number.isFinite(value) ? value : fallback;
}

function chartTimeToUnix(time: Time | null): number | null {
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

function candleTimeValues(candles: CandlestickData[]): number[] {
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

function timeToChartX(chart: IChartApi, candles: CandlestickData[], time: number, fallback: number): number {
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

function chartXToTime(chart: IChartApi, candles: CandlestickData[], x: number, fallback: number | null = null): number | null {
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

function drawingTimeSpanFromPoints(firstTime: number, secondTime: number, timeframe: string): { time1: number; time2: number } {
  const timeframeSeconds = timeframeToSeconds(timeframe);
  const firstStart = timeframeBucketStart(firstTime, timeframe);
  const secondStart = timeframeBucketStart(secondTime, timeframe);
  const left = Math.min(firstStart, secondStart);
  const right = Math.max(firstStart, secondStart) + timeframeSeconds;

  return {
    time1: left,
    time2: right <= left ? left + timeframeSeconds : right
  };
}

const desiredCandleSpacingPx = 18;
const initialCandleBarSpacing = 18;
const minVisibleBars = 22;

const maxVisibleBarsByTimeframe: Record<string, number> = {
  M1: 120,
  M5: 110,
  H1: 100,
  H2: 95,
  H3: 92,
  H4: 90,
  D1: 80,
  W1: 70
};

function barsWithCandleSpacing(baseBars: number, candleCount: number): number {
  return Math.min(Math.max(minVisibleBars, baseBars), candleCount);
}

function calculateVisibleBarsForWidth(
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

function centerRecentBars(
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
function scrollToLatestRealCandle(
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

function lastRealCandleTime(candles: CandlestickData[]): number | null {
  const lastCandle = candles[candles.length - 1];
  return lastCandle ? timeToNumber(lastCandle.time) : null;
}

function lastRealCandleClose(candles: CandlestickData[]): number | null {
  const lastCandle = candles[candles.length - 1];
  return lastCandle && Number.isFinite(lastCandle.close) ? lastCandle.close : null;
}

function newsZoneStartUtc(zone: NoTradeZone): number {
  return Math.floor(new Date(zone.start_time).getTime() / 1000);
}

function newsZoneEndUtc(zone: NoTradeZone): number {
  return Math.floor(new Date(zone.end_time).getTime() / 1000);
}

function newsZoneStart(zone: NoTradeZone): number {
  return utcToBrokerChartTime(newsZoneStartUtc(zone));
}

function newsZoneEnd(zone: NoTradeZone): number {
  return utcToBrokerChartTime(newsZoneEndUtc(zone));
}

function isNewsZoneVisibleNow(zone: NoTradeZone, nowMs = Date.now()): boolean {
  return newsZoneEndUtc(zone) * 1000 >= nowMs;
}

function snapFutureChartTime(
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

function buildFuturePaddingData(
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
function resetPriceScale(chart: IChartApi, series: ISeriesApi<"Candlestick">) {
  /*
   * Fuerza a Lightweight Charts a olvidar cualquier zoom/scroll vertical previo.
   * Esto es importante al cambiar entre activos con precios muy distintos:
   * XAUUSD ~4600, XAUEUR ~3900, DXY ~100, etc.
   */
  chart.priceScale("right").applyOptions({
    autoScale: true,
    scaleMargins: {
      top: 0.18,
      bottom: 0.18
    }
  });

  series.priceScale().applyOptions({
    autoScale: true,
    scaleMargins: {
      top: 0.18,
      bottom: 0.18
    }
  });
}

function disablePriceAutoScale(chart: IChartApi, series: ISeriesApi<"Candlestick">) {
  /*
   * Permite que el usuario mantenga su ajuste manual del eje vertical.
   * Se usa cuando detectamos interacción sobre la escala de precios.
   */
  chart.priceScale("right").applyOptions({
    autoScale: false
  });

  series.priceScale().applyOptions({
    autoScale: false
  });
}
function hardResetChartView(
  chart: IChartApi,
  series: ISeriesApi<"Candlestick">,
  candleCount: number,
  timeframe: string,
  preferredVisibleBars?: number
) {
  /*
   * Reset fuerte de escala vertical.
   * Sirve para corregir casos donde el rango de precio queda heredado
   * de otro activo o de un zoom manual.
   */
  resetPriceScale(chart, series);

  /*
   * Reset horizontal con zoom adecuado por timeframe.
   */
  if (candleCount <= 0) {
    chart.timeScale().fitContent();

    window.requestAnimationFrame(() => {
      resetPriceScale(chart, series);
    });

    return;
  }

  if (candleCount <= 2) {
    chart.timeScale().setVisibleLogicalRange({ from: 0, to: candleCount + 4 });

    window.requestAnimationFrame(() => {
      resetPriceScale(chart, series);
    });

    return;
  }

   const bars = preferredVisibleBars ?? barsWithCandleSpacing(maxVisibleBarsByTimeframe[timeframe] ?? 90, candleCount);
  const rightOffset = 4;
  const from = Math.max(0, candleCount - bars);
  const to = candleCount + rightOffset;

  chart.timeScale().setVisibleLogicalRange({ from, to });

  /*
   * Aplicamos reset varias veces en frames distintos porque Lightweight Charts
   * a veces recalcula escalas después de setData/setVisibleLogicalRange.
   */
  window.requestAnimationFrame(() => {
    resetPriceScale(chart, series);
    chart.timeScale().setVisibleLogicalRange({ from, to });

    window.requestAnimationFrame(() => {
      resetPriceScale(chart, series);
      chart.timeScale().setVisibleLogicalRange({ from, to });
    });
  });
}

function centerSymbolChange(
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

    window.requestAnimationFrame(() => {
      resetPriceScale(chart, series);
    });

    return;
  }

  const bars = preferredVisibleBars ?? barsWithCandleSpacing(maxVisibleBarsByTimeframe[timeframe] ?? 90, candleCount);
  const rightOffset = 4;
  const from = Math.max(0, candleCount - bars);
  const to = candleCount + rightOffset;

  chart.timeScale().setVisibleLogicalRange({ from, to });

  /*
   * Segundo reset en el siguiente frame, después de que setData y el rango lógico
   * hayan aplicado. Esto evita que se quede el rango vertical del activo anterior.
   */
  window.requestAnimationFrame(() => {
    resetPriceScale(chart, series);
  });
}

export function MarketChart({
  candles,
  loadingCandles = false,
  symbolResetToken = 0,
  hardResetToken = 0,
  noTradeZones = [],
  indicatorLines = [],
  drawings = [],
  drawingTool = "select",
  selectedDrawingId = null,
  symbol,
  timeframe,
  onCreateDrawing,
  onUpdateDrawing,
  onDeleteDrawing,
  onSelectDrawing,
  tradeLines = [],
  tradeMarkers = [],
  onSelectPosition,
  onUpdatePositionTp,
  alertToolActive = false,
  priceAlerts = [],
  onCreatePriceAlert,
  onUpdatePriceAlert,
  onCancelPriceAlert,
  bidPrice = null,
  askPrice = null,
  showBidLine = true,
  showAskLine = true,
  autoFollowEnabled = true,
  onAutoFollowChange,
  recenterToken = 0,
  resetKey,
  showFutureNewsZones = true,
  autoExtendToFutureNews = true
}: MarketChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const lineSeriesRef = useRef<Map<string, ISeriesApi<"Line">>>(new Map());
  const futurePaddingSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const bidPriceLineRef = useRef<IPriceLine | null>(null);
  const askPriceLineRef = useRef<IPriceLine | null>(null);
  const loadedResetKeyRef = useRef<string | null>(null);
  const hasFullDataRef = useRef(false);
  const centeredResetKeyRef = useRef<string | null>(null);
  const appliedSymbolResetTokenRef = useRef<number | null>(null);
  const appliedHardResetTokenRef = useRef<number | null>(hardResetToken);
  const priceScaleManuallyAdjustedRef = useRef(false);
  const overlayRecalculateFrameRef = useRef<number | null>(null);
  const chartPointerActiveRef = useRef(false);
  const priceScaleWidthRef = useRef(64);
  const [localHardResetToken, setLocalHardResetToken] = useState(0);
  const [localRecenterToken, setLocalRecenterToken] = useState(0);
  const [overlays, setOverlays] = useState<ZoneOverlay[]>([]);
  const [tradeLineOverlays, setTradeLineOverlays] = useState<TradeLineOverlay[]>([]);
  const [tradeMarkerOverlays, setTradeMarkerOverlays] = useState<TradeMarkerOverlay[]>([]);
  const [priceAlertOverlays, setPriceAlertOverlays] = useState<PriceAlertOverlay[]>([]);
  const [draggingAlertId, setDraggingAlertId] = useState<string | null>(null);
  const [selectedAlertId, setSelectedAlertId] = useState<string | null>(null);
  const [draftAlertPrices, setDraftAlertPrices] = useState<Record<string, number>>({});
  const [alertVisualStyles, setAlertVisualStyles] = useState<Record<string, PriceAlertVisualStyle>>(() => loadAlertVisualStyles());
  const [draggingTpLineId, setDraggingTpLineId] = useState<string | null>(null);
  const [draftTradeLinePrices, setDraftTradeLinePrices] = useState<Record<string, number>>({});
  const [drawingShapes, setDrawingShapes] = useState<DrawingShape[]>([]);
  const draftDrawingPayloadsRef = useRef<Record<string, Record<string, unknown>>>({});
  const draggingDrawingShapeRef = useRef<DrawingShape | null>(null);
  const [draggingDrawingId, setDraggingDrawingId] = useState<string | null>(null);
  const [styleEditorTarget, setStyleEditorTarget] = useState<{ kind: "drawing" | "alert"; id: string } | null>(null);
  const [pendingPoint, setPendingPoint] = useState<DrawingPoint | null>(null);
  const [pendingCoordinate, setPendingCoordinate] = useState<DrawingCoordinate | null>(null);
  function getPreferredVisibleBars(candleCount: number): number {
    const container = containerRef.current;
    const containerWidth = container?.clientWidth ?? 360;

    return calculateVisibleBarsForWidth(containerWidth, timeframe, candleCount);
  }
  const suppressNextChartPointRef = useRef(false);
  const effectiveHardResetToken = hardResetToken + localHardResetToken;
  const effectiveRecenterToken = recenterToken + localRecenterToken;

  function syncPriceScaleWidth(container: HTMLDivElement): number {
    const chart = chartRef.current;
    const measuredWidth = chart?.priceScale("right").width() ?? priceScaleWidthRef.current;
    const extraWidth = cssPixelValue(container, "--chart-price-scale-extra", 0);
    const nextWidth = Math.max(0, Math.round(measuredWidth + extraWidth));
    priceScaleWidthRef.current = nextWidth;
    container.style.setProperty("--chart-price-scale-width", `${nextWidth}px`);
    return nextWidth;
  }

  function chartPaneWidth(container: HTMLDivElement): number {
    return Math.max(0, container.clientWidth - priceScaleWidthRef.current);
  }

  useEffect(() => {
    saveAlertVisualStyles(alertVisualStyles);
  }, [alertVisualStyles]);

  useEffect(() => {
    if (selectedDrawingId) {
      setSelectedAlertId(null);
    }
  }, [selectedDrawingId]);

  useEffect(() => {
    if (selectedAlertId && !priceAlerts.some((alert) => alert.id === selectedAlertId)) {
      setSelectedAlertId(null);
    }
  }, [priceAlerts, selectedAlertId]);

  useEffect(() => {
    if (!styleEditorTarget) {
      return;
    }

    if (styleEditorTarget.kind === "drawing" && !drawings.some((drawing) => drawing.id === styleEditorTarget.id)) {
      setStyleEditorTarget(null);
    }

    if (styleEditorTarget.kind === "alert" && !priceAlerts.some((alert) => alert.id === styleEditorTarget.id)) {
      setStyleEditorTarget(null);
    }
  }, [drawings, priceAlerts, styleEditorTarget]);

  useEffect(() => {
    setStyleEditorTarget((current) => {
      if (!current) {
        return current;
      }

      if (current.kind === "drawing" && current.id !== selectedDrawingId) {
        return null;
      }

      if (current.kind === "alert" && current.id !== selectedAlertId) {
        return null;
      }

      return current;
    });
  }, [selectedAlertId, selectedDrawingId]);

  const recalculateOverlays = useCallback(() => {
    const chart = chartRef.current;
    const series = seriesRef.current;
    const container = containerRef.current;

    if (!chart || !series || !container) {
      setOverlays([]);
      setDrawingShapes([]);
      setTradeLineOverlays([]);
      setTradeMarkerOverlays([]);
      setPriceAlertOverlays([]);
      return;
    }

    syncPriceScaleWidth(container);
    const containerWidth = chartPaneWidth(container);
    const containerHeight = container.clientHeight;
    const sortedCandles = normalizeCandlesForChart(candles);
    const lastCandleTime = lastRealCandleTime(sortedCandles);
    const timeframeSeconds = timeframeToSeconds(timeframe);
    const nowMs = Date.now();

    const next = noTradeZones
      .filter(
        (zone) =>
          isNewsZoneVisibleNow(zone, nowMs) &&
          (showFutureNewsZones || lastCandleTime === null || newsZoneStart(zone) <= lastCandleTime)
      )
      .map((zone) => {
        const start = snapFutureChartTime(newsZoneStart(zone), lastCandleTime, timeframeSeconds, "floor") as UTCTimestamp;
        const end = snapFutureChartTime(newsZoneEnd(zone), lastCandleTime, timeframeSeconds, "ceil") as UTCTimestamp;

        const startCoordinate = chart.timeScale().timeToCoordinate(start);
        const endCoordinate = chart.timeScale().timeToCoordinate(end);

        if (startCoordinate === null && endCoordinate === null) {
          return null;
        }

        const left = Math.max(0, startCoordinate ?? 0);
        const right = Math.min(containerWidth, endCoordinate ?? containerWidth);

        if (right <= left) {
          return null;
        }

        return {
          id: zone.id,
          left,
          width: Math.max(2, right - left),
          zone
        };
      })
      .filter((value): value is ZoneOverlay => value !== null);

    setOverlays(next);

    const shapes = drawings
      .map((drawing): DrawingShape | null => {
        const color = styleValue(drawing.style, "color", "#f5c542");
        const lineWidth = numericStyleValue(drawing.style, "lineWidth", 2);
        const lineStyle = lineStyleValue(drawing.style);
        const glow = clampedNumericStyleValue(drawing.style, "glow", 0, 0, 18);
        const opacity = clampedNumericStyleValue(drawing.style, "opacity", drawing.drawing_type === "manual_zone" ? 0.16 : 0.13, 0, 1);
        const fallbackBackgroundColor = styleValue(drawing.style, "backgroundColor", "rgba(245,197,66,0.15)");
        const backgroundColor = drawing.drawing_type === "rectangle" || drawing.drawing_type === "manual_zone" ? hexToRgba(color, opacity) : fallbackBackgroundColor;
        const textColor = styleValue(drawing.style, "textColor", "#edf2ef");
        const fontSize = clampedNumericStyleValue(drawing.style, "fontSize", 14, 8, 48);
        const label = drawingLabel(drawing);

        const base = {
          id: drawing.id,
          drawing,
          color,
          lineWidth,
          lineStyle,
          glow,
          label
        };

        const payload = draftDrawingPayloadsRef.current[drawing.id] ?? drawing.payload;

        if (drawing.drawing_type === "horizontal_line") {
          const price = numberValue(payload.price);
          const y = price === null ? null : series.priceToCoordinate(price);

          return y === null
            ? null
            : ({
                ...base,
                kind: "horizontal_line",
                x1: 0,
                x2: containerWidth,
                y
              } satisfies DrawingShape);
        }

        if (drawing.drawing_type === "vertical_line") {
          const time = numberValue(payload.time);

          if (time === null) {
            return null;
          }

          const x = timeToChartX(chart, sortedCandles, time, Number.NaN);

          return Number.isNaN(x)
            ? null
            : ({
                ...base,
                kind: "vertical_line",
                x,
                y1: 0,
                y2: containerHeight
              } satisfies DrawingShape);
        }

        if (drawing.drawing_type === "trend_line") {
          const points = Array.isArray(payload.points) ? payload.points : [];

          if (
            points.length !== 2 ||
            typeof points[0] !== "object" ||
            points[0] === null ||
            typeof points[1] !== "object" ||
            points[1] === null
          ) {
            return null;
          }

          const first = points[0] as Record<string, unknown>;
          const second = points[1] as Record<string, unknown>;

          const time1 = numberValue(first.time);
          const time2 = numberValue(second.time);
          const price1 = numberValue(first.price);
          const price2 = numberValue(second.price);

          if (time1 === null || time2 === null || price1 === null || price2 === null) {
            return null;
          }

          const x1 = timeToChartX(chart, sortedCandles, time1, Number.NaN);
          const x2 = timeToChartX(chart, sortedCandles, time2, Number.NaN);
          const y1 = series.priceToCoordinate(price1);
          const y2 = series.priceToCoordinate(price2);

          return Number.isNaN(x1) || Number.isNaN(x2) || y1 === null || y2 === null
            ? null
            : ({
                ...base,
                kind: "trend_line",
                x1,
                y1,
                x2,
                y2
              } satisfies DrawingShape);
        }

        if (drawing.drawing_type === "rectangle") {
          const time1 = numberValue(payload.time1);
          const time2 = numberValue(payload.time2);
          const price1 = numberValue(payload.price1);
          const price2 = numberValue(payload.price2);

          if (time1 === null || time2 === null || price1 === null || price2 === null) {
            return null;
          }

          const x1 = timeToChartX(chart, sortedCandles, time1, 0);
          const x2 = timeToChartX(chart, sortedCandles, time2, containerWidth);
          const y1 = series.priceToCoordinate(price1);
          const y2 = series.priceToCoordinate(price2);

          if (y1 === null || y2 === null) {
            return null;
          }

          return {
            ...base,
            kind: "rectangle",
            x: Math.min(x1, x2),
            y: Math.min(y1, y2),
            width: Math.max(2, Math.abs(x2 - x1)),
            height: Math.max(2, Math.abs(y2 - y1)),
            backgroundColor
          } satisfies DrawingShape;
        }

        if (drawing.drawing_type === "manual_zone") {
          const time1 = numberValue(payload.time1);
          const time2 = numberValue(payload.time2);
          const priceMin = numberValue(payload.price_min);
          const priceMax = numberValue(payload.price_max);

          if (time1 === null || priceMin === null || priceMax === null) {
            return null;
          }

          const x1 = timeToChartX(chart, sortedCandles, time1, 0);
          const x2 = time2 === null ? containerWidth : timeToChartX(chart, sortedCandles, time2, containerWidth);
          const y1 = series.priceToCoordinate(priceMin);
          const y2 = series.priceToCoordinate(priceMax);

          if (y1 === null || y2 === null) {
            return null;
          }

          return {
            ...base,
            kind: "manual_zone",
            x: Math.min(x1, x2),
            y: Math.min(y1, y2),
            width: Math.max(2, Math.abs(x2 - x1)),
            height: Math.max(2, Math.abs(y2 - y1)),
            backgroundColor,
            direction: typeof payload.direction === "string" ? payload.direction : "NEUTRAL"
          } satisfies DrawingShape;
        }

        if (drawing.drawing_type === "text") {
          const time = numberValue(payload.time);
          const price = numberValue(payload.price);
          const text = typeof payload.text === "string" ? payload.text : drawingLabel(drawing);

          if (time === null || price === null) {
            return null;
          }

          const x = timeToChartX(chart, sortedCandles, time, Number.NaN);
          const y = series.priceToCoordinate(price);

          return Number.isNaN(x) || y === null
            ? null
            : ({
                ...base,
                kind: "text",
                x,
                y,
                text,
                textColor,
                fontSize
              } satisfies DrawingShape);
        }

        return null;
      })
      .filter((shape): shape is DrawingShape => shape !== null);

    const draggingShape = draggingDrawingShapeRef.current;
    setDrawingShapes(
      draggingShape
        ? shapes.map((shape) => (shape.id === draggingShape.id ? draggingShape : shape))
        : shapes
    );

    setTradeLineOverlays(
      tradeLines
        .filter((line) => (line.tone === "entry" || line.tone === "tp") && Number.isFinite(line.price))
        .map((line): TradeLineOverlay | null => {
          const price = draftTradeLinePrices[line.id] ?? line.price;
          const y = series.priceToCoordinate(price);

          return y === null ? null : { ...line, price, y, label: tradeLineLabel(line, price) };
        })
        .filter((line): line is TradeLineOverlay => line !== null)
    );

    setTradeMarkerOverlays([]);

    setPriceAlertOverlays(
      priceAlerts
        .filter((alert) => alert.status === "ACTIVE")
        .map((alert): PriceAlertOverlay | null => {
          const targetPrice = draftAlertPrices[alert.id] ?? alert.target_price;
          const y = series.priceToCoordinate(targetPrice);
          return y === null ? null : { alert, y, targetPrice };
        })
        .filter((line): line is PriceAlertOverlay => line !== null)
    );

    if (pendingPoint) {
      const x = timeToChartX(chart, sortedCandles, pendingPoint.time, Number.NaN);
      const y = series.priceToCoordinate(pendingPoint.price);
      setPendingCoordinate(Number.isNaN(x) || y === null ? null : { x, y });
    } else {
      setPendingCoordinate(null);
    }
 }, [
  candles,
  drawings,
  draftAlertPrices,
  draftTradeLinePrices,
  noTradeZones,
  pendingPoint,
  priceAlerts,
  showFutureNewsZones,
  timeframe,
  tradeLines,
  tradeMarkers
]);

  function scheduleOverlayRecalculate() {
    if (overlayRecalculateFrameRef.current !== null) {
      return;
    }

    overlayRecalculateFrameRef.current = window.requestAnimationFrame(() => {
      overlayRecalculateFrameRef.current = null;
      recalculateOverlays();
    });
  }

  useEffect(() => {
    setDraftAlertPrices((current) => {
      let changed = false;
      const next = { ...current };

      for (const [alertId, price] of Object.entries(current)) {
        const alert = priceAlerts.find((item) => item.id === alertId);

        if (!alert || Math.abs(alert.target_price - price) < 0.00001) {
          delete next[alertId];
          changed = true;
        }
      }

      return changed ? next : current;
    });
  }, [priceAlerts]);

  useEffect(() => {
    setDraftTradeLinePrices((current) => {
      let changed = false;
      const next = { ...current };

      for (const [lineId, price] of Object.entries(current)) {
        const line = tradeLines.find((item) => item.id === lineId);

        if (!line || Math.abs(line.price - price) < 0.00001) {
          delete next[lineId];
          changed = true;
        }
      }

      return changed ? next : current;
    });
  }, [tradeLines]);

  useEffect(() => {
    let changed = false;
    const nextDrafts = { ...draftDrawingPayloadsRef.current };

    for (const [drawingId, payload] of Object.entries(draftDrawingPayloadsRef.current)) {
      const drawing = drawings.find((item) => item.id === drawingId);

      if (!drawing || payloadsEqual(drawing.payload, payload)) {
        delete nextDrafts[drawingId];
        changed = true;

        if (draggingDrawingShapeRef.current?.id === drawingId) {
          draggingDrawingShapeRef.current = null;
        }
      }
    }

    if (changed) {
      draftDrawingPayloadsRef.current = nextDrafts;
      scheduleOverlayRecalculate();
    }
  }, [drawings]);

  useEffect(() => {
    const intervalId = window.setInterval(recalculateOverlays, 30_000);
    return () => window.clearInterval(intervalId);
  }, [recalculateOverlays]);

  useEffect(() => {
    recalculateOverlays();
  }, [priceAlerts, recalculateOverlays]);

  useEffect(() => {
    function handleChartTimeSettingsChanged() {
      const chart = chartRef.current;

      if (!chart) {
        return;
      }

      chart.applyOptions({
        localization: {
          locale: "es-ES",
          timeFormatter: formatChartCrosshairTime
        },
        timeScale: {
          tickMarkFormatter: formatChartTickMark
        }
      });
      window.setTimeout(recalculateOverlays, 0);
    }

    window.addEventListener(chartTimeSettingsChangedEvent, handleChartTimeSettingsChanged);
    return () => window.removeEventListener(chartTimeSettingsChangedEvent, handleChartTimeSettingsChanged);
  }, [recalculateOverlays]);

  useEffect(() => {
    setPendingPoint(null);
    setPendingCoordinate(null);
  }, [drawingTool, symbol, timeframe]);

  useEffect(() => {
    if (!containerRef.current) {
      return;
    }

    const chart = createChart(containerRef.current, {
      autoSize: true,
      layout: {
        background: { color: "#000000" },
        textColor: "#f2f4f5"
      },
      localization: {
        locale: "es-ES",
        timeFormatter: formatChartCrosshairTime
      },
      grid: {
        vertLines: { color: "#24303a", style: LineStyle.Dashed },
        horzLines: { color: "#24303a", style: LineStyle.Dashed }
      },
      rightPriceScale: {
        borderColor: "#3a434a",
        scaleMargins: {
          top: 0.18,
          bottom: 0.18
        }
      },
      timeScale: {
        borderColor: "#293033",
        barSpacing: initialCandleBarSpacing,
        minBarSpacing: 6,
        timeVisible: true,
        secondsVisible: false,
        tickMarkFormatter: formatChartTickMark
      },
      handleScale: {
        axisPressedMouseMove: {
          time: true,
          price: true
        },
        mouseWheel: true,
        pinch: true
      },
      handleScroll: {
        horzTouchDrag: true,
        vertTouchDrag: true,
        mouseWheel: true,
        pressedMouseMove: true
      },
      crosshair: {
        mode: 1
      }
    });

    const series = chart.addCandlestickSeries({
      upColor: "#20c9bd",
      downColor: "#f45d5d",
      borderUpColor: "#20c9bd",
      borderDownColor: "#f45d5d",
      wickUpColor: "#20c9bd",
      wickDownColor: "#f45d5d",
      lastValueVisible: false,
      priceLineVisible: false
    });
    const futurePaddingSeries = chart.addLineSeries({
      color: "rgba(0,0,0,0)",
      lineWidth: 1,
      lastValueVisible: false,
      priceLineVisible: false,
      crosshairMarkerVisible: false
    });

    chartRef.current = chart;
    seriesRef.current = series;
    futurePaddingSeriesRef.current = futurePaddingSeries;

    return () => {
      if (overlayRecalculateFrameRef.current !== null) {
        window.cancelAnimationFrame(overlayRecalculateFrameRef.current);
        overlayRecalculateFrameRef.current = null;
      }
      lineSeriesRef.current.clear();
      futurePaddingSeriesRef.current = null;
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  useEffect(() => {
  const chart = chartRef.current;
  const series = seriesRef.current;

  if (!chart || !series) {
    return;
  }

  if (appliedHardResetTokenRef.current === effectiveHardResetToken) {
    return;
  }

  appliedHardResetTokenRef.current = effectiveHardResetToken;

  const sortedCandles = normalizeCandlesForChart(candles);
  priceScaleManuallyAdjustedRef.current = false;
  hardResetChartView(
    chart,
    series,
    sortedCandles.length,
    timeframe,
    getPreferredVisibleBars(sortedCandles.length)
  );
  centeredResetKeyRef.current = resetKey ?? `${symbol}:${timeframe}`;
  appliedSymbolResetTokenRef.current = symbolResetToken;

  window.setTimeout(recalculateOverlays, 0);
}, [
  effectiveHardResetToken,
  candles,
  timeframe,
  resetKey,
  symbol,
  symbolResetToken,
  recalculateOverlays
]);

  useEffect(() => {
  const series = seriesRef.current;
  const chart = chartRef.current;

  if (!series || !chart) {
    return;
  }
  
  const sortedCandles = normalizeCandlesForChart(candles);
  const nextResetKey = resetKey ?? `${symbol}:${timeframe}`;
  const shouldReset = loadedResetKeyRef.current !== nextResetKey;
  const shouldApplySymbolReset = appliedSymbolResetTokenRef.current !== symbolResetToken;

  const firstCandleTime = sortedCandles[0] ? timeToNumber(sortedCandles[0].time) : null;
  const lastCandleTime = sortedCandles[sortedCandles.length - 1]
    ? timeToNumber(sortedCandles[sortedCandles.length - 1].time)
    : null;

  if (shouldReset) {
  loadedResetKeyRef.current = nextResetKey;
  hasFullDataRef.current = false;
  centeredResetKeyRef.current = null;

  series.setData([]);
  series.setMarkers([]);

  /*
   * Muy importante: eliminar líneas BID/ASK del activo anterior.
   * Si no, el eje vertical puede quedarse escalado al precio anterior.
   */
  if (bidPriceLineRef.current) {
    series.removePriceLine(bidPriceLineRef.current);
    bidPriceLineRef.current = null;
  }

  if (askPriceLineRef.current) {
    series.removePriceLine(askPriceLineRef.current);
    askPriceLineRef.current = null;
  }

  lineSeriesRef.current.forEach((lineSeries) => {
    lineSeries.setData([]);
  });

  setOverlays([]);
  setDrawingShapes([]);
  setTradeLineOverlays([]);
  setPriceAlertOverlays([]);
  setTradeMarkerOverlays([]);
  priceScaleManuallyAdjustedRef.current = false;
  resetPriceScale(chart, series);
}

  if (sortedCandles.length === 0) {
    series.setData([]);
    series.setMarkers([]);
    hasFullDataRef.current = false;
    window.setTimeout(recalculateOverlays, 0);
    return;
  }

  /*
   * Si estamos cargando histórico, no queremos que una vela suelta recibida
   * por WebSocket inicialice el gráfico como si fuera todo el histórico.
   */
  if (loadingCandles && sortedCandles.length <= 2 && !hasFullDataRef.current) {
    series.setData(sortedCandles);
    series.setMarkers([]);
    window.setTimeout(recalculateOverlays, 0);
    return;
  }

  /*
   * Cuando cambia símbolo/timeframe, o cuando todavía no tenemos histórico completo,
   * SIEMPRE usamos setData. update() solo se usa cuando el contexto ya está estable.
   */
if (shouldReset || !hasFullDataRef.current) {
  series.setData(sortedCandles);
  series.setMarkers([]);
  hasFullDataRef.current = true;

  if (shouldApplySymbolReset) {
    priceScaleManuallyAdjustedRef.current = false;
    centerSymbolChange(
      chart,
      series,
      sortedCandles.length,
      timeframe,
      getPreferredVisibleBars(sortedCandles.length)
    );
    appliedSymbolResetTokenRef.current = symbolResetToken;
    centeredResetKeyRef.current = nextResetKey;
  } else if (centeredResetKeyRef.current !== nextResetKey) {
    if (sortedCandles.length > 2) {
      centerRecentBars(
        chart,
        sortedCandles.length,
        timeframe,
        getPreferredVisibleBars(sortedCandles.length)
      );
    } else {
      centerRecentBars(
        chart,
        sortedCandles.length,
        timeframe,
        getPreferredVisibleBars(sortedCandles.length)
      );
    }

    centeredResetKeyRef.current = nextResetKey;
  }

  window.setTimeout(recalculateOverlays, 0);
  return;
}

  /*
   * Contexto estable: ahora sí podemos actualizar solo la última vela.
   */
  const lastCandle = sortedCandles[sortedCandles.length - 1];
  series.update(lastCandle);
  series.setMarkers([]);

  if (autoFollowEnabled) {
    scrollToLatestRealCandle(
      chart,
      sortedCandles.length,
      timeframe,
      getPreferredVisibleBars(sortedCandles.length)
    );
  }

  /*
  * Si el usuario ajustó manualmente el eje vertical, mantenemos desactivado
  * el autoscale aunque entren nuevas velas/ticks.
  */
  if (priceScaleManuallyAdjustedRef.current) {
    disablePriceAutoScale(chart, series);
  }

  window.setTimeout(recalculateOverlays, 0);
}, [
  autoFollowEnabled,
  candles,
  loadingCandles,
  recalculateOverlays,
  resetKey,
  symbol,
  timeframe,
  tradeMarkers
]);

  useEffect(() => {
    const chart = chartRef.current;
    const futurePaddingSeries = futurePaddingSeriesRef.current;

    if (!chart || !futurePaddingSeries) {
      return;
    }

    const visibleRange = chart.timeScale().getVisibleLogicalRange();
    const sortedCandles = normalizeCandlesForChart(candles);
    const paddingData =
      showFutureNewsZones && autoExtendToFutureNews
        ? buildFuturePaddingData(sortedCandles, noTradeZones, timeframe)
        : [];

    /*
     * Serie invisible. Solo extiende eje temporal para overlays futuros.
     * No crea candles. No alimenta indicadores.
     */
    futurePaddingSeries.setData(paddingData);

    if (visibleRange) {
      chart.timeScale().setVisibleLogicalRange(visibleRange);
    }

    window.requestAnimationFrame(() => {
      if (visibleRange) {
        chart.timeScale().setVisibleLogicalRange(visibleRange);
      }

      recalculateOverlays();
    });
  }, [
    autoExtendToFutureNews,
    candles,
    noTradeZones,
    recalculateOverlays,
    showFutureNewsZones,
    timeframe
  ]);


  useEffect(() => {
  const chart = chartRef.current;

  if (!chart || candles.length === 0) {
    return;
  }

  const sortedCandles = normalizeCandlesForChart(candles);

  if (sortedCandles.length === 0) {
    return;
  }

  if (appliedSymbolResetTokenRef.current === symbolResetToken) {
    return;
  }

  const series = seriesRef.current;

if (!series) {
  return;
}
  priceScaleManuallyAdjustedRef.current = false;
  centerSymbolChange(
    chart,
    series,
    sortedCandles.length,
    timeframe,
    getPreferredVisibleBars(sortedCandles.length)
  );
  appliedSymbolResetTokenRef.current = symbolResetToken;
  centeredResetKeyRef.current = resetKey ?? `${symbol}:${timeframe}`;

  window.setTimeout(recalculateOverlays, 0);
}, [candles, recalculateOverlays, resetKey, symbol, symbolResetToken, timeframe]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || candles.length === 0) {
      return;
    }
  centerRecentBars(
      chart,
      candles.length,
      timeframe,
      getPreferredVisibleBars(candles.length)
    );
    window.setTimeout(recalculateOverlays, 0);
  }, [effectiveRecenterToken]);

  useEffect(() => {
  const series = seriesRef.current;

  if (!series) {
    return;
  }

  if (bidPriceLineRef.current) {
    series.removePriceLine(bidPriceLineRef.current);
    bidPriceLineRef.current = null;
  }

  if (askPriceLineRef.current) {
    series.removePriceLine(askPriceLineRef.current);
    askPriceLineRef.current = null;
  }

  /*
   * Mientras se está cargando/cambiando el activo, no añadimos BID/ASK.
   * Pero aquí NO reseteamos la escala vertical, porque este efecto también
   * se ejecuta con cada tick y podría deshacer el zoom vertical manual.
   */
  if (loadingCandles) {
    return;
  }

  if (showBidLine && typeof bidPrice === "number" && Number.isFinite(bidPrice)) {
    bidPriceLineRef.current = series.createPriceLine({
      price: bidPrice,
      color: "#2be0d0",
      lineWidth: 1,
      lineStyle: LineStyle.Solid,
      axisLabelVisible: true,
      title: "BID"
    });
  }

  if (showAskLine && typeof askPrice === "number" && Number.isFinite(askPrice)) {
    askPriceLineRef.current = series.createPriceLine({
      price: askPrice,
      color: "#f45d5d",
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      axisLabelVisible: true,
      title: "ASK"
    });
  }
}, [askPrice, bidPrice, loadingCandles, showAskLine, showBidLine]);

  useEffect(() => {
    const chart = chartRef.current;

    if (!chart) {
      return;
    }

    const activeNames = new Set(indicatorLines.map((line) => line.name));

    for (const [name, series] of lineSeriesRef.current) {
      if (!activeNames.has(name)) {
        chart.removeSeries(series);
        lineSeriesRef.current.delete(name);
      }
    }

    for (const line of indicatorLines) {
      let lineSeries = lineSeriesRef.current.get(line.name);

      if (!lineSeries) {
        lineSeries = chart.addLineSeries({
          color: line.style.color ?? "#d6b25e",
          lineWidth: (line.style.lineWidth ?? 2) as 1 | 2 | 3 | 4
        });

        lineSeriesRef.current.set(line.name, lineSeries);
      }

      const data: LineData[] = sortLineDataByTimeAsc(
        line.points.map((point) => ({
          time: point.time as UTCTimestamp,
          value: point.value
        }))
      );

      lineSeries.setData(data);
    }
  }, [indicatorLines]);

  function chartPointFromClient(clientX: number, clientY: number, clampToChart = false): DrawingPoint | null {
    const chart = chartRef.current;
    const series = seriesRef.current;
    const container = containerRef.current;

    if (!chart || !series || !container) {
      return null;
    }

    const bounds = container.getBoundingClientRect();
    const rawX = clientX - bounds.left;
    const rawY = clientY - bounds.top;
    const paneWidth = chartPaneWidth(container);
    const x = clampToChart ? clampNumber(rawX, 0, paneWidth) : rawX;
    const y = clampToChart ? clampNumber(rawY, 0, bounds.height) : rawY;

    const time = chartTimeToUnix(chart.timeScale().coordinateToTime(x));
    const price = series.coordinateToPrice(y);

    if (time === null || price === null) {
      return null;
    }

    return { time, price };
  }

  function handleChartPoint(point: DrawingPoint) {
    if (alertToolActive && onCreatePriceAlert) {
      onCreatePriceAlert(Number(point.price.toFixed(5)));
      return;
    }

    if (drawingTool === "select" || !onCreateDrawing) {
      return;
    }

    if (drawingTool === "horizontal_line") {
      onCreateDrawing(
        createBaseDrawing(
          symbol,
          timeframe,
          "horizontal_line",
          {
            price: Number(point.price.toFixed(5)),
            label: "Horizontal"
          },
          "Horizontal line"
        )
      );
      return;
    }

    if (drawingTool === "vertical_line") {
      onCreateDrawing(
        createBaseDrawing(
          symbol,
          timeframe,
          "vertical_line",
          {
            time: point.time,
            label: "Vertical"
          },
          "Vertical line"
        )
      );
      return;
    }

    if (drawingTool === "text") {
      const text = window.prompt("Texto del dibujo", "Nota");

      if (text?.trim()) {
        onCreateDrawing(
          createBaseDrawing(
            symbol,
            timeframe,
            "text",
            {
              time: point.time,
              price: Number(point.price.toFixed(5)),
              text: text.trim()
            },
            "Text"
          )
        );
      }

      return;
    }

    if (!pendingPoint) {
      setPendingPoint(point);
      return;
    }

    if (drawingTool === "trend_line") {
      onCreateDrawing(
        createBaseDrawing(
          symbol,
          timeframe,
          "trend_line",
          {
            points: [
              {
                time: pendingPoint.time,
                price: Number(pendingPoint.price.toFixed(5))
              },
              {
                time: point.time,
                price: Number(point.price.toFixed(5))
              }
            ],
            label: "Trend"
          },
          "Trend line"
        )
      );
    }

    if (drawingTool === "rectangle") {
      const timeSpan = drawingTimeSpanFromPoints(pendingPoint.time, point.time, timeframe);
      onCreateDrawing(
        createBaseDrawing(
          symbol,
          timeframe,
          "rectangle",
          {
            time1: timeSpan.time1,
            time2: timeSpan.time2,
            price1: Number(Math.min(pendingPoint.price, point.price).toFixed(5)),
            price2: Number(Math.max(pendingPoint.price, point.price).toFixed(5)),
            label: "Zone"
          },
          "Rectangle"
        )
      );
    }

    if (drawingTool === "manual_zone") {
      const timeSpan = drawingTimeSpanFromPoints(pendingPoint.time, point.time, timeframe);
      onCreateDrawing(
        createBaseDrawing(
          symbol,
          timeframe,
          "manual_zone",
          {
            time1: timeSpan.time1,
            time2: timeSpan.time2,
            price_min: Number(Math.min(pendingPoint.price, point.price).toFixed(5)),
            price_max: Number(Math.max(pendingPoint.price, point.price).toFixed(5)),
            direction: "NEUTRAL",
            label: "Manual zone",
            rules: {},
            metadata: {}
          },
          "Manual zone"
        )
      );
    }

    setPendingPoint(null);
    setPendingCoordinate(null);
  }

  function handleChartPointerUp(event: PointerEvent<HTMLDivElement>) {
    if (suppressNextChartPointRef.current) {
      suppressNextChartPointRef.current = false;
      return;
    }
    if (!alertToolActive && drawingTool === "select") {
      onSelectDrawing?.(null);
      setSelectedAlertId(null);
      setStyleEditorTarget(null);
      return;
    }
    if (draggingAlertId || (!alertToolActive && drawingTool === "select")) {
      return;
    }
    const point = chartPointFromClient(event.clientX, event.clientY);
    if (!point) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    handleChartPoint(point);
  }

  function priceFromPointer(event: PointerEvent | globalThis.PointerEvent): number | null {
    const series = seriesRef.current;
    const container = containerRef.current;
    if (!series || !container) {
      return null;
    }
    const bounds = container.getBoundingClientRect();
    const y = event.clientY - bounds.top;
    const price = series.coordinateToPrice(y);
    return price === null ? null : Number(price.toFixed(5));
  }

  function chartTimeFromX(x: number, fallback: number | null = null): number | null {
    const chart = chartRef.current;
    const container = containerRef.current;

    if (!chart || !container) {
      return fallback;
    }

    const sortedCandles = normalizeCandlesForChart(candles);
    return chartXToTime(chart, sortedCandles, clampNumber(x, 0, chartPaneWidth(container)), fallback);
  }

  function chartPriceFromY(y: number, fallback: number | null = null): number | null {
    const series = seriesRef.current;
    const container = containerRef.current;

    if (!series || !container) {
      return fallback;
    }

    const price = series.coordinateToPrice(clampNumber(y, 0, container.clientHeight));
    return price === null ? fallback : Number(price.toFixed(5));
  }

  function moveDrawingShape(shape: DrawingShape, dx: number, dy: number, action: DrawingDragAction): DrawingShape {
    if (shape.kind === "horizontal_line") {
      return { ...shape, y: shape.y + dy };
    }

    if (shape.kind === "vertical_line") {
      return { ...shape, x: shape.x + dx };
    }

    if (shape.kind === "text") {
      return { ...shape, x: shape.x + dx, y: shape.y + dy };
    }

    if (shape.kind === "trend_line") {
      if (action === "p1") {
        return { ...shape, x1: shape.x1 + dx, y1: shape.y1 + dy };
      }

      if (action === "p2") {
        return { ...shape, x2: shape.x2 + dx, y2: shape.y2 + dy };
      }

      return {
        ...shape,
        x1: shape.x1 + dx,
        y1: shape.y1 + dy,
        x2: shape.x2 + dx,
        y2: shape.y2 + dy
      };
    }

    if (shape.kind === "rectangle" || shape.kind === "manual_zone") {
      if (action === "move") {
        return { ...shape, x: shape.x + dx, y: shape.y + dy };
      }

      let left = shape.x;
      let right = shape.x + shape.width;
      let top = shape.y;
      let bottom = shape.y + shape.height;

      if (action.includes("left")) left += dx;
      if (action.includes("right")) right += dx;
      if (action.includes("top")) top += dy;
      if (action.includes("bottom")) bottom += dy;

      return {
        ...shape,
        x: Math.min(left, right),
        y: Math.min(top, bottom),
        width: Math.max(2, Math.abs(right - left)),
        height: Math.max(2, Math.abs(bottom - top))
      };
    }

    return shape;
  }

  function drawingPayloadFromShape(
    drawing: ChartDrawingRead,
    payload: Record<string, unknown>,
    shape: DrawingShape
  ): Record<string, unknown> | null {
    if (drawing.drawing_type === "horizontal_line" && shape.kind === "horizontal_line") {
      const price = chartPriceFromY(shape.y, numberValue(payload.price));
      return price === null ? null : { ...payload, price };
    }

    if (drawing.drawing_type === "vertical_line" && shape.kind === "vertical_line") {
      const time = chartTimeFromX(shape.x, numberValue(payload.time));
      return time === null ? null : { ...payload, time };
    }

    if (drawing.drawing_type === "text" && shape.kind === "text") {
      const time = chartTimeFromX(shape.x, numberValue(payload.time));
      const price = chartPriceFromY(shape.y, numberValue(payload.price));
      return time === null || price === null ? null : { ...payload, time, price };
    }

    if (drawing.drawing_type === "trend_line" && shape.kind === "trend_line") {
      const points = Array.isArray(payload.points) ? payload.points : [];
      const first = typeof points[0] === "object" && points[0] !== null ? (points[0] as Record<string, unknown>) : {};
      const second = typeof points[1] === "object" && points[1] !== null ? (points[1] as Record<string, unknown>) : {};
      const firstTime = chartTimeFromX(shape.x1, numberValue(first.time));
      const firstPrice = chartPriceFromY(shape.y1, numberValue(first.price));
      const secondTime = chartTimeFromX(shape.x2, numberValue(second.time));
      const secondPrice = chartPriceFromY(shape.y2, numberValue(second.price));

      if (firstTime === null || firstPrice === null || secondTime === null || secondPrice === null) {
        return null;
      }

      return {
        ...payload,
        points: [
          { ...first, time: firstTime, price: firstPrice },
          { ...second, time: secondTime, price: secondPrice }
        ]
      };
    }

    if (
      (drawing.drawing_type === "rectangle" && shape.kind === "rectangle") ||
      (drawing.drawing_type === "manual_zone" && shape.kind === "manual_zone")
    ) {
      const isManualZone = drawing.drawing_type === "manual_zone";
      const time1Key = "time1";
      const time2Key = "time2";
      const lowKey = isManualZone ? "price_min" : "price1";
      const highKey = isManualZone ? "price_max" : "price2";
      const left = shape.x;
      const right = shape.x + shape.width;
      const top = shape.y;
      const bottom = shape.y + shape.height;
      const timeLeft = chartTimeFromX(left, numberValue(payload[time1Key]));
      const timeRight = chartTimeFromX(right, numberValue(payload[time2Key]));
      const priceTop = chartPriceFromY(top, numberValue(payload[highKey]));
      const priceBottom = chartPriceFromY(bottom, numberValue(payload[lowKey]));

      if (timeLeft === null || timeRight === null || priceTop === null || priceBottom === null) {
        return null;
      }

      return {
        ...payload,
        [time1Key]: Math.floor(Math.min(timeLeft, timeRight)),
        [time2Key]: Math.max(
          Math.floor(Math.max(timeLeft, timeRight)),
          Math.floor(Math.min(timeLeft, timeRight)) + 1
        ),
        [lowKey]: Number(Math.min(priceTop, priceBottom).toFixed(5)),
        [highKey]: Number(Math.max(priceTop, priceBottom).toFixed(5))
      };
    }

    return null;
  }

  function handleDrawingDragStart(shape: DrawingShape) {
    if (!onUpdateDrawing || shape.drawing.locked) {
      return;
    }

    suppressNextChartPointRef.current = true;
    setDraggingDrawingId(shape.id);
    draggingDrawingShapeRef.current = shape;
    setSelectedAlertId(null);
    onSelectDrawing?.(shape.id);
  }

  async function handleDrawingDragEnd(finalShape: DrawingShape) {
    if (!onUpdateDrawing || finalShape.drawing.locked) {
      return;
    }

    const drawing = finalShape.drawing;
    const nextPayload = drawingPayloadFromShape(drawing, drawing.payload, finalShape);

    try {
      if (nextPayload) {
        draftDrawingPayloadsRef.current = {
          ...draftDrawingPayloadsRef.current,
          [finalShape.id]: nextPayload
        };
        draggingDrawingShapeRef.current = finalShape;
        setDrawingShapes((current) => current.map((item) => (item.id === finalShape.id ? finalShape : item)));
        await onUpdateDrawing(drawing, { payload: nextPayload });
      }
    } catch {
      // El panel padre muestra el error cuando puede. Aqui solo soltamos el drag.
    } finally {
      onSelectDrawing?.(drawing.id);
      setDraggingDrawingId(null);
      window.setTimeout(() => {
        const nextDrafts = { ...draftDrawingPayloadsRef.current };
        if (payloadsEqual(nextDrafts[finalShape.id], nextPayload ?? undefined)) {
          delete nextDrafts[finalShape.id];
          draftDrawingPayloadsRef.current = nextDrafts;
          if (draggingDrawingShapeRef.current?.id === finalShape.id) {
            draggingDrawingShapeRef.current = null;
            window.requestAnimationFrame(recalculateOverlays);
          }
        }
      }, 10_000);
      window.requestAnimationFrame(recalculateOverlays);
      window.setTimeout(() => {
        suppressNextChartPointRef.current = false;
      }, 0);
    }
  }

  function startHtmlDrawingDrag(event: PointerEvent<HTMLElement>, shape: DrawingShape, action: DrawingDragAction = "move") {
    if (!onUpdateDrawing || shape.drawing.locked) {
      return;
    }

    event.preventDefault();
    event.stopPropagation();
    event.nativeEvent.stopImmediatePropagation?.();
    event.currentTarget.setPointerCapture?.(event.pointerId);

    suppressNextChartPointRef.current = true;
    setDraggingDrawingId(shape.id);
    setSelectedAlertId(null);
    onSelectDrawing?.(shape.id);

    const startClientX = event.clientX;
    const startClientY = event.clientY;
    let lastShape = shape;
    let animationFrame: number | null = null;

    function render(nextShape: DrawingShape) {
      lastShape = nextShape;

      if (animationFrame !== null) {
        return;
      }

      animationFrame = window.requestAnimationFrame(() => {
        animationFrame = null;
        draggingDrawingShapeRef.current = lastShape;
        setDrawingShapes((current) => current.map((item) => (item.id === shape.id ? lastShape : item)));
      });
    }

    function move(pointerEvent: globalThis.PointerEvent) {
      pointerEvent.preventDefault();
      pointerEvent.stopPropagation();
      const nextShape = moveDrawingShape(
        shape,
        pointerEvent.clientX - startClientX,
        pointerEvent.clientY - startClientY,
        action
      );
      render(nextShape);
    }

    function cleanup() {
      document.removeEventListener("pointermove", move, true);
      document.removeEventListener("pointerup", up, true);
      document.removeEventListener("pointercancel", cancel, true);

      if (animationFrame !== null) {
        window.cancelAnimationFrame(animationFrame);
        animationFrame = null;
      }
    }

    function up(pointerEvent: globalThis.PointerEvent) {
      pointerEvent.preventDefault();
      pointerEvent.stopPropagation();
      cleanup();
      const finalShape = moveDrawingShape(
        shape,
        pointerEvent.clientX - startClientX,
        pointerEvent.clientY - startClientY,
        action
      );
      draggingDrawingShapeRef.current = finalShape;
      setDrawingShapes((current) => current.map((item) => (item.id === shape.id ? finalShape : item)));
      void handleDrawingDragEnd(finalShape);
    }

    function cancel() {
      cleanup();
      draggingDrawingShapeRef.current = null;
      setDrawingShapes((current) => current.map((item) => (item.id === shape.id ? shape : item)));
      setDraggingDrawingId(null);
      window.setTimeout(() => {
        suppressNextChartPointRef.current = false;
      }, 0);
    }

    document.addEventListener("pointermove", move, { capture: true, passive: false });
    document.addEventListener("pointerup", up, true);
    document.addEventListener("pointercancel", cancel, true);
  }

  function drawingHitStyle(shape: DrawingShape): CSSProperties {
    if (shape.kind === "horizontal_line") {
      return { left: 0, top: shape.y - 18, width: "100%", height: 36, cursor: "pointer" };
    }

    if (shape.kind === "vertical_line") {
      return { left: shape.x - 18, top: 0, width: 36, height: "100%", cursor: "pointer" };
    }

    if (shape.kind === "text") {
      return {
        left: shape.x - 12,
        top: shape.y - shape.fontSize - 14,
        width: Math.max(54, shape.text.length * shape.fontSize * 0.58 + 28),
        height: shape.fontSize + 20,
        cursor: "pointer"
      };
    }

    if (shape.kind === "trend_line") {
      const dx = shape.x2 - shape.x1;
      const dy = shape.y2 - shape.y1;
      const length = Math.max(32, Math.hypot(dx, dy));
      const angle = Math.atan2(dy, dx);

      return {
        left: shape.x1,
        top: shape.y1 - 18,
        width: length,
        height: 36,
        transform: `rotate(${angle}rad)`,
        transformOrigin: "0 18px",
        cursor: "pointer"
      };
    }

    return {
      left: shape.x,
      top: shape.y,
      width: Math.max(18, shape.width),
      height: Math.max(18, shape.height),
      cursor: "pointer"
    };
  }

  function drawingHandleStyle(x: number, y: number, cursor: CSSProperties["cursor"], size = 18, color?: string): CSSProperties {
    return {
      backgroundColor: color,
      cursor,
      height: size,
      left: x - size / 2,
      top: y - size / 2,
      width: size
    };
  }

  function drawingCenter(shape: DrawingShape): { x: number; y: number } {
    if (shape.kind === "horizontal_line") {
      return { x: (shape.x1 + shape.x2) / 2, y: shape.y };
    }

    if (shape.kind === "vertical_line") {
      return { x: shape.x, y: (shape.y1 + shape.y2) / 2 };
    }

    if (shape.kind === "trend_line") {
      return { x: (shape.x1 + shape.x2) / 2, y: (shape.y1 + shape.y2) / 2 };
    }

    if (shape.kind === "text") {
      return { x: shape.x + Math.max(54, shape.text.length * shape.fontSize * 0.58 + 28) / 2, y: shape.y - shape.fontSize / 2 };
    }

    return { x: shape.x + shape.width / 2, y: shape.y + shape.height / 2 };
  }

  function selectDrawingForEdit(event: PointerEvent<HTMLElement>, shape: DrawingShape) {
    event.preventDefault();
    event.stopPropagation();
    event.nativeEvent.stopImmediatePropagation?.();
    setSelectedAlertId(null);
    onSelectDrawing?.(shape.id);
  }

  function renderDrawingHtmlHandles(shape: DrawingShape) {
    const center = drawingCenter(shape);
    const centerHandle = (
      <button
        aria-label="Mover dibujo"
        className="drawing-html-handle drawing-html-handle--center"
        style={drawingHandleStyle(center.x, center.y, "move", 18, shape.color)}
        type="button"
        onPointerDown={(event) => startHtmlDrawingDrag(event, shape, "move")}
      />
    );

    if (shape.kind === "trend_line") {
      return (
        <>
          {centerHandle}
          <button
            aria-label="Mover punto inicial"
            className="drawing-html-handle"
            style={drawingHandleStyle(shape.x1, shape.y1, "move", 16, shape.color)}
            type="button"
            onPointerDown={(event) => startHtmlDrawingDrag(event, shape, "p1")}
          />
          <button
            aria-label="Mover punto final"
            className="drawing-html-handle"
            style={drawingHandleStyle(shape.x2, shape.y2, "move", 16, shape.color)}
            type="button"
            onPointerDown={(event) => startHtmlDrawingDrag(event, shape, "p2")}
          />
        </>
      );
    }

    if (shape.kind !== "rectangle" && shape.kind !== "manual_zone") {
      return centerHandle;
    }

    const right = shape.x + shape.width;
    const bottom = shape.y + shape.height;

    return (
      <>
        {centerHandle}
        <button
          aria-label="Escalar arriba izquierda"
          className="drawing-html-handle"
          style={drawingHandleStyle(shape.x, shape.y, "nwse-resize", 14, shape.color)}
          type="button"
          onPointerDown={(event) => startHtmlDrawingDrag(event, shape, "top-left")}
        />
        <button
          aria-label="Escalar arriba derecha"
          className="drawing-html-handle"
          style={drawingHandleStyle(right, shape.y, "nesw-resize", 14, shape.color)}
          type="button"
          onPointerDown={(event) => startHtmlDrawingDrag(event, shape, "top-right")}
        />
        <button
          aria-label="Escalar abajo izquierda"
          className="drawing-html-handle"
          style={drawingHandleStyle(shape.x, bottom, "nesw-resize", 14, shape.color)}
          type="button"
          onPointerDown={(event) => startHtmlDrawingDrag(event, shape, "bottom-left")}
        />
        <button
          aria-label="Escalar abajo derecha"
          className="drawing-html-handle"
          style={drawingHandleStyle(right, bottom, "nwse-resize", 14, shape.color)}
          type="button"
          onPointerDown={(event) => startHtmlDrawingDrag(event, shape, "bottom-right")}
        />
      </>
    );
  }

  function renderDrawingHitLayer() {
    return (
      <div className="drawing-html-hit-layer" aria-hidden={drawingShapes.length === 0 ? "true" : undefined}>
        {drawingShapes.map((shape) => {
          const selected = effectiveSelectedDrawingId === shape.id;

          return (
            <div key={shape.id}>
              <button
                aria-label="Mover dibujo"
                className={selected ? "drawing-html-hit drawing-html-hit--selected" : "drawing-html-hit"}
                style={drawingHitStyle(shape)}
                type="button"
                onPointerDown={(event) => selectDrawingForEdit(event, shape)}
                onPointerUp={(event) => event.stopPropagation()}
              />
              {selected ? renderDrawingHtmlHandles(shape) : null}
            </div>
          );
        })}
      </div>
    );
  }

  function transformDrawingPayload(
    drawing: ChartDrawingRead,
    payload: Record<string, unknown>,
    startPoint: DrawingPoint,
    nextPoint: DrawingPoint,
    action: DrawingDragAction
  ): Record<string, unknown> {
    const timeDelta = nextPoint.time - startPoint.time;
    const priceDelta = nextPoint.price - startPoint.price;
    const withNumber = (value: unknown, delta: number) => Number(((numberValue(value) ?? 0) + delta).toFixed(5));
    const withTime = (value: unknown, delta: number) => Math.max(0, Math.floor((numberValue(value) ?? 0) + delta));

    if (drawing.drawing_type === "horizontal_line") {
      return { ...payload, price: Number(nextPoint.price.toFixed(5)) };
    }

    if (drawing.drawing_type === "vertical_line") {
      return { ...payload, time: nextPoint.time };
    }

    if (drawing.drawing_type === "text") {
      return {
        ...payload,
        time: action === "move" ? withTime(payload.time, timeDelta) : nextPoint.time,
        price: action === "move" ? withNumber(payload.price, priceDelta) : Number(nextPoint.price.toFixed(5))
      };
    }

    if (drawing.drawing_type === "trend_line") {
      const points = Array.isArray(payload.points) ? payload.points : [];
      const first = typeof points[0] === "object" && points[0] !== null ? { ...(points[0] as Record<string, unknown>) } : {};
      const second = typeof points[1] === "object" && points[1] !== null ? { ...(points[1] as Record<string, unknown>) } : {};
      if (action === "p1") {
        first.time = nextPoint.time;
        first.price = Number(nextPoint.price.toFixed(5));
      } else if (action === "p2") {
        second.time = nextPoint.time;
        second.price = Number(nextPoint.price.toFixed(5));
      } else {
        first.time = withTime(first.time, timeDelta);
        first.price = withNumber(first.price, priceDelta);
        second.time = withTime(second.time, timeDelta);
        second.price = withNumber(second.price, priceDelta);
      }
      return { ...payload, points: [first, second] };
    }

    if (drawing.drawing_type === "rectangle" || drawing.drawing_type === "manual_zone") {
      const isManualZone = drawing.drawing_type === "manual_zone";
      const time1Key = "time1";
      const time2Key = "time2";
      const lowKey = isManualZone ? "price_min" : "price1";
      const highKey = isManualZone ? "price_max" : "price2";
      let time1 = numberValue(payload[time1Key]) ?? startPoint.time;
      let time2 = numberValue(payload[time2Key]) ?? nextPoint.time;
      let price1 = numberValue(payload[lowKey]) ?? startPoint.price;
      let price2 = numberValue(payload[highKey]) ?? nextPoint.price;

      if (action === "move") {
        time1 += timeDelta;
        time2 += timeDelta;
        price1 += priceDelta;
        price2 += priceDelta;
      } else {
        if (action.includes("left")) time1 = timeframeBucketStart(nextPoint.time, timeframe);
        if (action.includes("right")) time2 = timeframeBucketStart(nextPoint.time, timeframe) + timeframeToSeconds(timeframe);
        if (action.includes("top")) price2 = nextPoint.price;
        if (action.includes("bottom")) price1 = nextPoint.price;
      }

      const normalizedTime1 = Math.floor(Math.min(time1, time2));
      const normalizedTime2 = Math.floor(Math.max(time1, time2));
      const safeTime2 = normalizedTime2 <= normalizedTime1 ? normalizedTime1 + timeframeToSeconds(timeframe) : normalizedTime2;
      const low = Number(Math.min(price1, price2).toFixed(5));
      const high = Number(Math.max(price1, price2).toFixed(5));
      return {
        ...payload,
        [time1Key]: normalizedTime1,
        [time2Key]: safeTime2,
        [lowKey]: low,
        [highKey]: high
      };
    }

    return payload;
  }

  function startAlertDrag(event: PointerEvent<HTMLDivElement>, alert: PriceAlertRead) {
    event.preventDefault();
    event.stopPropagation();
    event.nativeEvent.stopImmediatePropagation?.();
    suppressNextChartPointRef.current = true;
    onSelectDrawing?.(null);
    setSelectedAlertId(alert.id);
    setDraggingAlertId(alert.id);
    const price = priceFromPointer(event);
    if (price !== null) {
      setDraftAlertPrices((current) => ({ ...current, [alert.id]: price }));
    }
  }

  function startTpDrag(event: PointerEvent<HTMLDivElement>, line: TradeLineOverlay) {
    if (line.tone !== "tp" || !line.positionId || !line.editable || !onUpdatePositionTp) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    setDraggingTpLineId(line.id);
    const price = priceFromPointer(event);
    if (price !== null) {
      setDraftTradeLinePrices((current) => ({ ...current, [line.id]: price }));
    }
  }

  useEffect(() => {
    if (!draggingAlertId) {
      return;
    }
    const activeAlertId = draggingAlertId;

    function handleMove(event: globalThis.PointerEvent) {
      const price = priceFromPointer(event);
      if (price !== null) {
        setDraftAlertPrices((current) => ({ ...current, [activeAlertId]: price }));
      }
    }

    function handleUp(event: globalThis.PointerEvent) {
      const alert = priceAlerts.find((item) => item.id === activeAlertId);
      const price = priceFromPointer(event);
      if (alert && price !== null) {
        onUpdatePriceAlert?.(alert, price);
      }
      setDraggingAlertId(null);
      setSelectedAlertId(activeAlertId);
      window.setTimeout(() => {
        suppressNextChartPointRef.current = false;
      }, 0);
      window.setTimeout(() => {
        setDraftAlertPrices((current) => {
          if (current[activeAlertId] !== price) {
            return current;
          }

          const next = { ...current };
          delete next[activeAlertId];
          return next;
        });
      }, 10_000);
    }

    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", handleUp, { once: true });
    return () => {
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", handleUp);
    };
  }, [draggingAlertId, onUpdatePriceAlert, priceAlerts]);

  useEffect(() => {
    if (!draggingTpLineId) {
      return;
    }
    const activeLineId = draggingTpLineId;

    function handleMove(event: globalThis.PointerEvent) {
      const price = priceFromPointer(event);
      if (price !== null) {
        setDraftTradeLinePrices((current) => ({ ...current, [activeLineId]: price }));
      }
    }

    async function handleUp(event: globalThis.PointerEvent) {
      const line = tradeLines.find((item) => item.id === activeLineId);
      const price = priceFromPointer(event);
      if (line?.positionId && price !== null) {
        const closePrice = line.side === "SELL" ? askPrice : bidPrice;
        setDraftTradeLinePrices((current) => ({ ...current, [activeLineId]: price }));
        await onUpdatePositionTp?.(line.positionId, price, closePrice ?? null);
      }
      setDraggingTpLineId(null);
      window.setTimeout(() => {
        setDraftTradeLinePrices((current) => {
          if (current[activeLineId] !== price) {
            return current;
          }

          const next = { ...current };
          delete next[activeLineId];
          return next;
        });
      }, 10_000);
    }

    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", handleUp, { once: true });
    return () => {
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", handleUp);
    };
  }, [askPrice, bidPrice, draggingTpLineId, onUpdatePositionTp, tradeLines]);
  function isPointerInsideRightPriceScale(clientX: number): boolean {
  const container = containerRef.current;

  if (!container) {
    return false;
  }

  const bounds = container.getBoundingClientRect();

  /*
   * Ancho aproximado de la escala de precios derecha.
   * Si tu escala es más estrecha/ancha, ajusta este valor.
   */
  const priceScaleWidth = priceScaleWidthRef.current;

  return clientX >= bounds.right - priceScaleWidth;
}

  function markPriceScaleManualAdjustment() {
  const chart = chartRef.current;
  const series = seriesRef.current;

  if (!chart || !series) {
    return;
  }

  priceScaleManuallyAdjustedRef.current = true;
  disablePriceAutoScale(chart, series);
}

  function handleCenterChart() {
    onAutoFollowChange?.(true);
    setLocalHardResetToken((current) => current + 1);
    setLocalRecenterToken((current) => current + 1);
  }

  useEffect(() => {
  const chart = chartRef.current;
  const container = containerRef.current;

  if (!chart || !container) {
    return;
  }

  function markManualInteraction() {
    if (!alertToolActive && drawingTool === "select") {
      onAutoFollowChange?.(false);
    }
  }

  function handlePointerDown(event: globalThis.PointerEvent) {
    chartPointerActiveRef.current = true;

    if (isPointerInsideRightPriceScale(event.clientX)) {
      markPriceScaleManualAdjustment();
    }

    markManualInteraction();
    scheduleOverlayRecalculate();
  }

  function handlePointerMove() {
    if (!chartPointerActiveRef.current) {
      return;
    }

    scheduleOverlayRecalculate();
  }

  function handlePointerUp() {
    if (!chartPointerActiveRef.current) {
      return;
    }

    chartPointerActiveRef.current = false;
    scheduleOverlayRecalculate();
  }

  function handleWheel(event: WheelEvent) {
    if (isPointerInsideRightPriceScale(event.clientX)) {
      markPriceScaleManualAdjustment();
    }

    markManualInteraction();
    scheduleOverlayRecalculate();
  }

  chart.timeScale().subscribeVisibleTimeRangeChange(recalculateOverlays);
  container.addEventListener("wheel", handleWheel, { passive: true });
  container.addEventListener("pointerdown", handlePointerDown, { passive: true });
  window.addEventListener("pointermove", handlePointerMove, { passive: true });
  window.addEventListener("pointerup", handlePointerUp);
  window.addEventListener("pointercancel", handlePointerUp);
  window.addEventListener("resize", recalculateOverlays);
  recalculateOverlays();

  return () => {
    chart.timeScale().unsubscribeVisibleTimeRangeChange(recalculateOverlays);
    container.removeEventListener("wheel", handleWheel);
    container.removeEventListener("pointerdown", handlePointerDown);
    window.removeEventListener("pointermove", handlePointerMove);
    window.removeEventListener("pointerup", handlePointerUp);
    window.removeEventListener("pointercancel", handlePointerUp);
    window.removeEventListener("resize", recalculateOverlays);
  };
}, [alertToolActive, drawingTool, onAutoFollowChange, recalculateOverlays]);

  const effectiveSelectedDrawingId = draggingDrawingId ?? selectedDrawingId;
  const selectedDrawing = effectiveSelectedDrawingId ? drawings.find((drawing) => drawing.id === effectiveSelectedDrawingId) ?? null : null;
  const selectedAlert = selectedAlertId ? priceAlerts.find((alert) => alert.id === selectedAlertId) ?? null : null;
  const selectedObject = selectedDrawing
    ? { kind: "drawing" as const, id: selectedDrawing.id }
    : selectedAlert
      ? { kind: "alert" as const, id: selectedAlert.id }
      : null;
  const canStyleSelectedObject = selectedDrawing ? Boolean(onUpdateDrawing && !selectedDrawing.locked) : Boolean(selectedAlert);
  const canDeleteSelectedObject = selectedDrawing ? Boolean(onDeleteDrawing) : Boolean(selectedAlert && onCancelPriceAlert);

  function updateDrawingStyle(drawing: ChartDrawingRead, patch: Record<string, unknown>) {
    if (!onUpdateDrawing || drawing.locked) {
      return;
    }

    void onUpdateDrawing(drawing, { style: { ...drawing.style, ...patch } });
  }

  function updateAlertStyle(alertId: string, patch: Partial<PriceAlertVisualStyle>) {
    setAlertVisualStyles((current) => {
      const nextStyle = normalizeAlertVisualStyle({ ...(current[alertId] ?? DEFAULT_ALERT_VISUAL_STYLE), ...patch });
      return { ...current, [alertId]: nextStyle };
    });
  }

  function handleSelectedStyleButton(event: PointerEvent<HTMLButtonElement>) {
    event.preventDefault();
    event.stopPropagation();
    event.nativeEvent.stopImmediatePropagation?.();
    if (!selectedObject) {
      return;
    }

    setStyleEditorTarget((current) =>
      current?.kind === selectedObject.kind && current.id === selectedObject.id ? null : selectedObject
    );
  }

  function handleSelectedDeleteButton(event: PointerEvent<HTMLButtonElement>) {
    event.preventDefault();
    event.stopPropagation();
    event.nativeEvent.stopImmediatePropagation?.();

    if (selectedDrawing && onDeleteDrawing) {
      const nextDrafts = { ...draftDrawingPayloadsRef.current };
      delete nextDrafts[selectedDrawing.id];
      draftDrawingPayloadsRef.current = nextDrafts;

      if (draggingDrawingShapeRef.current?.id === selectedDrawing.id) {
        draggingDrawingShapeRef.current = null;
      }

      setStyleEditorTarget(null);
      setDraggingDrawingId(null);
      onSelectDrawing?.(null);
      onDeleteDrawing(selectedDrawing.id);
      return;
    }

    if (selectedAlert && onCancelPriceAlert) {
      const alertId = selectedAlert.id;
      setAlertVisualStyles((current) => {
        const next = { ...current };
        delete next[alertId];
        return next;
      });
      setStyleEditorTarget(null);
      setSelectedAlertId(null);
      onCancelPriceAlert(alertId);
    }
  }

  function renderStyleEditor() {
    if (!styleEditorTarget) {
      return null;
    }

    if (styleEditorTarget.kind === "drawing") {
      const drawing = drawings.find((item) => item.id === styleEditorTarget.id);
      if (!drawing || !onUpdateDrawing || drawing.locked) {
        return null;
      }

      const isLine = drawing.drawing_type === "horizontal_line" || drawing.drawing_type === "vertical_line" || drawing.drawing_type === "trend_line";
      const isBox = drawing.drawing_type === "rectangle" || drawing.drawing_type === "manual_zone";
      const isText = drawing.drawing_type === "text";
      const color = colorInputValue(styleValue(drawing.style, "color", isText ? "#edf2ef" : "#f5c542"), isText ? "#edf2ef" : "#f5c542");
      const textColor = colorInputValue(styleValue(drawing.style, "textColor", color), color);
      const lineWidth = clampedNumericStyleValue(drawing.style, "lineWidth", 2, 1, 6);
      const glow = clampedNumericStyleValue(drawing.style, "glow", 0, 0, 18);
      const opacity = clampedNumericStyleValue(drawing.style, "opacity", isBox && drawing.drawing_type === "manual_zone" ? 0.16 : 0.13, 0, 1);
      const fontSize = clampedNumericStyleValue(drawing.style, "fontSize", 14, 8, 48);

      return (
        <div
          className="chart-style-popover"
          onPointerDown={(event) => {
            event.stopPropagation();
            event.nativeEvent.stopImmediatePropagation?.();
          }}
          onPointerUp={(event) => {
            event.stopPropagation();
            event.nativeEvent.stopImmediatePropagation?.();
          }}
        >
          <div className="chart-style-popover__head">
            <strong>{isText ? "Texto" : isBox ? "Rectangulo" : "Linea"}</strong>
            <button type="button" onClick={() => setStyleEditorTarget(null)}>x</button>
          </div>

          {isLine ? (
            <>
              <label>
                Color
                <input type="color" value={color} onChange={(event) => updateDrawingStyle(drawing, { color: event.target.value })} />
              </label>
              <label>
                Tipo
                <select value={lineStyleValue(drawing.style)} onChange={(event) => updateDrawingStyle(drawing, { lineStyle: event.target.value as ChartLineStyle })}>
                  <option value="solid">Continua</option>
                  <option value="dashed">Discontinua</option>
                </select>
              </label>
              <label>
                Grosor
                <input min="1" max="6" step="1" type="range" value={lineWidth} onChange={(event) => updateDrawingStyle(drawing, { lineWidth: Number(event.target.value) })} />
                <span>{lineWidth}</span>
              </label>
              <label>
                Glow
                <input min="0" max="18" step="1" type="range" value={glow} onChange={(event) => updateDrawingStyle(drawing, { glow: Number(event.target.value) })} />
                <span>{glow}</span>
              </label>
            </>
          ) : null}

          {isBox ? (
            <>
              <label>
                Color
                <input
                  type="color"
                  value={color}
                  onChange={(event) => updateDrawingStyle(drawing, { color: event.target.value, backgroundColor: hexToRgba(event.target.value, opacity) })}
                />
              </label>
              <label>
                Opacidad
                <input
                  min="0"
                  max="1"
                  step="0.01"
                  type="range"
                  value={opacity}
                  onChange={(event) => {
                    const nextOpacity = Number(event.target.value);
                    updateDrawingStyle(drawing, { opacity: nextOpacity, backgroundColor: hexToRgba(color, nextOpacity) });
                  }}
                />
                <span>{Math.round(opacity * 100)}%</span>
              </label>
            </>
          ) : null}

          {isText ? (
            <>
              <label>
                Color
                <input type="color" value={textColor} onChange={(event) => updateDrawingStyle(drawing, { color: event.target.value, textColor: event.target.value })} />
              </label>
              <label>
                Tamano
                <input min="8" max="48" step="1" type="range" value={fontSize} onChange={(event) => updateDrawingStyle(drawing, { fontSize: Number(event.target.value) })} />
                <span>{fontSize}</span>
              </label>
              <label>
                Glow
                <input min="0" max="18" step="1" type="range" value={glow} onChange={(event) => updateDrawingStyle(drawing, { glow: Number(event.target.value) })} />
                <span>{glow}</span>
              </label>
            </>
          ) : null}
        </div>
      );
    }

    const alert = priceAlerts.find((item) => item.id === styleEditorTarget.id);
    if (!alert) {
      return null;
    }

    const style = alertVisualStyles[alert.id] ?? DEFAULT_ALERT_VISUAL_STYLE;
    const color = colorInputValue(style.color, DEFAULT_ALERT_VISUAL_STYLE.color);

    return (
      <div
        className="chart-style-popover"
        onPointerDown={(event) => {
          event.stopPropagation();
          event.nativeEvent.stopImmediatePropagation?.();
        }}
        onPointerUp={(event) => {
          event.stopPropagation();
          event.nativeEvent.stopImmediatePropagation?.();
        }}
      >
        <div className="chart-style-popover__head">
          <strong>Alerta</strong>
          <button type="button" onClick={() => setStyleEditorTarget(null)}>x</button>
        </div>
        <label>
          Color
          <input type="color" value={color} onChange={(event) => updateAlertStyle(alert.id, { color: event.target.value })} />
        </label>
        <label>
          Tipo
          <select value={style.lineStyle} onChange={(event) => updateAlertStyle(alert.id, { lineStyle: event.target.value as ChartLineStyle })}>
            <option value="solid">Continua</option>
            <option value="dashed">Discontinua</option>
          </select>
        </label>
      </div>
    );
  }

  return (
    <div
      className={
        drawingTool === "select"
          ? alertToolActive
            ? "market-chart market-chart-frame market-chart-frame--alert"
            : "market-chart market-chart-frame"
          : "market-chart market-chart-frame market-chart-frame--drawing"
      }
      ref={containerRef}
      onPointerUp={handleChartPointerUp}
    >
      <div className="news-zone-layer" aria-hidden="true">
        {overlays.map((overlay) => (
          <div
            className={
              overlay.zone.blocks_trading
                ? "news-zone-overlay news-zone-overlay--blocking"
                : "news-zone-overlay"
            }
            key={overlay.id}
            style={{
              left: overlay.left,
              width: overlay.width
            }}
            title={overlay.zone.reason}
          >
            <span className="news-zone-line news-zone-line--start" />
            <span className="news-zone-line news-zone-line--end" />
          </div>
        ))}
      </div>

      <DrawingLayer
        interactive={false}
        onSelect={(drawingId) => onSelectDrawing?.(drawingId)}
        pendingPoint={pendingCoordinate}
        selectedDrawingId={effectiveSelectedDrawingId}
        shapes={drawingShapes}
      />
      {renderDrawingHitLayer()}

      {selectedObject && canStyleSelectedObject ? (
        <button
          aria-label="Editar estilo"
          className="chart-hard-reset-button chart-object-style-button"
          type="button"
          onClick={handleSelectedStyleButton}
          onPointerDown={(event) => {
            event.stopPropagation();
            event.nativeEvent.stopImmediatePropagation?.();
          }}
          onPointerUp={(event) => {
            event.stopPropagation();
            event.nativeEvent.stopImmediatePropagation?.();
          }}
        >
          <SlidersHorizontal size={16} />
        </button>
      ) : null}

      {selectedObject && canDeleteSelectedObject ? (
        <button
          aria-label="Eliminar elemento"
          className="chart-hard-reset-button chart-object-delete-button"
          type="button"
          onClick={handleSelectedDeleteButton}
          onPointerDown={(event) => {
            event.stopPropagation();
            event.nativeEvent.stopImmediatePropagation?.();
          }}
          onPointerUp={(event) => {
            event.stopPropagation();
            event.nativeEvent.stopImmediatePropagation?.();
          }}
        >
          <Trash2 size={16} />
        </button>
      ) : null}

      {renderStyleEditor()}

      <button
        aria-label="Centrar grafico"
        className="chart-hard-reset-button"
        type="button"
        onClick={handleCenterChart}
        onPointerDown={(event) => event.stopPropagation()}
      >
        <LocateFixed size={16} />
      </button>

      <div className="trade-line-layer">
        {tradeMarkerOverlays.map((marker) => (
          <div
            className={
              marker.kind === "BUY"
                ? "trade-execution-marker trade-execution-marker--buy"
                : "trade-execution-marker trade-execution-marker--close"
            }
            key={marker.id}
            style={{
              left: marker.x,
              top: marker.y
            }}
          >
            <span className="trade-execution-marker__icon">
              {marker.kind === "BUY" ? "▲" : "●"}
            </span>
            <span className="trade-execution-marker__label">
              {marker.label}
            </span>
          </div>
        ))}
        {tradeLineOverlays.map((line) => (
          <div
            className={[
              "trade-line",
              `trade-line--${line.tone}`,
              line.selected ? "trade-line--selected" : "",
              line.muted ? "trade-line--muted" : "",
              line.editable ? "trade-line--editable" : ""
            ].filter(Boolean).join(" ")}
            key={line.id}
            style={{ top: line.y }}
            onPointerDown={(event) => {
              if (line.tone === "tp") {
                startTpDrag(event, line);
              } else if (line.positionId) {
                event.stopPropagation();
                onSelectPosition?.(line.positionId);
              }
            }}
          >
            <span>
              {line.tone === "entry" && typeof line.profit === "number" ? (
                <>
                  {line.side ?? "BUY"} {(line.volume ?? 0).toFixed(2)},{" "}
                  <strong className={line.profit >= 0 ? "trade-line__money trade-line__money--profit" : "trade-line__money trade-line__money--loss"}>
                    {line.profit.toFixed(2)} {line.currency ?? ""}
                  </strong>
                </>
              ) : (
                line.label
              )}
            </span>
          </div>
        ))}
      </div>

      <div className="price-alert-layer">
        {priceAlertOverlays.map((overlay) => {
          const alertStyle = alertVisualStyles[overlay.alert.id] ?? DEFAULT_ALERT_VISUAL_STYLE;
          const isSelected = selectedAlertId === overlay.alert.id;

          return (
            <div
              className={isSelected ? "price-alert-line price-alert-line--selected" : "price-alert-line"}
              key={overlay.alert.id}
              style={{ borderTopColor: alertStyle.color, borderTopStyle: cssLineStyle(alertStyle.lineStyle), top: overlay.y }}
              onPointerDown={(event) => startAlertDrag(event, overlay.alert)}
              onPointerUp={(event) => {
                event.stopPropagation();
                event.nativeEvent.stopImmediatePropagation?.();
              }}
            >
              <span style={{ borderColor: alertStyle.color, color: alertStyle.color }}>
                <Bell aria-hidden="true" size={13} strokeWidth={3} />
                {onCancelPriceAlert ? (
                  <button
                    aria-label="Cancelar alerta"
                    className="inline-delete"
                    type="button"
                    onPointerDown={(event) => {
                      event.stopPropagation();
                      event.nativeEvent.stopImmediatePropagation?.();
                    }}
                    onClick={(event) => {
                      event.stopPropagation();
                      setSelectedAlertId(null);
                      setStyleEditorTarget(null);
                      setAlertVisualStyles((current) => {
                        const next = { ...current };
                        delete next[overlay.alert.id];
                        return next;
                      });
                      onCancelPriceAlert(overlay.alert.id);
                    }}
                  >
                    x
                  </button>
                ) : null}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
