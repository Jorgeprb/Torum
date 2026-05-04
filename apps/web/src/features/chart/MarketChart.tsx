import { type PointerEvent, useCallback, useEffect, useRef, useState } from "react";
import {
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type LineData,
  LineStyle,
  type UTCTimestamp,
  createChart
} from "lightweight-charts";

import type { Candle } from "../../services/market";
import type { PriceAlertRead } from "../../services/alerts";
import type { ChartDrawingCreate, ChartDrawingRead, ChartDrawingUpdate } from "../../services/drawings";
import type { DrawingCoordinate, DrawingDragAction, DrawingPoint, DrawingShape } from "../drawings/drawingTypes";
import { createBaseDrawing, drawingLabel, numericStyleValue, styleValue } from "../drawings/drawingUtils";
import { DrawingLayer } from "../drawings/DrawingLayer";

import type {
  MarketChartProps,
  PriceAlertOverlay,
  PriceAlertVisualStyle,
  PullbackDebugOverlay,
  TradeLineOverlay,
  TradeMarkerOverlay,
  ZoneOverlay
} from "./chartTypes";
export type { TradeLine, TradeMarker } from "./chartTypes";

import {
  chartBrokerTimeZone,
  chartDisplayTimeZone,
  chartTimeSettingsChangedEvent,
  formatChartCrosshairTime,
  formatChartTickMark,
  timeframeToSeconds,
  timeToNumber,
  utcToBrokerChartTime
} from "./chartTime";

import {
  normalizeCandlesForChart,
  numberValue,
  payloadsEqual,
  sortLineDataByTimeAsc
} from "./chartData";

import {
  clampNumber,
  clampedNumericStyleValue,
  colorInputValue,
  cssLineStyle,
  hexToRgba,
  lineStyleValue
} from "./chartStyle";

import {
  buildFuturePaddingData,
  calculateVisibleBarsForWidth,
  centerRecentBars,
  centerSymbolChange,
  chartTimeToUnix,
  chartXToTime,
  cssPixelValue,
  disablePriceAutoScale,
  hardResetChartView,
  initialCandleBarSpacing,
  isNewsZoneVisibleNow,
  lastRealCandleTime,
  maxVisibleBarsByTimeframe,
  newsZoneEnd,
  newsZoneStart,
  resetPriceScale,
  scrollToLatestRealCandle,
  snapFutureChartTime,
  timeToChartX
} from "./chartCoords";

import { isPointInsideDrawingShape } from "./drawings/drawingHitTesting";
import { DrawingHtmlLayer } from "./overlays/DrawingHtmlLayer";
import { NewsZoneOverlay } from "./overlays/NewsZoneOverlay";
import { PullbackDebugOverlayLayer } from "./overlays/PullbackDebugOverlayLayer";
import { TradeLinesOverlay } from "./overlays/TradeLinesOverlay";
import { PriceAlertsOverlay } from "./overlays/PriceAlertsOverlay";
import { ChartActionButtons } from "./overlays/ChartActionButtons";
import { DrawingStyleEditor } from "./overlays/DrawingStyleEditor";

// ── Alert style persistence ──────────────────────────────────────────────────
const DEFAULT_ALERT_VISUAL_STYLE: PriceAlertVisualStyle = {
  color: "#f5c542",
  lineStyle: "dashed"
};
const ALERT_STYLE_STORAGE_KEY = "torum.priceAlertStyles.v1";

function normalizeAlertVisualStyle(value: unknown): PriceAlertVisualStyle {
  if (!value || typeof value !== "object") return DEFAULT_ALERT_VISUAL_STYLE;
  const source = value as Record<string, unknown>;
  return {
    color: typeof source.color === "string" && source.color ? source.color : DEFAULT_ALERT_VISUAL_STYLE.color,
    lineStyle: source.lineStyle === "solid" ? "solid" : "dashed"
  };
}

