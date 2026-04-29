import { type PointerEvent, useCallback, useEffect, useRef, useState } from "react";
import { LocateFixed, Trash2 } from "lucide-react";
import {
  type CandlestickData,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type LineData,
  LineStyle,
  type Time,
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
  onUpdateDrawing?: (drawing: ChartDrawingRead, patch: ChartDrawingUpdate) => void;
  onDeleteDrawing?: (drawingId: string) => void;
  onSelectDrawing?: (drawingId: string | null) => void;
  tradeLines?: TradeLine[];
  tradeMarkers?: TradeMarker[];
  onSelectPosition?: (positionId: number) => void;
  onUpdatePositionTp?: (positionId: number, tp: number) => void;
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

function toChartX(chart: IChartApi, time: number, fallback: number): number {
  return chart.timeScale().timeToCoordinate(time as UTCTimestamp) ?? fallback;
}

const visibleBarsByTimeframe: Record<string, number> = {
  M1: 120,
  M5: 150,
  H1: 160,
  H2: 160,
  H4: 160,
  D1: 180,
  W1: 220
};
const candleSpacingScale = 0.6; // Modifica aqui el espacio entre velas: menor = mas espacio.
const candleBarSpacing = 10; // Modifica aqui el espaciado base de velas.

function barsWithCandleSpacing(baseBars: number, candleCount: number): number {
  return Math.min(Math.max(20, Math.round(baseBars * candleSpacingScale)), candleCount);
}

function centerRecentBars(chart: IChartApi, candleCount: number, timeframe: string) {
  if (candleCount <= 0) {
    return;
  }

  if (candleCount <= 2) {
    chart.timeScale().fitContent();
    return;
  }

  const bars = barsWithCandleSpacing(visibleBarsByTimeframe[timeframe] ?? 160, candleCount);
  const from = Math.max(0, candleCount - bars);
  const to = candleCount + 4;

  chart.timeScale().setVisibleLogicalRange({ from, to });
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
  timeframe: string
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
    chart.timeScale().fitContent();
    chart.timeScale().scrollToRealTime();

    window.requestAnimationFrame(() => {
      resetPriceScale(chart, series);
    });

    return;
  }

  const barsByTimeframe: Record<string, number> = {
    M1: 90,
    M5: 110,
    H1: 120,
    H2: 130,
    H4: 140,
    D1: 160,
    W1: 180
  };

  const bars = barsWithCandleSpacing(barsByTimeframe[timeframe] ?? 120, candleCount);
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

function centerSymbolChange(chart: IChartApi, series: ISeriesApi<"Candlestick">, candleCount: number, timeframe: string) {
  if (candleCount <= 0) {
    resetPriceScale(chart, series);
    return;
  }

  resetPriceScale(chart, series);

  if (candleCount <= 2) {
    chart.timeScale().fitContent();
    chart.timeScale().scrollToRealTime();

    window.requestAnimationFrame(() => {
      resetPriceScale(chart, series);
    });

    return;
  }

  const barsByTimeframe: Record<string, number> = {
    M1: 90,
    M5: 110,
    H1: 120,
    H2: 130,
    H4: 140,
    D1: 160,
    W1: 180
  };

  const bars = barsWithCandleSpacing(barsByTimeframe[timeframe] ?? 120, candleCount);
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
  resetKey
}: MarketChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const lineSeriesRef = useRef<Map<string, ISeriesApi<"Line">>>(new Map());
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
  const [localHardResetToken, setLocalHardResetToken] = useState(0);
  const [localRecenterToken, setLocalRecenterToken] = useState(0);
  const [overlays, setOverlays] = useState<ZoneOverlay[]>([]);
  const [tradeLineOverlays, setTradeLineOverlays] = useState<TradeLineOverlay[]>([]);
  const [tradeMarkerOverlays, setTradeMarkerOverlays] = useState<TradeMarkerOverlay[]>([]);
  const [priceAlertOverlays, setPriceAlertOverlays] = useState<PriceAlertOverlay[]>([]);
  const [draggingAlertId, setDraggingAlertId] = useState<string | null>(null);
  const [draftAlertPrices, setDraftAlertPrices] = useState<Record<string, number>>({});
  const [draggingTpLineId, setDraggingTpLineId] = useState<string | null>(null);
  const [draftTradeLinePrices, setDraftTradeLinePrices] = useState<Record<string, number>>({});
  const [drawingShapes, setDrawingShapes] = useState<DrawingShape[]>([]);
  const [draftDrawingPayloads, setDraftDrawingPayloads] = useState<Record<string, Record<string, unknown>>>({});
  const [pendingPoint, setPendingPoint] = useState<DrawingPoint | null>(null);
  const [pendingCoordinate, setPendingCoordinate] = useState<DrawingCoordinate | null>(null);
  
  const suppressNextChartPointRef = useRef(false);
  const effectiveHardResetToken = hardResetToken + localHardResetToken;
  const effectiveRecenterToken = recenterToken + localRecenterToken;

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

    const containerWidth = container.clientWidth;
    const containerHeight = container.clientHeight;

    const next = noTradeZones
      .map((zone) => {
        const start = Math.floor(new Date(zone.start_time).getTime() / 1000) as UTCTimestamp;
        const end = Math.floor(new Date(zone.end_time).getTime() / 1000) as UTCTimestamp;

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
        const backgroundColor = styleValue(drawing.style, "backgroundColor", "rgba(245,197,66,0.15)");
        const textColor = styleValue(drawing.style, "textColor", "#edf2ef");
        const label = drawingLabel(drawing);

        const base = {
          id: drawing.id,
          drawing,
          color,
          lineWidth,
          label
        };

        const payload = draftDrawingPayloads[drawing.id] ?? drawing.payload;

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

          const x = chart.timeScale().timeToCoordinate(time as UTCTimestamp);

          return x === null
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

          const x1 = chart.timeScale().timeToCoordinate(time1 as UTCTimestamp);
          const x2 = chart.timeScale().timeToCoordinate(time2 as UTCTimestamp);
          const y1 = series.priceToCoordinate(price1);
          const y2 = series.priceToCoordinate(price2);

          return x1 === null || x2 === null || y1 === null || y2 === null
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

          const x1 = toChartX(chart, time1, 0);
          const x2 = toChartX(chart, time2, containerWidth);
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

          const x1 = toChartX(chart, time1, 0);
          const x2 = time2 === null ? containerWidth : toChartX(chart, time2, containerWidth);
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

          const x = chart.timeScale().timeToCoordinate(time as UTCTimestamp);
          const y = series.priceToCoordinate(price);

          return x === null || y === null
            ? null
            : ({
                ...base,
                kind: "text",
                x,
                y,
                text,
                textColor
              } satisfies DrawingShape);
        }

        return null;
      })
      .filter((shape): shape is DrawingShape => shape !== null);

    setDrawingShapes(shapes);

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
      const x = chart.timeScale().timeToCoordinate(pendingPoint.time as UTCTimestamp);
      const y = series.priceToCoordinate(pendingPoint.price);
      setPendingCoordinate(x === null || y === null ? null : { x, y });
    } else {
      setPendingCoordinate(null);
    }
 }, [
  candles,
  drawings,
  draftAlertPrices,
  draftDrawingPayloads,
  draftTradeLinePrices,
  noTradeZones,
  pendingPoint,
  priceAlerts,
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
        barSpacing: candleBarSpacing,
        timeVisible: true,
        secondsVisible: false
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

    chartRef.current = chart;
    seriesRef.current = series;

    return () => {
      if (overlayRecalculateFrameRef.current !== null) {
        window.cancelAnimationFrame(overlayRecalculateFrameRef.current);
        overlayRecalculateFrameRef.current = null;
      }
      lineSeriesRef.current.clear();
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
  hardResetChartView(chart, series, sortedCandles.length, timeframe);

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
    centerSymbolChange(chart, series, sortedCandles.length, timeframe);
    appliedSymbolResetTokenRef.current = symbolResetToken;
    centeredResetKeyRef.current = nextResetKey;
  } else if (centeredResetKeyRef.current !== nextResetKey) {
    if (sortedCandles.length > 2) {
      centerRecentBars(chart, sortedCandles.length, timeframe);
    } else {
      chart.timeScale().fitContent();
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
    chart.timeScale().scrollToRealTime();
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
  centerSymbolChange(chart, series, sortedCandles.length, timeframe);
  appliedSymbolResetTokenRef.current = symbolResetToken;
  centeredResetKeyRef.current = resetKey ?? `${symbol}:${timeframe}`;

  window.setTimeout(recalculateOverlays, 0);
}, [candles, recalculateOverlays, resetKey, symbol, symbolResetToken, timeframe]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || candles.length === 0) {
      return;
    }
    centerRecentBars(chart, candles.length, timeframe);
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
    const x = clampToChart ? clampNumber(rawX, 0, bounds.width) : rawX;
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
      onCreateDrawing(
        createBaseDrawing(
          symbol,
          timeframe,
          "rectangle",
          {
            time1: Math.min(pendingPoint.time, point.time),
            time2: Math.max(pendingPoint.time, point.time),
            price1: Number(Math.min(pendingPoint.price, point.price).toFixed(5)),
            price2: Number(Math.max(pendingPoint.price, point.price).toFixed(5)),
            label: "Zone"
          },
          "Rectangle"
        )
      );
    }

    if (drawingTool === "manual_zone") {
      onCreateDrawing(
        createBaseDrawing(
          symbol,
          timeframe,
          "manual_zone",
          {
            time1: Math.min(pendingPoint.time, point.time),
            time2: Math.max(pendingPoint.time, point.time),
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

  function startDrawingDrag(event: PointerEvent<SVGElement>, shape: DrawingShape, action: DrawingDragAction) {
    if (!onUpdateDrawing || shape.drawing.locked) {
      return;
    }
    const updateDrawing = onUpdateDrawing;
    suppressNextChartPointRef.current = true;
    const startPoint = chartPointFromClient(event.clientX, event.clientY, true);
    if (!startPoint) {
      return;
    }
    const dragStartPoint = startPoint;
    const originalPayload = { ...shape.drawing.payload };
    const drawing = shape.drawing;

    function handleMove(moveEvent: globalThis.PointerEvent) {
      const nextPoint = chartPointFromClient(moveEvent.clientX, moveEvent.clientY, true);
      if (!nextPoint) {
        return;
      }
      const nextPayload = transformDrawingPayload(drawing, originalPayload, dragStartPoint, nextPoint, action);
      setDraftDrawingPayloads((current) => ({ ...current, [drawing.id]: nextPayload }));
    }

    function handleUp(upEvent: globalThis.PointerEvent) {
      window.removeEventListener("pointermove", handleMove);
      const nextPoint = chartPointFromClient(upEvent.clientX, upEvent.clientY, true);
      if (nextPoint) {
        const nextPayload = transformDrawingPayload(drawing, originalPayload, dragStartPoint, nextPoint, action);
        updateDrawing(drawing, { payload: nextPayload });
      }
      setDraftDrawingPayloads((current) => {
        const next = { ...current };
        delete next[drawing.id];
        return next;
      });
      window.setTimeout(() => {
        suppressNextChartPointRef.current = false;
      }, 0);
    }

    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", handleUp, { once: true });
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
        if (action.includes("left")) time1 = nextPoint.time;
        if (action.includes("right")) time2 = nextPoint.time;
        if (action.includes("top")) price2 = nextPoint.price;
        if (action.includes("bottom")) price1 = nextPoint.price;
      }

      const normalizedTime1 = Math.floor(Math.min(time1, time2));
      const normalizedTime2 = Math.floor(Math.max(time1, time2));
      const low = Number(Math.min(price1, price2).toFixed(5));
      const high = Number(Math.max(price1, price2).toFixed(5));
      return {
        ...payload,
        [time1Key]: normalizedTime1,
        [time2Key]: normalizedTime2,
        [lowKey]: low,
        [highKey]: high
      };
    }

    return payload;
  }

  function startAlertDrag(event: PointerEvent<HTMLDivElement>, alert: PriceAlertRead) {
    event.preventDefault();
    event.stopPropagation();
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
      setDraftAlertPrices((current) => {
        const next = { ...current };
        delete next[activeAlertId];
        return next;
      });
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

    function handleUp(event: globalThis.PointerEvent) {
      const line = tradeLines.find((item) => item.id === activeLineId);
      const price = priceFromPointer(event);
      if (line?.positionId && price !== null) {
        onUpdatePositionTp?.(line.positionId, price);
      }
      setDraggingTpLineId(null);
      setDraftTradeLinePrices((current) => {
        const next = { ...current };
        delete next[activeLineId];
        return next;
      });
    }

    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", handleUp, { once: true });
    return () => {
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", handleUp);
    };
  }, [draggingTpLineId, onUpdatePositionTp, tradeLines]);
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
  const priceScaleWidth = 76;

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
        onDragStart={startDrawingDrag}
        onSelect={(drawingId) => onSelectDrawing?.(drawingId)}
        pendingPoint={pendingCoordinate}
        selectedDrawingId={selectedDrawingId}
        shapes={drawingShapes}
      />

      {selectedDrawingId && onDeleteDrawing ? (
        <button
          aria-label="Eliminar dibujo"
          className="chart-hard-reset-button chart-object-delete-button"
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            onDeleteDrawing(selectedDrawingId);
          }}
          onPointerDown={(event) => event.stopPropagation()}
        >
          <Trash2 size={16} />
        </button>
      ) : null}

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
        {priceAlertOverlays.map((overlay) => (
          <div
            className="price-alert-line"
            key={overlay.alert.id}
            style={{ top: overlay.y }}
            onPointerDown={(event) => startAlertDrag(event, overlay.alert)}
          >
            <span>
              ALERTA &lt;= {overlay.targetPrice.toFixed(2)}
              {onCancelPriceAlert ? (
                <button
                  aria-label="Cancelar alerta"
                  className="inline-delete"
                  type="button"
                  onPointerDown={(event) => event.stopPropagation()}
                  onClick={(event) => {
                    event.stopPropagation();
                    onCancelPriceAlert(overlay.alert.id);
                  }}
                >
                  x
                </button>
              ) : null}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