function loadAlertVisualStyles(): Record<string, PriceAlertVisualStyle> {
  try {
    if (typeof window === "undefined") return {};
    const raw = window.localStorage.getItem(ALERT_STYLE_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : null;
    if (!parsed || typeof parsed !== "object") return {};
    return Object.fromEntries(
      Object.entries(parsed as Record<string, unknown>).map(([id, v]) => [id, normalizeAlertVisualStyle(v)])
    );
  } catch { return {}; }
}

function saveAlertVisualStyles(styles: Record<string, PriceAlertVisualStyle>) {
  try {
    if (typeof window !== "undefined") window.localStorage.setItem(ALERT_STYLE_STORAGE_KEY, JSON.stringify(styles));
  } catch { /* ok */ }
}

// ── Drawing zone helpers ─────────────────────────────────────────────────────
function isTorumV1OperationZone(drawing: ChartDrawingRead): boolean {
  const metadata = drawing.metadata ?? {};
  const payload = drawing.payload ?? {};
  return metadata.torum_v1_zone_enabled === true || payload.torum_v1_zone_enabled === true;
}

function canBeTorumV1OperationZone(drawing: ChartDrawingRead | null): drawing is ChartDrawingRead {
  return Boolean(drawing && (drawing.drawing_type === "rectangle" || drawing.drawing_type === "manual_zone"));
}

function tradeLineLabel(line: import("./chartTypes").TradeLine, price: number): string {
  if (
    line.tone === "tp" &&
    typeof line.openPrice === "number" && Number.isFinite(line.openPrice) && line.openPrice !== 0 &&
    typeof line.volume === "number" && typeof line.contractSize === "number"
  ) {
    const direction = line.side === "SELL" ? -1 : 1;
    const tpPercent = ((price - line.openPrice) / line.openPrice) * 100 * direction;
    const profit = (price - line.openPrice) * line.volume * line.contractSize * direction;
    return `TP, ${profit >= 0 ? "+" : ""}${profit.toFixed(2)} ${line.currency ?? ""}, ${tpPercent.toFixed(2)}%`;
  }
  return line.label;
}

function drawingTimeSpanFromPoints(firstTime: number, secondTime: number, timeframe: string) {
  const tfSec = timeframeToSeconds(timeframe);
  const firstStart = Math.floor(firstTime / tfSec) * tfSec;
  const secondStart = Math.floor(secondTime / tfSec) * tfSec;
  const left = Math.min(firstStart, secondStart);
  const right = Math.max(firstStart, secondStart) + tfSec;
  return { time1: left, time2: right <= left ? left + tfSec : right };
}

// ── Component ────────────────────────────────────────────────────────────────
export function MarketChart({
  candles,
  loadingCandles = false,
  symbolResetToken = 0,
  hardResetToken = 0,
  noTradeZones = [],
  indicatorLines = [],
  strategyDebugPullbacks = [],
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
  // ── Refs ───────────────────────────────────────────────────────────────────
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
  const suppressNextChartPointerUpRef = useRef(false);
  const suppressNextChartClickRef = useRef(false);
  const suppressNextChartPointRef = useRef(false);
  const draftDrawingPayloadsRef = useRef<Record<string, Record<string, unknown>>>({});
  const draggingDrawingShapeRef = useRef<DrawingShape | null>(null);

  const DRAWING_LONG_PRESS_MS = 550;
  const DRAWING_LONG_PRESS_MOVE_TOLERANCE_PX = 8;

  // ── State ──────────────────────────────────────────────────────────────────
  const [localHardResetToken, setLocalHardResetToken] = useState(0);
  const [localRecenterToken, setLocalRecenterToken] = useState(0);
  const [overlays, setOverlays] = useState<ZoneOverlay[]>([]);
  const [tradeLineOverlays, setTradeLineOverlays] = useState<TradeLineOverlay[]>([]);
  const [tradeMarkerOverlays, setTradeMarkerOverlays] = useState<TradeMarkerOverlay[]>([]);
  const [priceAlertOverlays, setPriceAlertOverlays] = useState<PriceAlertOverlay[]>([]);
  const [pullbackDebugOverlays, setPullbackDebugOverlays] = useState<PullbackDebugOverlay[]>([]);
  const [draggingAlertId, setDraggingAlertId] = useState<string | null>(null);
  const [selectedAlertId, setSelectedAlertId] = useState<string | null>(null);
  const [draftAlertPrices, setDraftAlertPrices] = useState<Record<string, number>>({});
  const [alertVisualStyles, setAlertVisualStyles] = useState<Record<string, PriceAlertVisualStyle>>(() => loadAlertVisualStyles());
  const [draggingTpLineId, setDraggingTpLineId] = useState<string | null>(null);
  const [draftTradeLinePrices, setDraftTradeLinePrices] = useState<Record<string, number>>({});
  const [drawingShapes, setDrawingShapes] = useState<DrawingShape[]>([]);
  const [draggingDrawingId, setDraggingDrawingId] = useState<string | null>(null);
  const [styleEditorTarget, setStyleEditorTarget] = useState<{ kind: "drawing" | "alert"; id: string } | null>(null);
  const [pendingPoint, setPendingPoint] = useState<DrawingPoint | null>(null);
  const [pendingCoordinate, setPendingCoordinate] = useState<DrawingCoordinate | null>(null);

  const effectiveHardResetToken = hardResetToken + localHardResetToken;
  const effectiveRecenterToken = recenterToken + localRecenterToken;

  // ── Helpers ────────────────────────────────────────────────────────────────
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

  function getPreferredVisibleBars(candleCount: number): number {
    const containerWidth = containerRef.current?.clientWidth ?? 360;
    return calculateVisibleBarsForWidth(containerWidth, timeframe, candleCount);
  }

  function isPointerInsideRightPriceScale(clientX: number): boolean {
    const container = containerRef.current;
    if (!container) return false;
    const bounds = container.getBoundingClientRect();
    return clientX >= bounds.right - priceScaleWidthRef.current;
  }

  function markPriceScaleManualAdjustment() {
    const chart = chartRef.current;
    const series = seriesRef.current;
    if (!chart || !series) return;
    priceScaleManuallyAdjustedRef.current = true;
    disablePriceAutoScale(chart, series);
  }

  function priceFromPointer(event: PointerEvent | globalThis.PointerEvent): number | null {
    const series = seriesRef.current;
    const container = containerRef.current;
    if (!series || !container) return null;
    const bounds = container.getBoundingClientRect();
    const y = event.clientY - bounds.top;
    const price = series.coordinateToPrice(y);
    return price === null ? null : Number(price.toFixed(5));
  }

  function chartTimeFromX(x: number, fallback: number | null = null): number | null {
    const chart = chartRef.current;
    const container = containerRef.current;
    if (!chart || !container) return fallback;
    const sortedCandles = normalizeCandlesForChart(candles);
    return chartXToTime(chart, sortedCandles, clampNumber(x, 0, chartPaneWidth(container)), fallback);
  }

  function chartPriceFromY(y: number, fallback: number | null = null): number | null {
    const series = seriesRef.current;
    const container = containerRef.current;
    if (!series || !container) return fallback;
    const price = series.coordinateToPrice(clampNumber(y, 0, container.clientHeight));
    return price === null ? fallback : Number(price.toFixed(5));
  }

  function chartPointFromClient(clientX: number, clientY: number, clampToChart = false): DrawingPoint | null {
    const chart = chartRef.current;
    const series = seriesRef.current;
    const container = containerRef.current;
    if (!chart || !series || !container) return null;
    const bounds = container.getBoundingClientRect();
    const rawX = clientX - bounds.left;
    const rawY = clientY - bounds.top;
    const paneWidth = chartPaneWidth(container);
    const x = clampToChart ? clampNumber(rawX, 0, paneWidth) : rawX;
    const y = clampToChart ? clampNumber(rawY, 0, bounds.height) : rawY;
    const time = chartTimeToUnix(chart.timeScale().coordinateToTime(x));
    const price = series.coordinateToPrice(y);
    if (time === null || price === null) return null;
    return { time, price };
  }

  // ── recalculateOverlays ────────────────────────────────────────────────────
  const recalculateOverlays = useCallback(() => {
    const chart = chartRef.current;
    const series = seriesRef.current;
    const container = containerRef.current;
    if (!chart || !series || !container) {
      setOverlays([]); setDrawingShapes([]); setTradeLineOverlays([]);
      setTradeMarkerOverlays([]); setPriceAlertOverlays([]); setPullbackDebugOverlays([]);
      return;
    }
    syncPriceScaleWidth(container);
    const containerWidth = chartPaneWidth(container);
    const containerHeight = container.clientHeight;
    const sortedCandles = normalizeCandlesForChart(candles);
    const lastCandleTime = lastRealCandleTime(sortedCandles);
    const timeframeSeconds = timeframeToSeconds(timeframe);
    const nowMs = Date.now();

    // news zones
    const next = noTradeZones
      .filter(z => isNewsZoneVisibleNow(z, nowMs) && (showFutureNewsZones || lastCandleTime === null || newsZoneStart(z) <= lastCandleTime))
      .map(zone => {
        const start = snapFutureChartTime(newsZoneStart(zone), lastCandleTime, timeframeSeconds, "floor") as UTCTimestamp;
        const end = snapFutureChartTime(newsZoneEnd(zone), lastCandleTime, timeframeSeconds, "ceil") as UTCTimestamp;
        const startCoord = chart.timeScale().timeToCoordinate(start);
        const endCoord = chart.timeScale().timeToCoordinate(end);
        if (startCoord === null && endCoord === null) return null;
        const left = Math.max(0, startCoord ?? 0);
        const right = Math.min(containerWidth, endCoord ?? containerWidth);
        if (right <= left) return null;
        return { id: zone.id, left, width: Math.max(2, right - left), zone };
      })
      .filter((v): v is ZoneOverlay => v !== null);
    setOverlays(next);

    // drawing shapes
    const shapes = drawings.map((drawing): DrawingShape | null => {
      const operationZone = isTorumV1OperationZone(drawing);
      const color = operationZone ? "#2f8cff" : styleValue(drawing.style, "color", "#f5c542");
      const lineWidth = numericStyleValue(drawing.style, "lineWidth", 2);
      const ls = operationZone ? "dashed" : lineStyleValue(drawing.style);
      const glow = clampedNumericStyleValue(drawing.style, "glow", 0, 0, 18);
      const opacity = operationZone ? 0.18 : clampedNumericStyleValue(drawing.style, "opacity", drawing.drawing_type === "manual_zone" ? 0.16 : 0.13, 0, 1);
      const bgColor = drawing.drawing_type === "rectangle" || drawing.drawing_type === "manual_zone" ? hexToRgba(color, opacity) : styleValue(drawing.style, "backgroundColor", "rgba(245,197,66,0.15)");
      const textColor = styleValue(drawing.style, "textColor", "#edf2ef");
      const fontSize = clampedNumericStyleValue(drawing.style, "fontSize", 14, 8, 48);
      const label = operationZone ? "TORUM V1 BUY ZONE" : drawingLabel(drawing);
      const base = { id: drawing.id, drawing, color, lineWidth, lineStyle: ls, glow, label };
      const payload = draftDrawingPayloadsRef.current[drawing.id] ?? drawing.payload;

      if (drawing.drawing_type === "horizontal_line") {
        const price = numberValue(payload.price);
        const y = price === null ? null : series.priceToCoordinate(price);
        return y === null ? null : ({ ...base, kind: "horizontal_line", x1: 0, x2: containerWidth, y } satisfies DrawingShape);
      }
      if (drawing.drawing_type === "vertical_line") {
        const time = numberValue(payload.time);
        if (time === null) return null;
        const x = timeToChartX(chart, sortedCandles, time, Number.NaN);
        return Number.isNaN(x) ? null : ({ ...base, kind: "vertical_line", x, y1: 0, y2: containerHeight } satisfies DrawingShape);
      }
      if (drawing.drawing_type === "trend_line") {
        const points = Array.isArray(payload.points) ? payload.points : [];
        if (points.length !== 2 || typeof points[0] !== "object" || points[0] === null || typeof points[1] !== "object" || points[1] === null) return null;
        const first = points[0] as Record<string, unknown>;
        const second = points[1] as Record<string, unknown>;
        const time1 = numberValue(first.time); const time2 = numberValue(second.time);
        const price1 = numberValue(first.price); const price2 = numberValue(second.price);
        if (time1 === null || time2 === null || price1 === null || price2 === null) return null;
        const x1 = timeToChartX(chart, sortedCandles, time1, Number.NaN);
        const x2 = timeToChartX(chart, sortedCandles, time2, Number.NaN);
        const y1 = series.priceToCoordinate(price1); const y2 = series.priceToCoordinate(price2);
        return Number.isNaN(x1) || Number.isNaN(x2) || y1 === null || y2 === null ? null : ({ ...base, kind: "trend_line", x1, y1, x2, y2 } satisfies DrawingShape);
      }
      if (drawing.drawing_type === "rectangle") {
        const time1 = numberValue(payload.time1); const time2 = numberValue(payload.time2);
        const price1 = numberValue(payload.price1); const price2 = numberValue(payload.price2);
        if (time1 === null || time2 === null || price1 === null || price2 === null) return null;
        const x1 = timeToChartX(chart, sortedCandles, time1, 0); const x2 = timeToChartX(chart, sortedCandles, time2, containerWidth);
        const y1 = series.priceToCoordinate(price1); const y2 = series.priceToCoordinate(price2);
        if (y1 === null || y2 === null) return null;
        return { ...base, kind: "rectangle", x: Math.min(x1, x2), y: Math.min(y1, y2), width: Math.max(2, Math.abs(x2 - x1)), height: Math.max(2, Math.abs(y2 - y1)), backgroundColor: bgColor } satisfies DrawingShape;
      }
      if (drawing.drawing_type === "manual_zone") {
        const time1 = numberValue(payload.time1); const time2 = numberValue(payload.time2);
        const priceMin = numberValue(payload.price_min); const priceMax = numberValue(payload.price_max);
        if (time1 === null || priceMin === null || priceMax === null) return null;
        const x1 = timeToChartX(chart, sortedCandles, time1, 0);
        const x2 = time2 === null ? containerWidth : timeToChartX(chart, sortedCandles, time2, containerWidth);
        const y1 = series.priceToCoordinate(priceMin); const y2 = series.priceToCoordinate(priceMax);
        if (y1 === null || y2 === null) return null;
        return { ...base, kind: "manual_zone", x: Math.min(x1, x2), y: Math.min(y1, y2), width: Math.max(2, Math.abs(x2 - x1)), height: Math.max(2, Math.abs(y2 - y1)), backgroundColor: bgColor, direction: typeof payload.direction === "string" ? payload.direction : "NEUTRAL" } satisfies DrawingShape;
      }
      if (drawing.drawing_type === "text") {
        const time = numberValue(payload.time); const price = numberValue(payload.price);
        const text = typeof payload.text === "string" ? payload.text : drawingLabel(drawing);
        if (time === null || price === null) return null;
        const x = timeToChartX(chart, sortedCandles, time, Number.NaN);
        const y = series.priceToCoordinate(price);
        return Number.isNaN(x) || y === null ? null : ({ ...base, kind: "text", x, y, text, textColor, fontSize } satisfies DrawingShape);
      }
      return null;
    }).filter((s): s is DrawingShape => s !== null);

    const draggingShape = draggingDrawingShapeRef.current;
    setDrawingShapes(draggingShape ? shapes.map(s => s.id === draggingShape.id ? draggingShape : s) : shapes);

    setTradeLineOverlays(
      tradeLines.filter(l => (l.tone === "entry" || l.tone === "tp") && Number.isFinite(l.price))
        .map(line => {
          const price = draftTradeLinePrices[line.id] ?? line.price;
          const y = series.priceToCoordinate(price);
          return y === null ? null : { ...line, price, y: Number(y), label: tradeLineLabel(line, price) };
        }).filter((l): l is TradeLineOverlay => l !== null)
    );

    setTradeMarkerOverlays([]);

    setPriceAlertOverlays(
      priceAlerts.filter(a => a.status === "ACTIVE")
        .map(alert => {
          const targetPrice = draftAlertPrices[alert.id] ?? alert.target_price;
          const y = series.priceToCoordinate(targetPrice);
          return y === null ? null : { alert, y: Number(y), targetPrice };
        }).filter((o): o is PriceAlertOverlay => o !== null)
    );

    setPullbackDebugOverlays(
      strategyDebugPullbacks.map(debug => {
        const x1 = timeToChartX(chart, sortedCandles, debug.swing_high_time, Number.NaN);
        const x2 = timeToChartX(chart, sortedCandles, debug.pullback_low_time, Number.NaN);
        const y1 = series.priceToCoordinate(debug.swing_high);
        const y2 = series.priceToCoordinate(debug.pullback_low);
        return Number.isNaN(x1) || Number.isNaN(x2) || y1 === null || y2 === null ? null : { debug, x1, y1: Number(y1), x2, y2: Number(y2) };
      }).filter((o): o is PullbackDebugOverlay => o !== null)
    );

    if (pendingPoint) {
      const x = timeToChartX(chart, sortedCandles, pendingPoint.time, Number.NaN);
      const y = series.priceToCoordinate(pendingPoint.price);
      setPendingCoordinate(Number.isNaN(x) || y === null ? null : { x, y });
    } else {
      setPendingCoordinate(null);
    }
  }, [candles, drawings, draftAlertPrices, draftTradeLinePrices, noTradeZones, pendingPoint, priceAlerts, showFutureNewsZones, strategyDebugPullbacks, timeframe, tradeLines, tradeMarkers]);

  function scheduleOverlayRecalculate() {
    if (overlayRecalculateFrameRef.current !== null) return;
    overlayRecalculateFrameRef.current = window.requestAnimationFrame(() => {
      overlayRecalculateFrameRef.current = null;
      recalculateOverlays();
    });
  }
// â”€â”€ Chart init â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      autoSize: true,
      layout: { background: { color: "#000000" }, textColor: "#f2f4f5" },
      localization: { locale: "es-ES", timeFormatter: formatChartCrosshairTime },
      grid: { vertLines: { color: "#24303a", style: LineStyle.Dashed }, horzLines: { color: "#24303a", style: LineStyle.Dashed } },
      rightPriceScale: { borderColor: "#3a434a", scaleMargins: { top: 0.18, bottom: 0.18 } },
      timeScale: { borderColor: "#293033", barSpacing: initialCandleBarSpacing, minBarSpacing: 6, timeVisible: true, secondsVisible: false, tickMarkFormatter: formatChartTickMark },
      handleScale: { axisPressedMouseMove: { time: true, price: true }, mouseWheel: true, pinch: true },
      handleScroll: { horzTouchDrag: true, vertTouchDrag: true, mouseWheel: true, pressedMouseMove: true },
      crosshair: { mode: 1 }
    });
    const series = chart.addCandlestickSeries({ upColor: "#20c9bd", downColor: "#f45d5d", borderUpColor: "#20c9bd", borderDownColor: "#f45d5d", wickUpColor: "#20c9bd", wickDownColor: "#f45d5d", lastValueVisible: false, priceLineVisible: false });
    const fp = chart.addLineSeries({ color: "rgba(0,0,0,0)", lineWidth: 1, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false });
    chartRef.current = chart; seriesRef.current = series; futurePaddingSeriesRef.current = fp;
    return () => {
      if (overlayRecalculateFrameRef.current !== null) { window.cancelAnimationFrame(overlayRecalculateFrameRef.current); overlayRecalculateFrameRef.current = null; }
      lineSeriesRef.current.clear(); futurePaddingSeriesRef.current = null;
      chart.remove(); chartRef.current = null; seriesRef.current = null;
    };
  }, []);

  useEffect(() => { saveAlertVisualStyles(alertVisualStyles); }, [alertVisualStyles]);
  useEffect(() => { if (selectedDrawingId) setSelectedAlertId(null); }, [selectedDrawingId]);
  useEffect(() => {
    if (selectedAlertId && !priceAlerts.some(a => a.id === selectedAlertId)) setSelectedAlertId(null);
  }, [priceAlerts, selectedAlertId]);
  useEffect(() => {
    if (!styleEditorTarget) return;
    if (styleEditorTarget.kind === "drawing" && !drawings.some(d => d.id === styleEditorTarget.id)) setStyleEditorTarget(null);
    if (styleEditorTarget.kind === "alert" && !priceAlerts.some(a => a.id === styleEditorTarget.id)) setStyleEditorTarget(null);
  }, [drawings, priceAlerts, styleEditorTarget]);
  useEffect(() => {
    setStyleEditorTarget(cur => {
      if (!cur) return cur;
      if (cur.kind === "drawing" && cur.id !== selectedDrawingId) return null;
      if (cur.kind === "alert" && cur.id !== selectedAlertId) return null;
      return cur;
    });
  }, [selectedAlertId, selectedDrawingId]);
  useEffect(() => {
    setDraftAlertPrices(cur => {
      let changed = false; const next = { ...cur };
      for (const [id, price] of Object.entries(cur)) {
        const alert = priceAlerts.find(a => a.id === id);
        if (!alert || Math.abs(alert.target_price - price) < 0.00001) { delete next[id]; changed = true; }
      }
      return changed ? next : cur;
    });
  }, [priceAlerts]);
  useEffect(() => {
    setDraftTradeLinePrices(cur => {
      let changed = false; const next = { ...cur };
      for (const [id, price] of Object.entries(cur)) {
        const line = tradeLines.find(l => l.id === id);
        if (!line || Math.abs(line.price - price) < 0.00001) { delete next[id]; changed = true; }
      }
      return changed ? next : cur;
    });
  }, [tradeLines]);
  useEffect(() => {
    let changed = false;
    const nextDrafts = { ...draftDrawingPayloadsRef.current };
    for (const [drawingId, payload] of Object.entries(draftDrawingPayloadsRef.current)) {
      const drawing = drawings.find(d => d.id === drawingId);
      if (!drawing || payloadsEqual(drawing.payload, payload)) {
        delete nextDrafts[drawingId]; changed = true;
        if (draggingDrawingShapeRef.current?.id === drawingId) draggingDrawingShapeRef.current = null;
      }
    }
    if (changed) { draftDrawingPayloadsRef.current = nextDrafts; scheduleOverlayRecalculate(); }
  }, [drawings]);
  useEffect(() => { const id = window.setInterval(recalculateOverlays, 30_000); return () => window.clearInterval(id); }, [recalculateOverlays]);
  useEffect(() => { recalculateOverlays(); }, [priceAlerts, recalculateOverlays]);
  useEffect(() => {
    function handler() {
      const chart = chartRef.current; if (!chart) return;
      chart.applyOptions({ localization: { locale: "es-ES", timeFormatter: formatChartCrosshairTime }, timeScale: { tickMarkFormatter: formatChartTickMark } });
      window.setTimeout(recalculateOverlays, 0);
    }
    window.addEventListener(chartTimeSettingsChangedEvent, handler);
    return () => window.removeEventListener(chartTimeSettingsChangedEvent, handler);
  }, [recalculateOverlays]);
  useEffect(() => { setPendingPoint(null); setPendingCoordinate(null); }, [drawingTool, symbol, timeframe]);

  // â”€â”€ Hard reset â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  useEffect(() => {
    const chart = chartRef.current; const series = seriesRef.current;
    if (!chart || !series || appliedHardResetTokenRef.current === effectiveHardResetToken) return;
    appliedHardResetTokenRef.current = effectiveHardResetToken;
    const sc = normalizeCandlesForChart(candles);
    priceScaleManuallyAdjustedRef.current = false;
    hardResetChartView(chart, series, sc.length, timeframe, getPreferredVisibleBars(sc.length));
    centeredResetKeyRef.current = resetKey ?? `${symbol}:${timeframe}`;
    appliedSymbolResetTokenRef.current = symbolResetToken;
    window.setTimeout(recalculateOverlays, 0);
  }, [effectiveHardResetToken, candles, timeframe, resetKey, symbol, symbolResetToken, recalculateOverlays]);

  // â”€â”€ Candle data sync â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  useEffect(() => {
    const series = seriesRef.current; const chart = chartRef.current;
    if (!series || !chart) return;
    const sc = normalizeCandlesForChart(candles);
    const nextKey = resetKey ?? `${symbol}:${timeframe}`;
    const shouldReset = loadedResetKeyRef.current !== nextKey;
    const shouldSymReset = appliedSymbolResetTokenRef.current !== symbolResetToken;
    if (shouldReset) {
      loadedResetKeyRef.current = nextKey; hasFullDataRef.current = false; centeredResetKeyRef.current = null;
      series.setData([]); series.setMarkers([]);
      if (bidPriceLineRef.current) { series.removePriceLine(bidPriceLineRef.current); bidPriceLineRef.current = null; }
      if (askPriceLineRef.current) { series.removePriceLine(askPriceLineRef.current); askPriceLineRef.current = null; }
      lineSeriesRef.current.forEach(ls => ls.setData([]));
      setOverlays([]); setDrawingShapes([]); setTradeLineOverlays([]); setPriceAlertOverlays([]); setTradeMarkerOverlays([]); setPullbackDebugOverlays([]);
      priceScaleManuallyAdjustedRef.current = false; resetPriceScale(chart, series);
    }
    if (sc.length === 0) { series.setData([]); series.setMarkers([]); hasFullDataRef.current = false; window.setTimeout(recalculateOverlays, 0); return; }
    if (loadingCandles && sc.length <= 2 && !hasFullDataRef.current) { series.setData(sc); series.setMarkers([]); window.setTimeout(recalculateOverlays, 0); return; }
    if (shouldReset || !hasFullDataRef.current) {
      series.setData(sc); series.setMarkers([]); hasFullDataRef.current = true;
      if (shouldSymReset) {
        priceScaleManuallyAdjustedRef.current = false;
        centerSymbolChange(chart, series, sc.length, timeframe, getPreferredVisibleBars(sc.length));
        appliedSymbolResetTokenRef.current = symbolResetToken; centeredResetKeyRef.current = nextKey;
      } else if (centeredResetKeyRef.current !== nextKey) {
        centerRecentBars(chart, sc.length, timeframe, getPreferredVisibleBars(sc.length));
        centeredResetKeyRef.current = nextKey;
      }
      window.setTimeout(recalculateOverlays, 0); return;
    }
    series.update(sc[sc.length - 1]); series.setMarkers([]);
    if (autoFollowEnabled) scrollToLatestRealCandle(chart, sc.length, timeframe, getPreferredVisibleBars(sc.length));
    if (priceScaleManuallyAdjustedRef.current) disablePriceAutoScale(chart, series);
    window.setTimeout(recalculateOverlays, 0);
  }, [autoFollowEnabled, candles, loadingCandles, recalculateOverlays, resetKey, symbol, timeframe, tradeMarkers]);

  useEffect(() => {
    const chart = chartRef.current; const fp = futurePaddingSeriesRef.current;
    if (!chart || !fp) return;
    const vr = chart.timeScale().getVisibleLogicalRange();
    const sc = normalizeCandlesForChart(candles);
    const pd = showFutureNewsZones && autoExtendToFutureNews ? buildFuturePaddingData(sc, noTradeZones, timeframe) : [];
    fp.setData(pd as LineData[]);
    if (vr) chart.timeScale().setVisibleLogicalRange(vr);
    window.requestAnimationFrame(() => { if (vr) chart.timeScale().setVisibleLogicalRange(vr); recalculateOverlays(); });
  }, [autoExtendToFutureNews, candles, noTradeZones, recalculateOverlays, showFutureNewsZones, timeframe]);

  useEffect(() => {
    const chart = chartRef.current; if (!chart || candles.length === 0) return;
    const sc = normalizeCandlesForChart(candles); if (sc.length === 0 || appliedSymbolResetTokenRef.current === symbolResetToken) return;
    const series = seriesRef.current; if (!series) return;
    priceScaleManuallyAdjustedRef.current = false;
    centerSymbolChange(chart, series, sc.length, timeframe, getPreferredVisibleBars(sc.length));
    appliedSymbolResetTokenRef.current = symbolResetToken; centeredResetKeyRef.current = resetKey ?? `${symbol}:${timeframe}`;
    window.setTimeout(recalculateOverlays, 0);
  }, [candles, recalculateOverlays, resetKey, symbol, symbolResetToken, timeframe]);

  useEffect(() => {
    const chart = chartRef.current; if (!chart || candles.length === 0) return;
    centerRecentBars(chart, candles.length, timeframe, getPreferredVisibleBars(candles.length));
    window.setTimeout(recalculateOverlays, 0);
  }, [effectiveRecenterToken]);

  useEffect(() => {
    const series = seriesRef.current; if (!series) return;
    if (bidPriceLineRef.current) { series.removePriceLine(bidPriceLineRef.current); bidPriceLineRef.current = null; }
    if (askPriceLineRef.current) { series.removePriceLine(askPriceLineRef.current); askPriceLineRef.current = null; }
    if (loadingCandles) return;
    if (showBidLine && typeof bidPrice === "number" && Number.isFinite(bidPrice)) bidPriceLineRef.current = series.createPriceLine({ price: bidPrice, color: "#2be0d0", lineWidth: 1, lineStyle: LineStyle.Solid, axisLabelVisible: true, title: "BID" });
    if (showAskLine && typeof askPrice === "number" && Number.isFinite(askPrice)) askPriceLineRef.current = series.createPriceLine({ price: askPrice, color: "#f45d5d", lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: "ASK" });
  }, [askPrice, bidPrice, loadingCandles, showAskLine, showBidLine]);

  useEffect(() => {
    const chart = chartRef.current; if (!chart) return;
    const active = new Set(indicatorLines.map(l => l.name));
    for (const [name, s] of lineSeriesRef.current) { if (!active.has(name)) { chart.removeSeries(s); lineSeriesRef.current.delete(name); } }
    for (const line of indicatorLines) {
      let ls = lineSeriesRef.current.get(line.name);
      if (!ls) { ls = chart.addLineSeries({ color: line.style.color ?? "#d6b25e", lineWidth: (line.style.lineWidth ?? 2) as 1 | 2 | 3 | 4 }); lineSeriesRef.current.set(line.name, ls); }
      ls.setData(sortLineDataByTimeAsc(line.points.map(p => ({ time: p.time as UTCTimestamp, value: p.value }))));
    }
  }, [indicatorLines]);

  useEffect(() => {
    const chart = chartRef.current; const container = containerRef.current;
    if (!chart || !container) return;
    function markManual() { if (!alertToolActive && drawingTool === "select") onAutoFollowChange?.(false); }
    function onDown(e: globalThis.PointerEvent) { chartPointerActiveRef.current = true; if (isPointerInsideRightPriceScale(e.clientX)) markPriceScaleManualAdjustment(); markManual(); scheduleOverlayRecalculate(); }
    function onMove() { if (chartPointerActiveRef.current) scheduleOverlayRecalculate(); }
    function onUp() { if (!chartPointerActiveRef.current) return; chartPointerActiveRef.current = false; scheduleOverlayRecalculate(); }
    function onWheel(e: WheelEvent) { if (isPointerInsideRightPriceScale(e.clientX)) markPriceScaleManualAdjustment(); markManual(); scheduleOverlayRecalculate(); }
    chart.timeScale().subscribeVisibleTimeRangeChange(recalculateOverlays);
    container.addEventListener("wheel", onWheel, { passive: true });
    container.addEventListener("pointerdown", onDown, { passive: true });
    window.addEventListener("pointermove", onMove, { passive: true });
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
    window.addEventListener("resize", recalculateOverlays);
    recalculateOverlays();
    return () => {
      chart.timeScale().unsubscribeVisibleTimeRangeChange(recalculateOverlays);
      container.removeEventListener("wheel", onWheel);
      container.removeEventListener("pointerdown", onDown);
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
      window.removeEventListener("resize", recalculateOverlays);
    };
  }, [alertToolActive, drawingTool, onAutoFollowChange, recalculateOverlays]);

  useEffect(() => {
    if (!draggingAlertId) return;
    const id = draggingAlertId;
    function onMove(e: globalThis.PointerEvent) { const p = priceFromPointer(e); if (p !== null) setDraftAlertPrices(cur => ({ ...cur, [id]: p })); }
    function onUp(e: globalThis.PointerEvent) {
      const alert = priceAlerts.find(a => a.id === id); const p = priceFromPointer(e);
      if (alert && p !== null) onUpdatePriceAlert?.(alert, p);
      setDraggingAlertId(null); setSelectedAlertId(id);
      window.setTimeout(() => { suppressNextChartPointRef.current = false; }, 0);
      window.setTimeout(() => { setDraftAlertPrices(cur => { if (cur[id] !== p) return cur; const n = { ...cur }; delete n[id]; return n; }); }, 10_000);
    }
    window.addEventListener("pointermove", onMove); window.addEventListener("pointerup", onUp, { once: true });
    return () => { window.removeEventListener("pointermove", onMove); window.removeEventListener("pointerup", onUp); };
  }, [draggingAlertId, onUpdatePriceAlert, priceAlerts]);

  useEffect(() => {
    if (!draggingTpLineId) return;
    const id = draggingTpLineId;
    function onMove(e: globalThis.PointerEvent) { const p = priceFromPointer(e); if (p !== null) setDraftTradeLinePrices(cur => ({ ...cur, [id]: p })); }
    async function onUp(e: globalThis.PointerEvent) {
      const line = tradeLines.find(l => l.id === id); const p = priceFromPointer(e);
      if (line?.positionId && p !== null) {
        const closePrice = line.side === "SELL" ? askPrice : bidPrice;
        setDraftTradeLinePrices(cur => ({ ...cur, [id]: p }));
        await onUpdatePositionTp?.(line.positionId, p, closePrice ?? null);
      }
      setDraggingTpLineId(null);
      window.setTimeout(() => { setDraftTradeLinePrices(cur => { if (cur[id] !== p) return cur; const n = { ...cur }; delete n[id]; return n; }); }, 10_000);
    }
    window.addEventListener("pointermove", onMove); window.addEventListener("pointerup", onUp, { once: true });
    return () => { window.removeEventListener("pointermove", onMove); window.removeEventListener("pointerup", onUp); };
  }, [askPrice, bidPrice, draggingTpLineId, onUpdatePositionTp, tradeLines]);

  // â”€â”€ Drawing handlers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  function moveDrawingShape(shape: DrawingShape, dx: number, dy: number, action: DrawingDragAction): DrawingShape {
    if (shape.kind === "horizontal_line") return { ...shape, y: shape.y + dy };
    if (shape.kind === "vertical_line") return { ...shape, x: shape.x + dx };
    if (shape.kind === "text") return { ...shape, x: shape.x + dx, y: shape.y + dy };
    if (shape.kind === "trend_line") {
      if (action === "p1") return { ...shape, x1: shape.x1 + dx, y1: shape.y1 + dy };
      if (action === "p2") return { ...shape, x2: shape.x2 + dx, y2: shape.y2 + dy };
      return { ...shape, x1: shape.x1 + dx, y1: shape.y1 + dy, x2: shape.x2 + dx, y2: shape.y2 + dy };
    }
    if (shape.kind === "rectangle" || shape.kind === "manual_zone") {
      if (action === "move") return { ...shape, x: shape.x + dx, y: shape.y + dy };
      let left = shape.x; let right = shape.x + shape.width; let top = shape.y; let bottom = shape.y + shape.height;
      if (action.includes("left")) left += dx;
      if (action.includes("right")) right += dx;
      if (action.includes("top")) top += dy;
      if (action.includes("bottom")) bottom += dy;
      return { ...shape, x: Math.min(left, right), y: Math.min(top, bottom), width: Math.max(2, Math.abs(right - left)), height: Math.max(2, Math.abs(bottom - top)) };
    }
    return shape;
  }

  function drawingPayloadFromShape(drawing: ChartDrawingRead, payload: Record<string, unknown>, shape: DrawingShape): Record<string, unknown> | null {
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
      const t1 = chartTimeFromX(shape.x1, numberValue(first.time));
      const p1 = chartPriceFromY(shape.y1, numberValue(first.price));
      const t2 = chartTimeFromX(shape.x2, numberValue(second.time));
      const p2 = chartPriceFromY(shape.y2, numberValue(second.price));
      if (t1 === null || p1 === null || t2 === null || p2 === null) return null;
      return { ...payload, points: [{ ...first, time: t1, price: p1 }, { ...second, time: t2, price: p2 }] };
    }
    if ((drawing.drawing_type === "rectangle" && shape.kind === "rectangle") || (drawing.drawing_type === "manual_zone" && shape.kind === "manual_zone")) {
      const isMZ = drawing.drawing_type === "manual_zone";
      const lowKey = isMZ ? "price_min" : "price1"; const highKey = isMZ ? "price_max" : "price2";
      const tL = chartTimeFromX(shape.x, numberValue(payload.time1));
      const tR = chartTimeFromX(shape.x + shape.width, numberValue(payload.time2));
      const pT = chartPriceFromY(shape.y, numberValue(payload[highKey]));
      const pB = chartPriceFromY(shape.y + shape.height, numberValue(payload[lowKey]));
      if (tL === null || tR === null || pT === null || pB === null) return null;
      return { ...payload, time1: Math.floor(Math.min(tL, tR)), time2: Math.max(Math.floor(Math.max(tL, tR)), Math.floor(Math.min(tL, tR)) + 1), [lowKey]: Number(Math.min(pT, pB).toFixed(5)), [highKey]: Number(Math.max(pT, pB).toFixed(5)) };
    }
    return null;
  }

  async function handleDrawingDragEnd(finalShape: DrawingShape) {
    if (!onUpdateDrawing || finalShape.drawing.locked) return;
    const drawing = finalShape.drawing;
    const nextPayload = drawingPayloadFromShape(drawing, drawing.payload, finalShape);
    try {
      if (nextPayload) {
        draftDrawingPayloadsRef.current = { ...draftDrawingPayloadsRef.current, [finalShape.id]: nextPayload };
        draggingDrawingShapeRef.current = finalShape;
        setDrawingShapes(cur => cur.map(item => item.id === finalShape.id ? finalShape : item));
        await onUpdateDrawing(drawing, { payload: nextPayload });
      }
    } catch { /* parent shows error */ } finally {
      onSelectDrawing?.(drawing.id);
      setDraggingDrawingId(null);
      window.setTimeout(() => {
        const nd = { ...draftDrawingPayloadsRef.current };
        if (payloadsEqual(nd[finalShape.id], nextPayload ?? undefined)) {
          delete nd[finalShape.id]; draftDrawingPayloadsRef.current = nd;
          if (draggingDrawingShapeRef.current?.id === finalShape.id) { draggingDrawingShapeRef.current = null; window.requestAnimationFrame(recalculateOverlays); }
        }
      }, 10_000);
      window.requestAnimationFrame(recalculateOverlays);
      window.setTimeout(() => { suppressNextChartPointRef.current = false; }, 0);
    }
  }

  function startHtmlDrawingDrag(event: PointerEvent<HTMLElement>, shape: DrawingShape, action: DrawingDragAction = "move") {
    if (!onUpdateDrawing || shape.drawing.locked) return;
    event.preventDefault(); event.stopPropagation(); event.nativeEvent.stopImmediatePropagation?.();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    suppressNextChartPointRef.current = true;
    setDraggingDrawingId(shape.id); setSelectedAlertId(null); onSelectDrawing?.(shape.id);
    const startX = event.clientX; const startY = event.clientY;
    let lastShape = shape; let af: number | null = null;
    function render(ns: DrawingShape) {
      lastShape = ns; if (af !== null) return;
      af = window.requestAnimationFrame(() => { af = null; draggingDrawingShapeRef.current = lastShape; setDrawingShapes(cur => cur.map(i => i.id === shape.id ? lastShape : i)); });
    }
    function onMove(e: globalThis.PointerEvent) { e.preventDefault(); e.stopPropagation(); render(moveDrawingShape(shape, e.clientX - startX, e.clientY - startY, action)); }
    function cleanup() { document.removeEventListener("pointermove", onMove, true); document.removeEventListener("pointerup", onUp, true); document.removeEventListener("pointercancel", onCancel, true); if (af !== null) { window.cancelAnimationFrame(af); af = null; } }
    function onUp(e: globalThis.PointerEvent) { e.preventDefault(); e.stopPropagation(); cleanup(); const fs = moveDrawingShape(shape, e.clientX - startX, e.clientY - startY, action); draggingDrawingShapeRef.current = fs; setDrawingShapes(cur => cur.map(i => i.id === shape.id ? fs : i)); void handleDrawingDragEnd(fs); }
    function onCancel() { cleanup(); draggingDrawingShapeRef.current = null; setDrawingShapes(cur => cur.map(i => i.id === shape.id ? shape : i)); setDraggingDrawingId(null); window.setTimeout(() => { suppressNextChartPointRef.current = false; }, 0); }
    document.addEventListener("pointermove", onMove, { capture: true, passive: false });
    document.addEventListener("pointerup", onUp, true);
    document.addEventListener("pointercancel", onCancel, true);
  }

  function handleChartPointerDownCapture(event: PointerEvent<HTMLDivElement>) {
    if (event.button !== 0) return;
    const container = containerRef.current; if (!container) return;
    const bounds = container.getBoundingClientRect();
    const x = event.clientX - bounds.left; const y = event.clientY - bounds.top;
    const shape = [...drawingShapes].reverse().find(c => !c.drawing.locked && isPointInsideDrawingShape(c, x, y));
    if (!shape) return;
    const startX = event.clientX; const startY = event.clientY;
    let longPress = false;
    const tid = window.setTimeout(() => {
      longPress = true; suppressNextChartPointerUpRef.current = true; suppressNextChartClickRef.current = true;
      setSelectedAlertId(null); onSelectDrawing?.(shape.id);
      if (navigator.vibrate) navigator.vibrate(20);
    }, DRAWING_LONG_PRESS_MS);
    function cleanup() { window.clearTimeout(tid); document.removeEventListener("pointermove", onMove, true); document.removeEventListener("pointerup", onUp, true); document.removeEventListener("pointercancel", onCancel, true); }
    function onMove(e: globalThis.PointerEvent) { if (!longPress && Math.hypot(e.clientX - startX, e.clientY - startY) > DRAWING_LONG_PRESS_MOVE_TOLERANCE_PX) cleanup(); }
    function onUp() { cleanup(); }
    function onCancel() { cleanup(); }
    document.addEventListener("pointermove", onMove, { capture: true, passive: true });
    document.addEventListener("pointerup", onUp, true);
    document.addEventListener("pointercancel", onCancel, true);
  }

  function handleChartPointerUp(event: PointerEvent<HTMLDivElement>) {
    if (suppressNextChartPointRef.current) { suppressNextChartPointRef.current = false; return; }
    if (!alertToolActive && drawingTool === "select") { onSelectDrawing?.(null); setSelectedAlertId(null); setStyleEditorTarget(null); return; }
    if (draggingAlertId || (!alertToolActive && drawingTool === "select")) return;
    const point = chartPointFromClient(event.clientX, event.clientY);
    if (!point) return;
    event.preventDefault(); event.stopPropagation();
    handleChartPoint(point);
  }

  function handleChartPoint(point: DrawingPoint) {
    if (alertToolActive && onCreatePriceAlert) { onCreatePriceAlert(Number(point.price.toFixed(5))); return; }
    if (drawingTool === "select" || !onCreateDrawing) return;
    if (drawingTool === "horizontal_line") { onCreateDrawing(createBaseDrawing(symbol, timeframe, "horizontal_line", { price: Number(point.price.toFixed(5)), label: "Horizontal" }, "Horizontal line")); return; }
    if (drawingTool === "vertical_line") { onCreateDrawing(createBaseDrawing(symbol, timeframe, "vertical_line", { time: point.time, label: "Vertical" }, "Vertical line")); return; }
    if (drawingTool === "text") {
      const text = window.prompt("Texto del dibujo", "Nota");
      if (text?.trim()) onCreateDrawing(createBaseDrawing(symbol, timeframe, "text", { time: point.time, price: Number(point.price.toFixed(5)), text: text.trim() }, "Text"));
      return;
    }
    if (!pendingPoint) { setPendingPoint(point); return; }
    if (drawingTool === "trend_line") onCreateDrawing(createBaseDrawing(symbol, timeframe, "trend_line", { points: [{ time: pendingPoint.time, price: Number(pendingPoint.price.toFixed(5)) }, { time: point.time, price: Number(point.price.toFixed(5)) }], label: "Trend" }, "Trend line"));
    if (drawingTool === "rectangle") {
      const ts = drawingTimeSpanFromPoints(pendingPoint.time, point.time, timeframe);
      onCreateDrawing(createBaseDrawing(symbol, timeframe, "rectangle", { time1: ts.time1, time2: ts.time2, price1: Number(Math.min(pendingPoint.price, point.price).toFixed(5)), price2: Number(Math.max(pendingPoint.price, point.price).toFixed(5)), label: "Zone" }, "Rectangle"));
    }
    if (drawingTool === "manual_zone") {
      const ts = drawingTimeSpanFromPoints(pendingPoint.time, point.time, timeframe);
      onCreateDrawing(createBaseDrawing(symbol, timeframe, "manual_zone", { time1: ts.time1, time2: ts.time2, price_min: Number(Math.min(pendingPoint.price, point.price).toFixed(5)), price_max: Number(Math.max(pendingPoint.price, point.price).toFixed(5)), direction: "NEUTRAL", label: "Manual zone", rules: {}, metadata: {} }, "Manual zone"));
    }
    setPendingPoint(null); setPendingCoordinate(null);
  }

  function startAlertDrag(event: PointerEvent<HTMLDivElement>, alert: PriceAlertRead) {
    event.preventDefault(); event.stopPropagation(); event.nativeEvent.stopImmediatePropagation?.();
    suppressNextChartPointRef.current = true; onSelectDrawing?.(null); setSelectedAlertId(alert.id); setDraggingAlertId(alert.id);
    const price = priceFromPointer(event);
    if (price !== null) setDraftAlertPrices(cur => ({ ...cur, [alert.id]: price }));
  }

  function startTpDrag(event: PointerEvent<HTMLDivElement>, line: TradeLineOverlay) {
    if (line.tone !== "tp" || !line.positionId || !line.editable || !onUpdatePositionTp) return;
    event.preventDefault(); event.stopPropagation(); setDraggingTpLineId(line.id);
    const price = priceFromPointer(event);
    if (price !== null) setDraftTradeLinePrices(cur => ({ ...cur, [line.id]: price }));
  }

  // â”€â”€ Derived state â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  const effectiveSelectedDrawingId = draggingDrawingId ?? selectedDrawingId;
  const selectedDrawing = effectiveSelectedDrawingId ? drawings.find(d => d.id === effectiveSelectedDrawingId) ?? null : null;
  const selectedAlert = selectedAlertId ? priceAlerts.find(a => a.id === selectedAlertId) ?? null : null;
  const selectedObject = selectedDrawing
    ? { kind: "drawing" as const, id: selectedDrawing.id }
    : selectedAlert ? { kind: "alert" as const, id: selectedAlert.id } : null;
  const canToggleTorumZone = canBeTorumV1OperationZone(selectedDrawing) && Boolean(onUpdateDrawing && !selectedDrawing.locked);
  const canStyleSelectedObject = selectedDrawing ? Boolean(onUpdateDrawing && !selectedDrawing.locked) : Boolean(selectedAlert);
  const canDeleteSelectedObject = selectedDrawing ? Boolean(onDeleteDrawing) : Boolean(selectedAlert && onCancelPriceAlert);

  function updateDrawingStyle(drawing: ChartDrawingRead, patch: Record<string, unknown>) {
    if (!onUpdateDrawing || drawing.locked) return;
    void onUpdateDrawing(drawing, { style: { ...drawing.style, ...patch } });
  }

  function updateAlertStyle(alertId: string, patch: Partial<PriceAlertVisualStyle>) {
    setAlertVisualStyles(cur => {
      const nextStyle = normalizeAlertVisualStyle({ ...(cur[alertId] ?? DEFAULT_ALERT_VISUAL_STYLE), ...patch });
      return { ...cur, [alertId]: nextStyle };
    });
  }

  function handleSelectedStyleButton(event: PointerEvent<HTMLButtonElement>) {
    event.preventDefault(); event.stopPropagation(); event.nativeEvent.stopImmediatePropagation?.();
    if (!selectedObject) return;
    setStyleEditorTarget(cur => cur?.kind === selectedObject.kind && cur.id === selectedObject.id ? null : selectedObject);
  }

  function handleTorumZoneToggle(event: PointerEvent<HTMLButtonElement>) {
    event.preventDefault(); event.stopPropagation(); event.nativeEvent.stopImmediatePropagation?.();
    if (!selectedDrawing || !onUpdateDrawing || selectedDrawing.locked || !canBeTorumV1OperationZone(selectedDrawing)) return;
    const enabled = !isTorumV1OperationZone(selectedDrawing);
    void onUpdateDrawing(selectedDrawing, { metadata: { ...selectedDrawing.metadata, torum_v1_zone_enabled: enabled, zone_type: enabled ? "OPERATION_ZONE" : null, direction: "BUY" } });
  }

  function handleSelectedDeleteButton(event: PointerEvent<HTMLButtonElement>) {
    event.preventDefault(); event.stopPropagation(); event.nativeEvent.stopImmediatePropagation?.();
    if (selectedDrawing && onDeleteDrawing) {
      const nd = { ...draftDrawingPayloadsRef.current }; delete nd[selectedDrawing.id]; draftDrawingPayloadsRef.current = nd;
      if (draggingDrawingShapeRef.current?.id === selectedDrawing.id) draggingDrawingShapeRef.current = null;
      setStyleEditorTarget(null); setDraggingDrawingId(null); onSelectDrawing?.(null); onDeleteDrawing(selectedDrawing.id); return;
    }
    if (selectedAlert && onCancelPriceAlert) {
      const alertId = selectedAlert.id;
      setAlertVisualStyles(cur => { const n = { ...cur }; delete n[alertId]; return n; });
      setStyleEditorTarget(null); setSelectedAlertId(null); onCancelPriceAlert(alertId);
    }
  }

  function handleAlertCancel(alertId: string) {
    setSelectedAlertId(null); setStyleEditorTarget(null);
    setAlertVisualStyles(cur => { const n = { ...cur }; delete n[alertId]; return n; });
    onCancelPriceAlert?.(alertId);
  }

  // â”€â”€ JSX â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  return (
    <div
      className={
        drawingTool === "select"
          ? alertToolActive ? "market-chart market-chart-frame market-chart-frame--alert" : "market-chart market-chart-frame"
          : "market-chart market-chart-frame market-chart-frame--drawing"
      }
      ref={containerRef}
      onPointerUp={handleChartPointerUp}
      onPointerDownCapture={handleChartPointerDownCapture}
    >
      <NewsZoneOverlay overlays={overlays} />
      <PullbackDebugOverlayLayer overlays={pullbackDebugOverlays} />
      <DrawingLayer
        interactive={false}
        onSelect={(id) => onSelectDrawing?.(id)}
        pendingPoint={pendingCoordinate}
        selectedDrawingId={effectiveSelectedDrawingId}
        shapes={drawingShapes}
      />
      <DrawingHtmlLayer
        shapes={drawingShapes}
        selectedDrawingId={effectiveSelectedDrawingId}
        onDragStart={startHtmlDrawingDrag}
      />
      <ChartActionButtons
        selectedObject={selectedObject}
        canToggleTorumZone={canToggleTorumZone}
        isTorumZoneActive={selectedDrawing ? isTorumV1OperationZone(selectedDrawing) : false}
        canStyleSelectedObject={canStyleSelectedObject}
        canDeleteSelectedObject={canDeleteSelectedObject}
        styleEditorOpen={Boolean(styleEditorTarget)}
        onCenterChart={() => { onAutoFollowChange?.(true); setLocalHardResetToken(c => c + 1); setLocalRecenterToken(c => c + 1); }}
        onToggleTorumZone={handleTorumZoneToggle}
        onStyleButton={handleSelectedStyleButton}
        onDeleteButton={handleSelectedDeleteButton}
      />
      <DrawingStyleEditor
        styleEditorTarget={styleEditorTarget}
        drawings={drawings}
        priceAlerts={priceAlerts}
        alertVisualStyles={alertVisualStyles}
        defaultAlertStyle={DEFAULT_ALERT_VISUAL_STYLE}
        onClose={() => setStyleEditorTarget(null)}
        onUpdateDrawingStyle={updateDrawingStyle}
        onUpdateAlertStyle={updateAlertStyle}
      />
      <TradeLinesOverlay
        tradeLineOverlays={tradeLineOverlays}
        tradeMarkerOverlays={tradeMarkerOverlays}
        onSelectPosition={onSelectPosition}
        onTpDragStart={startTpDrag}
      />
      <PriceAlertsOverlay
        priceAlertOverlays={priceAlertOverlays}
        alertVisualStyles={alertVisualStyles}
        selectedAlertId={selectedAlertId}
        onCancelPriceAlert={onCancelPriceAlert}
        onDragStart={startAlertDrag}
        onPointerUp={(e) => { e.stopPropagation(); e.nativeEvent.stopImmediatePropagation?.(); }}
        onAlertCancel={handleAlertCancel}
      />
    </div>
  );
}
