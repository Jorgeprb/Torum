import { startTransition, useEffect, useMemo, useRef, useState } from "react";
import type { Time } from "lightweight-charts";
import { AlertTriangle, ArrowDownUp, Bell, CalendarDays, Database, Menu, Minus, MousePointer, Pause, Play, RadioTower, RefreshCw, SeparatorVertical, ShieldAlert, Square, TrendingUp, Type, X } from "lucide-react";

import { StatusPill } from "../../components/ui/StatusPill";
import { MarketChart, type TradeExecutionMarker, type TradeLine, type TradeMarker } from "../chart/MarketChart";
import { chartDensityChangedEvent, readChartDensity, type ChartDensityOptions } from "../chart/chartDensitySettings";
import { DrawingPanel } from "../drawings/DrawingPanel";
import { DrawingToolbar } from "../drawings/DrawingToolbar";
import { IndicatorsPanel } from "../indicators/IndicatorsPanel";
import { NewsPanel } from "../news/NewsPanel";
import { PriceAlertPanel } from "../alerts/PriceAlertPanel";
import { activatePushForPriceAlert, type PushStatus } from "../alerts/pushNotifications";
import { SystemStatusModal } from "../admin/SystemStatusModal";
import { DollarStrengthBadge } from "../marketContext/DollarStrengthBadge";
import { AccountDrawer, type MobileView } from "../mobile/AccountDrawer";
import { MobileTopBar } from "../mobile/MobileTopBar";
import { BuyOnlyOrderPanel } from "./BuyOnlyOrderPanel";
import { OrdersPositionsPanel } from "./OrdersPositionsPanel";
import { TradingWorkspacePanels } from "./TradingWorkspacePanels";
import { usePwaResume } from "./hooks/usePwaResume";
import {
  type TradeExecutionMarkerSettings,
  readTradeExecutionMarkerSettings,
  tradeExecutionMarkersChangedEvent
} from "./tradeExecutionMarkerSettings";
import {
  buildTradeExecutionMarkers,
  calculatePriceDistanceProfit,
  contractSizeFor,
  historyGrossProfit,
  profitConversionRateFor,
  isReallyOpenPosition,
  positionCloseTime,
  positionOpenTime,
  positionToTradeHistoryItem,
  positionValuation,
  tradeLinesForSymbol,
  uniqueMarkers
} from "./tradePresentation";
import {
  type Candle,
  type MarketMessage,
  type MockMarketStatus,
  type MT5Status,
  type LatestTickDiagnostic,
  type SymbolMapping,
  type Tick,
  type Timeframe,
  getCandles,
  getLatestTick,
  getMockMarketStatus,
  getMt5Status,
  getSymbols,
  getTicks,
  startMockMarket,
  stopMockMarket
} from "../../services/market";
import { MarketSocketManager, type MarketSocketStatus } from "../../services/marketSocket";
import { readPersistedCandles, sanitizeCandlesForCache, writePersistedCandles } from "../../services/candleCache";
import {
  type ChartDrawingCreate,
  type ChartDrawingRead,
  type ChartDrawingUpdate,
  type DrawingTool,
  createDrawing,
  deleteDrawing,
  getDrawings,
  patchDrawing
} from "../../services/drawings";
import {
  type ManualOrderResponse,
  type OrderRead,
  type PositionRead,
  type TradeHistoryItem,
  type TradingSettings,
  closePosition,
  getOrders,
  getPositions,
  getTradeHistory,
  getTradingSettings,
  modifyPositionTp
} from "../../services/trading";
import { type AthPriceZone, type IndicatorLineOutput, type StrategyPullbackDebug, getChartOverlays, getTorumV1Pullbacks, isLineOutput } from "../../services/indicators";
import { type NoTradeZone } from "../../services/news";
import { type TorumV1Status, getTorumV1Status } from "../../services/strategies";
import {
  type PriceAlertRead,
  cancelPriceAlert,
  createPriceAlert,
  getPriceAlertHistory,
  getPriceAlerts,
  patchPriceAlert
} from "../../services/alerts";

const fallbackSymbols = ["XAUUSD", "XAUEUR", "DXY"];
const timeframes: Timeframe[] = ["M1", "M5", "H1", "H2", "H3", "H4", "D1", "W1"];
const dxyTimeframes: Timeframe[] = ["D1"];
const deprecatedSymbols = new Set(["XAUAUD", "XAUJPY"]);
type ChartSplitCount = 1 | 2 | 3;
type ChartSplitOrientation = "vertical" | "horizontal";
interface SplitChartSelection {
  symbol: string;
}

const mobileDrawingTools: DrawingTool[] = ["horizontal_line", "vertical_line", "trend_line", "rectangle", "text", "select"];
const spyModeStorageKey = "torum.spyMode";
const showFutureNewsZonesStorageKey = "torum.showFutureNewsZones";
const autoExtendToFutureNewsStorageKey = "torum.autoExtendToFutureNews";
const showPullbackOverlaysStorageKey = "torum.showPullbackOverlays";
const futureNewsVisualsChangedEvent = "torum-future-news-visuals-changed";
const futureOverlayLookaheadDays = 90;
const torumTopbarStatusSymbols = new Set(["XAUUSD", "XAUEUR"]);

function readSpyModePreference(): boolean {
  try {
    return window.localStorage.getItem(spyModeStorageKey) === "1";
  } catch {
    return false;
  }
}

function readDefaultTruePreference(key: string): boolean {
  try {
    return window.localStorage.getItem(key) !== "0";
  } catch {
    return true;
  }
}

function saveBooleanPreference(key: string, enabled: boolean) {
  try {
    window.localStorage.setItem(key, enabled ? "1" : "0");
  } catch {
    // Prefer live UI over storage.
  }
}

function readInitialSymbol(): string {
  try {
    return new URLSearchParams(window.location.search).get("symbol")?.toUpperCase() || defaultSymbolForMadridSession();
  } catch {
    return defaultSymbolForMadridSession();
  }
}

function madridMinutes(date = new Date()): number {
  const parts = new Intl.DateTimeFormat("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Europe/Madrid"
  }).formatToParts(date);

  const hour = Number(parts.find((part) => part.type === "hour")?.value ?? "0");
  const minute = Number(parts.find((part) => part.type === "minute")?.value ?? "0");
  return hour * 60 + minute;
}

function defaultSymbolForMadridSession(date = new Date()): string {
  const minutes = madridMinutes(date);

  if (minutes >= 9 * 60 && minutes < 15 * 60) {
    return "XAUEUR";
  }

  if (minutes >= 15 * 60 + 30) {
    return "XAUUSD";
  }

  return "XAUUSD";
}

function sourceLabelForStatus(mt5Status: MT5Status | null, mockStatus: MockMarketStatus | null, streamSource: string): string {
  return mt5Status?.connected_to_mt5 ? "MT5" : mockStatus?.running ? "MOCK" : streamSource;
}

function drawingToolText(tool: DrawingTool): string {
  const labels: Record<DrawingTool, string> = {
    horizontal_line: "linea horizontal",
    vertical_line: "linea vertical",
    trend_line: "linea de tendencia",
    rectangle: "rectangulo",
    text: "texto",
    select: "seleccionar"
  };

  return labels[tool] ?? tool.replace(/_/g, " ");
}

function drawingToolIcon(tool: DrawingTool) {
  if (tool === "horizontal_line") return <Minus size={18} />;
  if (tool === "vertical_line") return <SeparatorVertical size={18} />;
  if (tool === "trend_line") return <TrendingUp size={18} />;
  if (tool === "rectangle") return <Square size={18} />;
  if (tool === "text") return <Type size={18} />;
  return <MousePointer size={18} />;
}

function torumAssetIcon(status: TorumV1Status | null, symbol: string): string {
  const asset = status?.assets?.[symbol];
  if (!asset) {
    return "";
  }
  if (asset.status === "UNLOCKED") {
    return "\u2705";
  }
  return "\u274c";
}

function torumAssetLabel(status: TorumV1Status | null, symbol: string): string {
  const icon = torumAssetIcon(status, symbol);
  return icon ? `${icon} ${symbol}` : symbol;
}

function torumTopbarAssetTone(status: TorumV1Status | null, symbol: string): "unlocked" | "locked" | null {
  if (!torumTopbarStatusSymbols.has(symbol)) {
    return null;
  }

  const asset = status?.assets?.[symbol];
  if (!asset) {
    return null;
  }

  return asset.status === "UNLOCKED" ? "unlocked" : "locked";
}

function isAnalysisOnlySymbol(symbol: string): boolean {
  return symbol.toUpperCase() === "DXY";
}

function pullbackLabelDecimals(label: string): number {
  const match = label.match(/\.(\d+)%/);
  return match ? match[1].length : 2;
}

function updateLivePullbackDebug(
  pullbacks: StrategyPullbackDebug[],
  observedLow: number | null,
  timeMsc: number
): StrategyPullbackDebug[] {
  if (observedLow === null || !Number.isFinite(observedLow) || pullbacks.length === 0) {
    return pullbacks;
  }

  const lastIndex = pullbacks.length - 1;
  const last = pullbacks[lastIndex];
  if (last.is_live !== true || observedLow >= last.pullback_low || last.swing_high <= 0) {
    return pullbacks;
  }

  const pullbackPct = ((last.swing_high - observedLow) / last.swing_high) * 100;
  const decimals = pullbackLabelDecimals(last.label);
  const next = [...pullbacks];
  next[lastIndex] = {
    ...last,
    pullback_low: observedLow,
    pullback_low_time: Math.floor(timeMsc / 1000),
    pullback_pct: pullbackPct,
    label: last.label ? `PB ${pullbackPct.toFixed(decimals)}%` : ""
  };
  return next;
}

function sameLivePullback(left: StrategyPullbackDebug, right: StrategyPullbackDebug): boolean {
  return (
    left.is_live === true &&
    right.is_live === true &&
    left.swing_high_time === right.swing_high_time &&
    Math.abs(left.swing_high - right.swing_high) < 0.0000001
  );
}

/**
 * Merge a server recalculation without ever raising the low of the current live
 * pullback. The current candle's wick is historical truth: a later tick or a
 * stale cached response may move the price up, but it cannot erase that low.
 */
function mergePullbackSnapshot(
  current: StrategyPullbackDebug[],
  incoming: StrategyPullbackDebug[]
): StrategyPullbackDebug[] {
  const next = clonePullbacks(incoming);
  if (current.length === 0 || next.length === 0) return next;

  const currentLive = current[current.length - 1];
  const incomingIndex = next.length - 1;
  const incomingLive = next[incomingIndex];
  if (!sameLivePullback(currentLive, incomingLive) || currentLive.pullback_low >= incomingLive.pullback_low) {
    return next;
  }

  const pullbackPct = ((incomingLive.swing_high - currentLive.pullback_low) / incomingLive.swing_high) * 100;
  const decimals = pullbackLabelDecimals(incomingLive.label || currentLive.label);
  next[incomingIndex] = {
    ...incomingLive,
    pullback_low: currentLive.pullback_low,
    pullback_low_time: currentLive.pullback_low_time,
    pullback_pct: pullbackPct,
    label: incomingLive.label ? `PB ${pullbackPct.toFixed(decimals)}%` : ""
  };
  return next;
}

function translateTradeMessage(message: string): string {
  return message
    .replace(/market closed/gi, "Mercado cerrado")
    .replace(/order rejected by risk manager/gi, "Orden rechazada por gestion de riesgo")
    .replace(/no price available/gi, "Sin precio disponible")
    .replace(/position is not open/gi, "La posicion no esta abierta")
    .replace(/failed to close position/gi, "No se pudo cerrar la posicion")
    .replace(/below/gi, "por debajo")
    .replace(/rejected/gi, "rechazada")
    .replace(/failed/gi, "fallo");
}

function pushStatusLabel(status: PushStatus): string {
  const labels: Record<PushStatus, string> = {
    unsupported: "Push no disponible en este navegador",
    denied: "Push bloqueado en permisos",
    "permission-required": "Push sin permiso",
    subscribed: "Push activo",
    ready: "Push listo",
    "missing-vapid": "Faltan claves VAPID"
  };

  return labels[status];
}

async function preparePushForPriceAlert(): Promise<PushStatus | null> {
  try {
    return await activatePushForPriceAlert();
  } catch {
    return null;
  }
}

function normalizeCandleTime(time: unknown): number {
  if (typeof time === "number") {
    if (!Number.isFinite(time)) {
      return 0;
    }

    return time > 10_000_000_000 ? Math.floor(time / 1000) : Math.floor(time);
  }

  if (typeof time === "string") {
    const parsed = Number(time);
    if (Number.isFinite(parsed)) {
      return parsed > 10_000_000_000 ? Math.floor(parsed / 1000) : Math.floor(parsed);
    }

    const parsedDate = Date.parse(time);
    return Number.isNaN(parsedDate) ? 0 : Math.floor(parsedDate / 1000);
  }

  if (typeof time === "object" && time !== null) {
    const source = time as { year?: unknown; month?: unknown; day?: unknown };
    const year = Number(source.year);
    const month = Number(source.month);
    const day = Number(source.day);
    if (Number.isInteger(year) && Number.isInteger(month) && Number.isInteger(day)) {
      return Math.floor(Date.UTC(year, month - 1, day) / 1000);
    }
  }

  return 0;
}

function normalizeDashboardCandle(candle: Candle): Candle | null {
  const time = normalizeCandleTime(candle.time);

  if (
    time <= 0 ||
    !Number.isFinite(candle.open) ||
    !Number.isFinite(candle.high) ||
    !Number.isFinite(candle.low) ||
    !Number.isFinite(candle.close)
  ) {
    return null;
  }

  return {
    ...candle,
    time
  };
}

function upsertCandle(candles: Candle[], update: Candle): Candle[] {
  const normalizedUpdate = normalizeDashboardCandle(update);

  if (!normalizedUpdate) {
    return candles;
  }

  const normalizedCandles = candles
    .map(normalizeDashboardCandle)
    .filter((candle): candle is Candle => candle !== null);

  const byTime = new Map<number, Candle>();

  for (const candle of normalizedCandles) {
    byTime.set(candle.time, candle);
  }

  byTime.set(normalizedUpdate.time, normalizedUpdate);

  return [...byTime.values()]
    .sort((a, b) => a.time - b.time)
    .slice(-candleCacheLimit);
}

const candleMemoryCache = new Map<string, Candle[]>();
const candlePersistenceTimers = new Map<string, number>();
const candlePrefetchInFlight = new Set<string>();
const candleCacheLimit = 5000;
const candleInitialLimit = 1000;
const candleNewerSyncLimit = 5000;
const candleOlderPageLimit = 500;
const drawingMemoryCache = new Map<string, ChartDrawingRead[]>();
const pullbackMemoryCache = new Map<string, StrategyPullbackDebug[]>();

function candleCacheKey(symbol: string, timeframe: Timeframe): string {
  return `${symbol.toUpperCase()}:${timeframe}`;
}

function drawingCacheKey(symbol: string, timeframe: Timeframe): string {
  return `${symbol.toUpperCase()}:${timeframe}`;
}

function pullbackCacheKey(symbol: string): string {
  return `${symbol.toUpperCase()}:M5`;
}

function clonePullbacks(pullbacks: StrategyPullbackDebug[]): StrategyPullbackDebug[] {
  return pullbacks.map((item) => ({ ...item }));
}

function drawingAffectsStrategy(drawing: Pick<ChartDrawingRead, "drawing_type" | "metadata">): boolean {
  const metadata = drawing.metadata ?? {};
  return Boolean(
    metadata.torum_v1_zone_enabled ||
    metadata.support_enabled ||
    metadata.supportLevel
  );
}

function cloneDrawings(drawings: ChartDrawingRead[]): ChartDrawingRead[] {
  return drawings.map((drawing) => ({ ...drawing, payload: { ...drawing.payload }, style: { ...drawing.style }, metadata: { ...drawing.metadata } }));
}

function readCachedDrawings(symbol: string, timeframe: Timeframe): ChartDrawingRead[] | null {
  const cached = drawingMemoryCache.get(drawingCacheKey(symbol, timeframe));
  return cached ? cloneDrawings(cached) : null;
}

function writeCachedDrawings(symbol: string, timeframe: Timeframe, drawings: ChartDrawingRead[]): ChartDrawingRead[] {
  const cloned = cloneDrawings(drawings);
  drawingMemoryCache.set(drawingCacheKey(symbol, timeframe), cloned);
  return cloneDrawings(cloned);
}

function cloneCandles(candles: Candle[]): Candle[] {
  return candles.map((candle) => ({ ...candle }));
}

function normalizeDashboardCandles(candles: Candle[], symbol?: string, timeframe?: Timeframe): Candle[] {
  const expectedSymbol = symbol?.toUpperCase();
  const byTime = new Map<number, Candle>();
  const normalizedCandles = sanitizeCandlesForCache(
    expectedSymbol ?? "",
    timeframe ?? "D1",
    candles
    .map(normalizeDashboardCandle)
    .filter((candle): candle is Candle => candle !== null)
    .filter((candle) => (expectedSymbol ? candle.internal_symbol.toUpperCase() === expectedSymbol : true))
    .filter((candle) => (timeframe ? candle.timeframe === timeframe : true))
  );

  for (const candle of normalizedCandles) {
    byTime.set(candle.time, candle);
  }

  return [...byTime.values()].sort((a, b) => a.time - b.time).slice(-candleCacheLimit);
}

function readCachedCandles(symbol: string, timeframe: Timeframe): Candle[] | null {
  const cached = candleMemoryCache.get(candleCacheKey(symbol, timeframe));
  if (!cached) {
    return null;
  }

  const normalizedCandles = normalizeDashboardCandles(cached, symbol, timeframe);
  candleMemoryCache.set(candleCacheKey(symbol, timeframe), normalizedCandles);
  return normalizedCandles.length > 0 ? cloneCandles(normalizedCandles) : null;
}


function schedulePersistedCandleWrite(symbol: string, timeframe: Timeframe): void {
  if (typeof window === "undefined") return;
  const key = candleCacheKey(symbol, timeframe);
  const existing = candlePersistenceTimers.get(key);
  if (existing !== undefined) window.clearTimeout(existing);
  const timer = window.setTimeout(() => {
    candlePersistenceTimers.delete(key);
    const current = candleMemoryCache.get(key);
    if (current) void writePersistedCandles(symbol, timeframe, current);
  }, 750);
  candlePersistenceTimers.set(key, timer);
}

function writeCachedCandles(symbol: string, timeframe: Timeframe, candles: Candle[]): Candle[] {
  const normalizedCandles = normalizeDashboardCandles(candles, symbol, timeframe);
  candleMemoryCache.set(candleCacheKey(symbol, timeframe), normalizedCandles);
  schedulePersistedCandleWrite(symbol, timeframe);
  return cloneCandles(normalizedCandles);
}

async function readAnyCachedCandles(symbol: string, timeframe: Timeframe): Promise<Candle[] | null> {
  const memoryCandles = readCachedCandles(symbol, timeframe);
  if (memoryCandles) {
    return memoryCandles;
  }

  const persistedCandles = await readPersistedCandles(symbol, timeframe);
  if (!persistedCandles) {
    return null;
  }

  return writeCachedCandles(symbol, timeframe, persistedCandles);
}

function mergeCandles(existing: Candle[], incoming: Candle[]): Candle[] {
  const byTime = new Map<number, Candle>();

  for (const candle of normalizeDashboardCandles(existing)) {
    byTime.set(candle.time, candle);
  }

  for (const candle of normalizeDashboardCandles(incoming)) {
    byTime.set(candle.time, candle);
  }

  return [...byTime.values()]
    .sort((a, b) => a.time - b.time)
    .slice(-candleCacheLimit);
}

function latestCandleTime(candles: Candle[] | null): number | null {
  if (!candles?.length) {
    return null;
  }

  return candles[candles.length - 1]?.time ?? null;
}

function oldestCandleTime(candles: Candle[] | null): number | null {
  if (!candles?.length) {
    return null;
  }

  return candles[0]?.time ?? null;
}

function patchCandlesWithLivePrice(candles: Candle[], price: number | null): Candle[] | null {
  if (price === null || !Number.isFinite(price) || candles.length === 0) {
    return null;
  }

  const normalizedCandles = normalizeDashboardCandles(candles);
  const last = normalizedCandles[normalizedCandles.length - 1];
  if (!last) {
    return null;
  }

  const nextLast: Candle = {
    ...last,
    close: price,
    high: Math.max(last.high, price),
    low: Math.min(last.low, price)
  };

  return [...normalizedCandles.slice(0, -1), nextLast];
}

function candlesBelongToMarket(candles: Candle[], symbol: string, timeframe: Timeframe): boolean {
  const last = candles[candles.length - 1];
  return last?.internal_symbol === symbol && last.timeframe === timeframe;
}

function patchCachedCandlesWithLivePrice(
  symbol: string,
  timeframe: Timeframe,
  price: number | null,
  visibleCandles?: Candle[]
): Candle[] | null {
  const key = candleCacheKey(symbol, timeframe);
  const cachedCandles = candleMemoryCache.get(key);
  const baseCandles =
    visibleCandles && visibleCandles.length > 0 && candlesBelongToMarket(visibleCandles, symbol, timeframe)
      ? visibleCandles
      : cachedCandles ?? [];
  const nextCandles = patchCandlesWithLivePrice(baseCandles, price);

  if (!nextCandles) {
    return null;
  }

  candleMemoryCache.set(key, nextCandles);
  return cloneCandles(nextCandles);
}

function livePriceFromMarketMessage(message: Extract<MarketMessage, { type: "latest_tick_update" | "market_tick" }>): number | null {
  return message.bid ?? message.last ?? message.ask ?? null;
}

function nearbyTimeframes(timeframe: Timeframe): Timeframe[] {
  const supportedNearby: Record<Timeframe, Timeframe[]> = {
    M1: ["M5"],
    M5: ["M1", "H1"],
    H1: ["M5", "H4"],
    H2: ["H1", "H3"],
    H3: ["H2", "H4"],
    H4: ["H1", "D1"],
    D1: ["H4", "W1"],
    W1: ["D1"]
  };

  return supportedNearby[timeframe] ?? [];
}

function prefetchNearbyCandles(symbol: string, timeframe: Timeframe) {
  for (const nearby of nearbyTimeframes(timeframe)) {
    const key = candleCacheKey(symbol, nearby);
    if (candleMemoryCache.has(key) || candlePrefetchInFlight.has(key)) {
      continue;
    }

    candlePrefetchInFlight.add(key);
    void getCandles(symbol, nearby)
      .then((candles) => {
        writeCachedCandles(symbol, nearby, candles);
      })
      .catch(() => {
        // Precarga ligera. Si falla, no molesta al grafico activo.
      })
      .finally(() => {
        candlePrefetchInFlight.delete(key);
      });
  }
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException
    ? error.name === "AbortError"
    : error instanceof Error && error.name === "AbortError";
}

function formatHistoryDate(value: string | null): string {
  if (!value) {
    return "--";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "--";
  }

  const pad = (part: number) => String(part).padStart(2, "0");
  return `${date.getFullYear()}.${pad(date.getMonth() + 1)}.${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

interface SplitMarketChartProps {
  accountCurrency: string;
  alertToolActive: boolean;
  chartSymbols: string[];
  drawingTool: DrawingTool;
  drawingsVisible: boolean;
  onSelectPosition: (positionId: number) => void;
  onUpdatePositionTp: (positionId: number, tp: number, closePrice?: number | null) => void | Promise<void>;
  positions: PositionRead[];
  tradeHistory: TradeHistoryItem[];
  tradeExecutionMarkerSettings: TradeExecutionMarkerSettings;
  chartDensity: ChartDensityOptions;
  selectedPositionId: number | null;
  symbolMappings: SymbolMapping[];
  symbolLabels: Record<string, string>;
  symbol: string;
  timeframe: Timeframe;
  onSymbolChange: (symbol: string) => void;
  showAskLine: boolean;
  showBidLine: boolean;
  showFutureNewsZones: boolean;
  autoExtendToFutureNews: boolean;
  showPullbackOverlays: boolean;
  onPullbackOverlayToggle: (visible: boolean) => void;
  strategyDebugPullbacks?: StrategyPullbackDebug[];
}

function SplitMarketChart({
  accountCurrency,
  alertToolActive,
  chartSymbols,
  drawingTool,
  drawingsVisible,
  onSelectPosition,
  onUpdatePositionTp,
  positions,
  tradeHistory,
  tradeExecutionMarkerSettings,
  chartDensity,
  selectedPositionId,
  symbolMappings,
  symbolLabels,
  symbol,
  timeframe,
  onSymbolChange,
  showAskLine,
  showBidLine,
  showFutureNewsZones,
  autoExtendToFutureNews,
  showPullbackOverlays,
  onPullbackOverlayToggle,
  strategyDebugPullbacks = []
}: SplitMarketChartProps) {
  const [candles, setCandles] = useState<Candle[]>([]);
  const [latestTick, setLatestTick] = useState<Tick | null>(null);
  const [loadingCandles, setLoadingCandles] = useState(false);
  const [noTradeZones, setNoTradeZones] = useState<NoTradeZone[]>([]);
  const [indicatorLines, setIndicatorLines] = useState<IndicatorLineOutput[]>([]);
  const [localStrategyDebugPullbacks, setLocalStrategyDebugPullbacks] = useState<StrategyPullbackDebug[]>([]);
  const [athZones, setAthZones] = useState<AthPriceZone[]>([]);
  const [priceAlerts, setPriceAlerts] = useState<PriceAlertRead[]>([]);
  const [drawings, setDrawings] = useState<ChartDrawingRead[]>([]);
  const [selectedDrawingId, setSelectedDrawingId] = useState<string | null>(null);
  const [autoFollowEnabled, setAutoFollowEnabled] = useState(true);
  const generationRef = useRef(0);
  const candleAbortRef = useRef<AbortController | null>(null);
  const candlesRef = useRef<Candle[]>([]);
  const splitDrawingMutationSeqRef = useRef(new Map<string, number>());
  const previousSplitSymbolRef = useRef(symbol);
  const visibleSplitLatestTick = latestTick?.internal_symbol === symbol ? latestTick : null;
  const latestBid = visibleSplitLatestTick?.bid ?? null;
  const latestAsk = visibleSplitLatestTick?.ask ?? null;
  const splitLiveTickFresh = visibleSplitLatestTick ? Date.now() - visibleSplitLatestTick.time_msc <= 45000 : false;
  const tradeLines = useMemo(
    () => tradeLinesForSymbol(positions, symbol, symbolMappings, latestBid, latestAsk, splitLiveTickFresh, accountCurrency, selectedPositionId),
    [accountCurrency, latestAsk, latestBid, positions, selectedPositionId, splitLiveTickFresh, symbol, symbolMappings]
  );
  const tradeExecutionMarkers = useMemo(
    () => buildTradeExecutionMarkers(positions, tradeHistory, symbol, timeframe, tradeExecutionMarkerSettings),
    [positions, tradeExecutionMarkerSettings, tradeHistory, symbol, timeframe]
  );

  useEffect(() => {
    candlesRef.current = candles;
  }, [candles]);

  useEffect(() => {
    const symbolChanged = previousSplitSymbolRef.current !== symbol;
    previousSplitSymbolRef.current = symbol;
    generationRef.current += 1;
    const generation = generationRef.current;
    const analysisOnly = isAnalysisOnlySymbol(symbol);
    const from = new Date(Date.now() - 14 * 24 * 60 * 60 * 1000).toISOString();
    const to = new Date(Date.now() + futureOverlayLookaheadDays * 24 * 60 * 60 * 1000).toISOString();
    const cachedCandles = readCachedCandles(symbol, timeframe);
    if (cachedCandles) {
      setCandles(cachedCandles);
    } else {
      setCandles([]);
    }
    setNoTradeZones([]);
    setIndicatorLines([]);
    setLocalStrategyDebugPullbacks([]);
    setAthZones([]);
    setPriceAlerts([]);
    const cachedDrawings = readCachedDrawings(symbol, timeframe);
    if (symbolChanged) {
      setDrawings(cachedDrawings ?? []);
      setSelectedDrawingId(null);
    } else if (cachedDrawings) {
      setDrawings(cachedDrawings);
      setSelectedDrawingId((current) => (current && cachedDrawings.some((drawing) => drawing.id === current) ? current : null));
    }
    setAutoFollowEnabled(true);

    async function refresh() {
      setLoadingCandles(true);
      candleAbortRef.current?.abort();
      const controller = new AbortController();
      candleAbortRef.current = controller;

      try {
        const cachedBeforeFetch = await readAnyCachedCandles(symbol, timeframe);
        if (generation !== generationRef.current) {
          return;
        }

        if (cachedBeforeFetch) {
          setCandles(cachedBeforeFetch);
        }

        if (!analysisOnly) {
        void getTicks(symbol, 1)
          .then((ticks) => {
            if (generation === generationRef.current) setLatestTick(ticks[ticks.length - 1] ?? null);
          })
          .catch(() => {
            if (generation === generationRef.current) setLatestTick(null);
          });
        } else {
          setLatestTick(null);
        }

        void getChartOverlays(symbol, timeframe, from, to)
          .then((overlays) => {
            if (generation !== generationRef.current) return;
            setNoTradeZones(overlays.no_trade_zones ?? []);
            setIndicatorLines(overlays.indicators.filter(isLineOutput) ?? []);
            // Pullbacks have a dedicated cached endpoint; do not block all overlays on their calculation.
            setAthZones(overlays.ath_zones ?? []);
            setPriceAlerts(overlays.price_alerts ?? []);
          })
          .catch(() => {
            if (generation !== generationRef.current) return;
            setNoTradeZones([]);
            setIndicatorLines([]);
            setLocalStrategyDebugPullbacks([]);
            setAthZones([]);
            setPriceAlerts([]);
          });

        if (showPullbackOverlays) {
          const cachedPullbacks = pullbackMemoryCache.get(pullbackCacheKey(symbol));
          if (cachedPullbacks) setLocalStrategyDebugPullbacks(clonePullbacks(cachedPullbacks));
          void getTorumV1Pullbacks(symbol, { limit: 600 })
            .then((response) => {
              if (generation !== generationRef.current) return;
              startTransition(() => {
                setLocalStrategyDebugPullbacks((current) => {
                  const merged = mergePullbackSnapshot(current, response.pullbacks);
                  pullbackMemoryCache.set(pullbackCacheKey(symbol), clonePullbacks(merged));
                  return merged;
                });
              });
            })
            .catch(() => undefined);
        } else {
          setLocalStrategyDebugPullbacks([]);
        }

        void getDrawings(symbol, timeframe, true)
          .then((nextDrawings) => {
            if (generation !== generationRef.current) return;
            const cached = writeCachedDrawings(symbol, timeframe, nextDrawings);
            setDrawings(cached);
            setSelectedDrawingId((current) => (current && cached.some((drawing) => drawing.id === current) ? current : null));
          })
          .catch(() => {
            if (generation !== generationRef.current) return;
            if (symbolChanged) {
              setDrawings([]);
              setSelectedDrawingId(null);
            }
          });

        const nextCandles = await getCandles(symbol, timeframe, candleInitialLimit, { signal: controller.signal });

        if (generation !== generationRef.current) {
          return;
        }

        const mergedCandles = writeCachedCandles(symbol, timeframe, mergeCandles(cachedBeforeFetch ?? [], nextCandles));

        setCandles(mergedCandles);
        prefetchNearbyCandles(symbol, timeframe);

        const after = latestCandleTime(cachedBeforeFetch);
        if (after) {
          void getCandles(symbol, timeframe, candleNewerSyncLimit, { signal: controller.signal, after })
            .then((newerCandles) => {
              if (generation !== generationRef.current || newerCandles.length === 0) return;
              setCandles((current) => writeCachedCandles(symbol, timeframe, mergeCandles(current, newerCandles)));
            })
            .catch(() => undefined);
        }

        const before = oldestCandleTime(mergedCandles);
        if (before) {
          void getCandles(symbol, timeframe, candleOlderPageLimit, { signal: controller.signal, before })
            .then((olderCandles) => {
              if (generation !== generationRef.current || olderCandles.length === 0) return;
              setCandles((current) => writeCachedCandles(symbol, timeframe, mergeCandles(olderCandles, current)));
            })
            .catch(() => undefined);
        }
      } catch (requestError) {
        if (isAbortError(requestError)) {
          return;
        }

        if (generation !== generationRef.current) {
          return;
        }

        setLatestTick(null);
        setNoTradeZones([]);
        setIndicatorLines([]);
        setLocalStrategyDebugPullbacks([]);
        setAthZones([]);
        setPriceAlerts([]);
        if (symbolChanged) {
          setDrawings([]);
          setSelectedDrawingId(null);
        }
      } finally {
        if (candleAbortRef.current === controller) {
          candleAbortRef.current = null;
        }
        if (generation === generationRef.current && candleAbortRef.current === null) {
          setLoadingCandles(false);
        }
      }
    }

    void refresh();

    if (analysisOnly) {
      return () => {
        candleAbortRef.current?.abort();
      };
    }

    const socket = new MarketSocketManager({
      onMessage: (message) => {
        if (generation !== generationRef.current) {
          return;
        }

        if (message.type === "candle_update" && message.symbol === symbol && message.timeframe === timeframe) {
          const previousLatestTime = candlesRef.current[candlesRef.current.length - 1]?.time ?? null;
          const isNewM5Candle = timeframe === "M5" && previousLatestTime !== null && message.candle.time > previousLatestTime;
          setCandles((current) => {
            const next = upsertCandle(current, message.candle);
            return writeCachedCandles(symbol, timeframe, next);
          });
          if (showPullbackOverlays && timeframe === "M5") {
            setLocalStrategyDebugPullbacks((current) => {
              const next = updateLivePullbackDebug(current, message.candle.low, message.candle.time * 1000);
              pullbackMemoryCache.set(pullbackCacheKey(symbol), clonePullbacks(next));
              return next;
            });
            if (isNewM5Candle) {
              void getTorumV1Pullbacks(symbol, { force: true, limit: 600 })
                .then((response) => {
                  if (generation !== generationRef.current) return;
                  setLocalStrategyDebugPullbacks((current) => {
                    const merged = mergePullbackSnapshot(current, response.pullbacks);
                    pullbackMemoryCache.set(pullbackCacheKey(symbol), clonePullbacks(merged));
                    return merged;
                  });
                })
                .catch(() => undefined);
            }
          }
          return;
        }

        if ((message.type === "latest_tick_update" || message.type === "market_tick") && message.symbol === symbol) {
          const parsedMessageTime = Date.parse(message.time);
          const messageTimeMsc = message.time_msc ?? (Number.isFinite(parsedMessageTime) ? parsedMessageTime : Date.now());
          setLatestTick((current) => {
            if (current && messageTimeMsc < current.time_msc) {
              return current;
            }

            return {
              time: message.time,
              time_msc: messageTimeMsc,
              internal_symbol: message.symbol,
              broker_symbol: message.broker_symbol ?? "",
              bid: message.bid,
              ask: message.ask,
              last: message.last,
              volume: message.volume,
              source: message.source ?? "UNKNOWN"
            };
          });
          if (showPullbackOverlays) {
            const liveLow = message.bid ?? message.last ?? message.ask ?? null;
            setLocalStrategyDebugPullbacks((current) => {
              const next = updateLivePullbackDebug(current, liveLow, messageTimeMsc);
              pullbackMemoryCache.set(pullbackCacheKey(symbol), clonePullbacks(next));
              return next;
            });
          }
          // MarketChart applies the live price directly with series.update().
        }
      },
      onReconnect: () => {
        if (generation === generationRef.current) {
          void refresh();
        }
      },
      onStatusChange: () => undefined
    });

    socket.connect(symbol, timeframe);

    return () => {
      candleAbortRef.current?.abort();
      socket.disconnect();
    };
  }, [symbol, timeframe]);

  async function handleCreateDrawing(drawing: ChartDrawingCreate) {
    const temporaryId = `local-${crypto.randomUUID()}`;
    const now = new Date().toISOString();
    const optimistic: ChartDrawingRead = {
      id: temporaryId, user_id: 0, internal_symbol: drawing.internal_symbol, timeframe: drawing.timeframe ?? null,
      drawing_type: drawing.drawing_type, name: drawing.name ?? null, payload: { ...drawing.payload },
      style: { ...(drawing.style ?? {}) }, metadata: { ...(drawing.metadata ?? {}) }, locked: drawing.locked ?? false,
      visible: drawing.visible ?? true, source: drawing.source ?? "MANUAL", revision: 0, created_at: now, updated_at: now
    };
    setDrawings((current) => writeCachedDrawings(symbol, timeframe, [...current, optimistic]));
    setSelectedDrawingId(temporaryId);
    try {
      const created = await createDrawing(drawing);
      setDrawings((current) => writeCachedDrawings(symbol, timeframe, current.map((item) => item.id === temporaryId ? created : item)));
      setSelectedDrawingId((current) => current === temporaryId ? created.id : current);
    } catch (error) {
      setDrawings((current) => writeCachedDrawings(symbol, timeframe, current.filter((item) => item.id !== temporaryId)));
      throw error;
    }
  }

  async function handleUpdateDrawing(drawing: ChartDrawingRead, patch: ChartDrawingUpdate) {
    if (drawing.id.startsWith("local-")) return;
    const previous = drawings.find((item) => item.id === drawing.id) ?? drawing;
    const sequence = (splitDrawingMutationSeqRef.current.get(drawing.id) ?? 0) + 1;
    splitDrawingMutationSeqRef.current.set(drawing.id, sequence);
    const optimistic = {
      ...previous,
      ...patch,
      payload: patch.payload ?? previous.payload,
      style: patch.style ?? previous.style,
      metadata: patch.metadata ?? previous.metadata,
      updated_at: new Date().toISOString()
    };
    setDrawings((current) => writeCachedDrawings(symbol, timeframe, current.map((item) => item.id === drawing.id ? optimistic : item)));
    try {
      const updated = await patchDrawing(drawing.id, { ...patch, expected_revision: previous.revision });
      if (splitDrawingMutationSeqRef.current.get(drawing.id) !== sequence) return;
      setDrawings((current) => writeCachedDrawings(symbol, timeframe, current.map((item) => item.id === updated.id ? updated : item)));
    } catch (error) {
      if (splitDrawingMutationSeqRef.current.get(drawing.id) === sequence) {
        setDrawings((current) => writeCachedDrawings(symbol, timeframe, current.map((item) => item.id === previous.id ? previous : item)));
      }
      throw error;
    }
  }

  async function handleDeleteDrawing(drawingId: string) {
    const previous = drawings.find((item) => item.id === drawingId);
    if (!previous) return;
    setDrawings((current) => writeCachedDrawings(symbol, timeframe, current.filter((drawing) => drawing.id !== drawingId)));
    setSelectedDrawingId((current) => (current === drawingId ? null : current));
    try {
      if (!drawingId.startsWith("local-")) await deleteDrawing(drawingId);
    } catch (error) {
      setDrawings((current) => writeCachedDrawings(symbol, timeframe, current.some((item) => item.id === previous.id) ? current : [...current, previous]));
      throw error;
    }
  }

  async function handleCreatePriceAlert(price: number) {
    await preparePushForPriceAlert();
    const alert = await createPriceAlert({
      internal_symbol: symbol,
      timeframe: null,
      target_price: price,
      message: `${symbol} <= ${price.toFixed(2)}`,
      source: "CHART"
    });
    setPriceAlerts((current) => [...current, alert]);
  }

  async function handleUpdatePriceAlert(alert: PriceAlertRead, targetPrice: number) {
    const updated = await patchPriceAlert(alert.id, {
      target_price: targetPrice,
      message: `${alert.internal_symbol} <= ${targetPrice.toFixed(2)}`
    });
    setPriceAlerts((current) => current.map((item) => (item.id === updated.id ? updated : item)));
  }

  async function handleCancelPriceAlert(alertId: string) {
    const removedAlert = priceAlerts.find((alert) => alert.id === alertId) ?? null;
    setPriceAlerts((current) => current.filter((alert) => alert.id !== alertId));
    try {
      await cancelPriceAlert(alertId);
    } catch {
      if (removedAlert) {
        setPriceAlerts((current) => (current.some((alert) => alert.id === alertId) ? current : [...current, removedAlert]));
      }
    }
  }

  return (
    <div className="chart-split-pane chart-split-pane--secondary">
      <div className="chart-split-pane__controls" onPointerDown={(event) => event.stopPropagation()}>
        <select aria-label="Simbolo grafico" value={symbol} onChange={(event) => onSymbolChange(event.target.value)}>
          {chartSymbols.map((item) => (
            <option key={item} value={item}>
              {symbolLabels[item] ?? item}
            </option>
          ))}
        </select>
      </div>
      <div className="chart-split-pane__chart">
        <MarketChart
          alertToolActive={alertToolActive}
          askPrice={latestTick?.ask ?? null}
          autoFollowEnabled
          autoExtendToFutureNews={autoExtendToFutureNews}
          bidPrice={latestTick?.bid ?? null}
          livePrice={latestTick?.bid ?? latestTick?.last ?? latestTick?.ask ?? null}
          candles={candles}
          centerRequestKey={`${symbol}:${timeframe}`}
          drawingTool={drawingTool}
          drawings={drawingsVisible ? drawings.filter((drawing) => drawing.visible) : []}
          indicatorLines={indicatorLines}
          athZones={athZones}
          strategyDebugPullbacks={strategyDebugPullbacks.length > 0 ? strategyDebugPullbacks : localStrategyDebugPullbacks}
          loadingCandles={loadingCandles}
          preferredBarSpacing={chartDensity.barSpacing}
          minimumBarSpacing={chartDensity.minBarSpacing}
          noTradeZones={noTradeZones}
          onCancelPriceAlert={(alertId) => void handleCancelPriceAlert(alertId)}
          onCreateDrawing={(drawing) => void handleCreateDrawing(drawing)}
          onCreatePriceAlert={(price) => void handleCreatePriceAlert(price)}
          onDeleteDrawing={(drawingId) => void handleDeleteDrawing(drawingId)}
          onAutoFollowChange={setAutoFollowEnabled}
          onSelectDrawing={setSelectedDrawingId}
          onSelectPosition={onSelectPosition}
          onUpdateDrawing={handleUpdateDrawing}
          onUpdatePriceAlert={(alert, price) => void handleUpdatePriceAlert(alert, price)}
          onUpdatePositionTp={(positionId, tp, closePrice) => onUpdatePositionTp(positionId, tp, closePrice)}
          priceAlerts={priceAlerts}
          resetKey={`${symbol}:${timeframe}`}
          selectedDrawingId={selectedDrawingId}
          showAskLine={showAskLine}
          showBidLine={showBidLine}
          showFutureNewsZones={showFutureNewsZones}
          pullbackDebugVisible={showPullbackOverlays}
          onPullbackDebugToggle={onPullbackOverlayToggle}
          symbol={symbol}
          timeframe={timeframe}
          tradeLines={tradeLines}
          tradeExecutionMarkers={tradeExecutionMarkers}
        />
      </div>
    </div>
  );
}

interface TradingDashboardProps {
  activeView?: MobileView;
  onActiveViewChange?: (view: MobileView) => void;
}

export function TradingDashboard({ activeView: controlledActiveView, onActiveViewChange }: TradingDashboardProps = {}) {
  const [selectedSymbol, setSelectedSymbol] = useState(readInitialSymbol);
  const [selectedTimeframe, setSelectedTimeframe] = useState<Timeframe>("M5");
  const [symbolMappings, setSymbolMappings] = useState<SymbolMapping[]>([]);
  const [candles, setCandles] = useState<Candle[]>([]);
  const [mockStatus, setMockStatus] = useState<MockMarketStatus | null>(null);
  const [mt5Status, setMt5Status] = useState<MT5Status | null>(null);
  const [streamConnected, setStreamConnected] = useState(false);
  const [socketStatus, setSocketStatus] = useState<MarketSocketStatus>("disconnected");
  const [streamSource, setStreamSource] = useState("MOCK");
  const [lastTickTime, setLastTickTime] = useState<string | null>(null);
  const [latestTick, setLatestTick] = useState<Tick | null>(null);
  const [backendLatestTick, setBackendLatestTick] = useState<LatestTickDiagnostic | null>(null);
  const [tradingSettings, setTradingSettings] = useState<TradingSettings | null>(null);
  const [tradeExecutionMarkerSettings, setTradeExecutionMarkerSettings] = useState<TradeExecutionMarkerSettings>(() => readTradeExecutionMarkerSettings());
  const [chartDensity, setChartDensity] = useState<ChartDensityOptions>(() => readChartDensity());
  const [torumV1Status, setTorumV1Status] = useState<TorumV1Status | null>(null);
  const [loadingCandles, setLoadingCandles] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tradeMessage, setTradeMessage] = useState<string | null>(null);
  const [pendingOrderMarker, setPendingOrderMarker] = useState<TradeMarker | null>(null);
  const [appVisible, setAppVisible] = useState(() => (typeof document === "undefined" ? true : document.visibilityState !== "hidden"));
  const [resumeGraceUntil, setResumeGraceUntil] = useState(0);
  const [orders, setOrders] = useState<OrderRead[]>([]);
  const [positions, setPositions] = useState<PositionRead[]>([]);
  const [tradeHistory, setTradeHistory] = useState<TradeHistoryItem[]>([]);
  const [selectedPositionId, setSelectedPositionId] = useState<number | null>(null);
  const [closePositionId, setClosePositionId] = useState<number | null>(null);
  const [closingPosition, setClosingPosition] = useState(false);
  const [pendingClosingPositionIds, setPendingClosingPositionIds] = useState<Set<number>>(() => new Set());
  const [noTradeZones, setNoTradeZones] = useState<NoTradeZone[]>([]);
  const [indicatorLines, setIndicatorLines] = useState<IndicatorLineOutput[]>([]);
  const [strategyDebugPullbacks, setStrategyDebugPullbacks] = useState<StrategyPullbackDebug[]>([]);
  const [athZones, setAthZones] = useState<AthPriceZone[]>([]);
  const [drawings, setDrawings] = useState<ChartDrawingRead[]>([]);
  const [drawingTool, setDrawingTool] = useState<DrawingTool>("select");
  const [selectedDrawingId, setSelectedDrawingId] = useState<string | null>(null);
  const [drawingsVisible, setDrawingsVisible] = useState(true);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [systemStatusOpen, setSystemStatusOpen] = useState(false);
  const [internalActiveView, setInternalActiveView] = useState<MobileView>("chart");
  const [alertToolActive, setAlertToolActive] = useState(false);
  const [drawingMenuOpen, setDrawingMenuOpen] = useState(false);
  const [chartSplitCount, setChartSplitCount] = useState<ChartSplitCount>(1);
  const [chartSplitOrientation, setChartSplitOrientation] = useState<ChartSplitOrientation>("vertical");
  const [secondaryCharts, setSecondaryCharts] = useState<SplitChartSelection[]>([
    { symbol: "XAUEUR" },
    { symbol: "DXY" }
  ]);
  const [spyModeEnabled, setSpyModeEnabled] = useState(readSpyModePreference);
  const [showFutureNewsZones, setShowFutureNewsZones] = useState(() => readDefaultTruePreference(showFutureNewsZonesStorageKey));
  const [autoExtendToFutureNews, setAutoExtendToFutureNews] = useState(() => readDefaultTruePreference(autoExtendToFutureNewsStorageKey));
  const [showPullbackOverlays, setShowPullbackOverlays] = useState(() => readDefaultTruePreference(showPullbackOverlaysStorageKey));
  const [chartAutoFollowEnabled, setChartAutoFollowEnabled] = useState(true);
  const [chartRecenterToken, setChartRecenterToken] = useState(0);
  const [chartSymbolResetToken, setChartSymbolResetToken] = useState(0);
  const [chartHardResetToken, setChartHardResetToken] = useState(0);
  const [priceAlerts, setPriceAlerts] = useState<PriceAlertRead[]>([]);
  const [priceAlertHistory, setPriceAlertHistory] = useState<PriceAlertRead[]>([]);
  const [historyTab, setHistoryTab] = useState<"OPEN" | "CLOSED">("OPEN");
  const [historyVisibleCount, setHistoryVisibleCount] = useState(100);
  const [expandedHistoryRows, setExpandedHistoryRows] = useState<Set<string>>(() => new Set());
  const previousSymbolRef = useRef(selectedSymbol);
  const pendingClosingPositionIdsRef = useRef<Set<number>>(new Set());
  const latestTickBySymbolRef = useRef<Map<string, Tick>>(new Map());
  const pendingTickRef = useRef<Tick | null>(null);
  const tickFrameRef = useRef<number | null>(null);
  const tickCounterRef = useRef(0);
  const drawingMutationSeqRef = useRef<Map<string, number>>(new Map());
  const pullbackRequestSeqRef = useRef(0);
  const socketManagerRef = useRef<MarketSocketManager | null>(null);
  const marketGenerationRef = useRef(0);
  const tradingRefreshGenerationRef = useRef(0);
  const tradingMutationVersionRef = useRef(0);
  const tradingRefreshPromiseRef = useRef<Promise<void> | null>(null);
  const tradingRefreshQueuedRef = useRef(false);
  const candleAbortRef = useRef<AbortController | null>(null);
  const activeMarketKeyRef = useRef(`${selectedSymbol}:${selectedTimeframe}`);
  const pullbackOverlayRefreshAtRef = useRef(0);
  const [ticksPerSecond, setTicksPerSecond] = useState(0);
  const activeMobileView = controlledActiveView ?? internalActiveView;

  function setPendingClosing(positionId: number, pending: boolean) {
    const next = new Set(pendingClosingPositionIdsRef.current);
    if (pending) {
      next.add(positionId);
    } else {
      next.delete(positionId);
    }
    pendingClosingPositionIdsRef.current = next;
    setPendingClosingPositionIds(next);
  }

  function patchOpenPositionsWithTick(tick: Tick) {
    setPositions((current) =>
      current.map((position) => {
        if (position.internal_symbol !== tick.internal_symbol || !isReallyOpenPosition(position)) {
          return position;
        }

        const closePrice =
          position.side === "BUY"
            ? tick.bid ?? tick.last ?? tick.ask ?? null
            : tick.ask ?? tick.last ?? tick.bid ?? null;

        if (closePrice === null || !Number.isFinite(closePrice) || position.current_price === closePrice) {
          return position;
        }

        return { ...position, current_price: closePrice };
      })
    );
  }

  function flushPendingTick() {
    tickFrameRef.current = null;
    const tick = pendingTickRef.current;
    pendingTickRef.current = null;
    if (!tick || tick.internal_symbol !== selectedSymbol) return;

    latestTickBySymbolRef.current.set(tick.internal_symbol, tick);
    setLatestTick((current) => (current && current.time_msc > tick.time_msc ? current : tick));
    patchOpenPositionsWithTick(tick);

    const livePrice = tick.bid ?? tick.last ?? tick.ask ?? null;
    // Persist candles only on candle events; rewriting thousands of cached bars on
    // every tick caused avoidable CPU and IndexedDB churn.
    if (showPullbackOverlays) {
      setStrategyDebugPullbacks((current) => {
        const next = updateLivePullbackDebug(current, livePrice, tick.time_msc);
        pullbackMemoryCache.set(pullbackCacheKey(selectedSymbol), clonePullbacks(next));
        return next;
      });
    }
    setStreamSource(tick.source ?? "UNKNOWN");
    setLastTickTime(tick.time);
  }

  function queueTickForUi(tick: Tick) {
    pendingTickRef.current = tick;
    tickCounterRef.current += 1;
    if (tickFrameRef.current === null) {
      // 20 Hz is visually fluid while avoiding a full dashboard render per market tick.
      tickFrameRef.current = window.setTimeout(flushPendingTick, 50);
    }
  }

  function setActiveMobileView(view: MobileView) {
    setInternalActiveView(view);
    onActiveViewChange?.(view);
  }

  useEffect(() => {
    setPendingOrderMarker(null);
  }, [selectedSymbol]);

  useEffect(() => {
    const interval = window.setInterval(() => {
      setTicksPerSecond(tickCounterRef.current);
      tickCounterRef.current = 0;
    }, 1000);
    return () => {
      window.clearInterval(interval);
      if (tickFrameRef.current !== null) {
        window.clearTimeout(tickFrameRef.current);
        tickFrameRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    if (!("serviceWorker" in navigator)) {
      return;
    }

    function handleServiceWorkerMessage(event: MessageEvent) {
      const data = event.data as { type?: string; symbol?: string } | null;
      if (data?.type !== "price_alert_notification_click" || !data.symbol) {
        return;
      }

      handleSymbolChange(data.symbol);
      setActiveMobileView("chart");
    }

    navigator.serviceWorker.addEventListener("message", handleServiceWorkerMessage);
    return () => navigator.serviceWorker.removeEventListener("message", handleServiceWorkerMessage);
  }, []);

  useEffect(() => {
    if (!drawingMenuOpen) {
      return;
    }

    function handlePointerDown(event: PointerEvent) {
      const target = event.target as Element | null;
      if (target?.closest(".mobile-drawing-menu") || target?.closest("[data-mobile-drawing-toggle]")) {
        return;
      }
      setDrawingMenuOpen(false);
    }

    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [drawingMenuOpen]);

  useEffect(() => {
    const root = document.documentElement;

    function syncVisualViewportHeight() {
      const height = window.visualViewport?.height ?? window.innerHeight;
      root.style.setProperty("--torum-visual-height", `${height}px`);
    }

    syncVisualViewportHeight();
    window.visualViewport?.addEventListener("resize", syncVisualViewportHeight);
    window.addEventListener("resize", syncVisualViewportHeight);

    return () => {
      window.visualViewport?.removeEventListener("resize", syncVisualViewportHeight);
      window.removeEventListener("resize", syncVisualViewportHeight);
      root.style.removeProperty("--torum-visual-height");
    };
  }, []);

  useEffect(() => {
    if (!tradeMessage) {
      return;
    }

    const timeoutId = window.setTimeout(() => setTradeMessage(null), 3000);
    return () => window.clearTimeout(timeoutId);
  }, [tradeMessage]);

  useEffect(() => {
    function handleSpyModeChange() {
      setSpyModeEnabled(readSpyModePreference());
    }

    window.addEventListener("torum-spy-mode-changed", handleSpyModeChange);
    window.addEventListener("storage", handleSpyModeChange);
    return () => {
      window.removeEventListener("torum-spy-mode-changed", handleSpyModeChange);
      window.removeEventListener("storage", handleSpyModeChange);
    };
  }, []);

  useEffect(() => {
    function handleFutureNewsVisualsChange() {
      setShowFutureNewsZones(readDefaultTruePreference(showFutureNewsZonesStorageKey));
      setAutoExtendToFutureNews(readDefaultTruePreference(autoExtendToFutureNewsStorageKey));
    }

    window.addEventListener(futureNewsVisualsChangedEvent, handleFutureNewsVisualsChange);
    window.addEventListener("storage", handleFutureNewsVisualsChange);
    return () => {
      window.removeEventListener(futureNewsVisualsChangedEvent, handleFutureNewsVisualsChange);
      window.removeEventListener("storage", handleFutureNewsVisualsChange);
    };
  }, []);

  const selectedMapping = useMemo(
    () => symbolMappings.find((mapping) => mapping.internal_symbol === selectedSymbol),
    [selectedSymbol, symbolMappings]
  );
  const chartSymbols = useMemo(
    () =>
      symbolMappings.length > 0
        ? symbolMappings
            .filter((mapping) => mapping.enabled && !deprecatedSymbols.has(mapping.internal_symbol))
            .map((mapping) => mapping.internal_symbol)
        : fallbackSymbols,
    [symbolMappings]
  );
  const strategySymbolLabels = useMemo(
    () => Object.fromEntries(chartSymbols.map((symbol) => [symbol, torumAssetLabel(torumV1Status, symbol)])),
    [chartSymbols, torumV1Status]
  );
  const topbarSymbolStatusTones = useMemo(
    () =>
      Object.fromEntries(
        chartSymbols
          .map((symbol) => [symbol, torumTopbarAssetTone(torumV1Status, symbol)] as const)
          .filter((entry): entry is readonly [string, "unlocked" | "locked"] => entry[1] !== null)
      ),
    [chartSymbols, torumV1Status]
  );
  useEffect(() => {
    setSecondaryCharts((current) =>
      current.map((chart, index) => ({
        symbol: chartSymbols.includes(chart.symbol) ? chart.symbol : (chartSymbols[index + 1] ?? chartSymbols[0] ?? selectedSymbol),
      }))
    );
  }, [chartSymbols, selectedSymbol]);

  const currentCandle = candles.length > 0 ? candles[candles.length - 1] : undefined;
  const visibleLatestTick = latestTick?.internal_symbol === selectedSymbol ? latestTick : null;
  const latestBid = visibleLatestTick?.bid ?? null;
  const latestAsk = visibleLatestTick?.ask ?? null;
  const lastPrice = latestBid ?? undefined;
  const frontendTickAgeMs = visibleLatestTick ? Math.max(0, Date.now() - visibleLatestTick.time_msc) : null;
  const liveTickFresh = frontendTickAgeMs !== null && frontendTickAgeMs <= 45000;
  const mt5LastTickTime = mt5Status?.last_tick_time_by_symbol[selectedSymbol] ?? null;
  const mt5LastTickAgeMs = mt5LastTickTime ? Math.max(0, Date.now() - Date.parse(mt5LastTickTime)) : null;
  const backendTickAgeMs = backendLatestTick?.age_ms ?? null;
  const effectiveTickAgeMs = frontendTickAgeMs ?? mt5LastTickAgeMs ?? backendTickAgeMs;
  const mt5StatusAgeMs = mt5Status?.updated_at ? Math.max(0, Date.now() - Date.parse(mt5Status.updated_at)) : null;
  const mt5HeartbeatHealthy =
    Boolean(mt5Status?.connected_to_mt5 && mt5Status.connected_to_backend) && mt5StatusAgeMs !== null && mt5StatusAgeMs <= 45000;
  const tickOldOrMissing = effectiveTickAgeMs === null || effectiveTickAgeMs > 30000;
  const selectedAnalysisOnly = Boolean(selectedMapping?.analysis_only) || isAnalysisOnlySymbol(selectedSymbol);
  const resumeGraceActive = appVisible && resumeGraceUntil > 0 && Date.now() < resumeGraceUntil;
  const marketClosedWarning =
    appVisible &&
    !resumeGraceActive &&
    !selectedAnalysisOnly &&
    socketStatus === "connected" &&
    mt5HeartbeatHealthy &&
    tickOldOrMissing &&
    sourceLabelForStatus(mt5Status, mockStatus, streamSource) === "MT5";
  const staleSignals = socketStatus === "stale" || socketStatus === "reconnecting" || socketStatus === "disconnected" || tickOldOrMissing;
  const marketDataStale = selectedAnalysisOnly ? false : appVisible && !resumeGraceActive && staleSignals;
  const marketConnectionHealthy = selectedAnalysisOnly ? true : socketStatus === "connected" && !marketDataStale;
  const staleTradingReason = marketClosedWarning ? "Mercado cerrado" : "Datos desconectados o desactualizados. Reconectando...";
  const sourceLabel = mt5Status?.connected_to_mt5 ? "MT5" : mockStatus?.running ? "MOCK" : streamSource;
  const connectionStatusForUi: MarketSocketStatus =
    resumeGraceActive && (socketStatus === "reconnecting" || socketStatus === "stale" || socketStatus === "disconnected")
      ? "connected"
      : socketStatus;
  const streamConnectedForUi = streamConnected || resumeGraceActive;
  const streamStatusLabel =
    selectedAnalysisOnly
      ? "Solo analisis"
      : marketClosedWarning
        ? "Mercado cerrado"
        : connectionStatusForUi === "connected"
      ? "Stream conectado"
      : connectionStatusForUi === "reconnecting"
        ? "Reconectando"
        : connectionStatusForUi === "stale"
          ? "Datos stale"
          : connectionStatusForUi === "connecting"
            ? "Conectando"
            : "Stream desconectado";
  const streamStatusTone = selectedAnalysisOnly
    ? "neutral"
    : marketClosedWarning
    ? "warning"
    : connectionStatusForUi === "connected"
      ? "success"
      : connectionStatusForUi === "reconnecting" || connectionStatusForUi === "stale" || connectionStatusForUi === "connecting"
        ? "warning"
        : "danger";
  const accountMode = mt5Status?.account_trade_mode ?? "UNKNOWN";
  const accountCurrency = mt5Status?.account?.currency ?? "EUR";
  const symbolTradable = selectedMapping ? selectedMapping.tradable && !selectedMapping.analysis_only : !selectedAnalysisOnly;
  const visibleTimeframes = selectedAnalysisOnly ? dxyTimeframes : timeframes;
  const symbolTradingNotice = selectedMapping?.analysis_only
    ? `${selectedSymbol} es un activo de analisis. Trading deshabilitado.`
    : `${selectedSymbol} no esta habilitado para trading.`;
  
  
const tradeMarkers = useMemo<TradeMarker[]>(() => (pendingOrderMarker ? [pendingOrderMarker] : []), [pendingOrderMarker]);


  const tradeLines = useMemo(
  () => tradeLinesForSymbol(positions, selectedSymbol, symbolMappings, latestBid, latestAsk, liveTickFresh, accountCurrency, selectedPositionId),
  [accountCurrency, latestAsk, latestBid, liveTickFresh, positions, selectedPositionId, selectedSymbol, symbolMappings]
);

const tradeExecutionMarkers = useMemo(
  () => buildTradeExecutionMarkers(positions, tradeHistory, selectedSymbol, selectedTimeframe, tradeExecutionMarkerSettings),
  [positions, tradeExecutionMarkerSettings, tradeHistory, selectedSymbol, selectedTimeframe]
);


 const selectedPosition = useMemo(
  () => positions.find((position) => position.id === selectedPositionId && isReallyOpenPosition(position)) ?? null,
  [positions, selectedPositionId]
);
 const selectedPositionValuation = useMemo(
  () => (selectedPosition ? positionValuation(selectedPosition, symbolMappings, latestBid, latestAsk, liveTickFresh) : null),
  [latestAsk, latestBid, liveTickFresh, selectedPosition, symbolMappings]
);
 const closePositionCandidate = useMemo(
  () => positions.find((position) => position.id === closePositionId && isReallyOpenPosition(position)) ?? null,
  [closePositionId, positions]
);
 const closePositionValuation = useMemo(
  () => (closePositionCandidate ? positionValuation(closePositionCandidate, symbolMappings, latestBid, latestAsk, liveTickFresh) : null),
  [closePositionCandidate, latestAsk, latestBid, liveTickFresh, symbolMappings]
);
 const closeActionBusy = closingPosition || pendingClosingPositionIds.size > 0;
  function currentMarketKey(symbol = selectedSymbol, timeframe = selectedTimeframe) {
  return `${symbol}:${timeframe}`;
  }

  function handleSymbolChange(symbol: string) {
    const nextSymbol = symbol.toUpperCase();
    if (deprecatedSymbols.has(nextSymbol)) {
      return;
    }
    if (isAnalysisOnlySymbol(nextSymbol) && selectedTimeframe !== "D1") {
      setSelectedTimeframe("D1");
    }
    setSelectedSymbol(nextSymbol);
  }

  function isCurrentMarketContext(symbol: string, timeframe: Timeframe, generation: number) {
    return (
      generation === marketGenerationRef.current &&
      symbol === selectedSymbol &&
      timeframe === selectedTimeframe &&
      activeMarketKeyRef.current === `${symbol}:${timeframe}`
    );
  }
  useEffect(() => {
    if (selectedPositionId && !positions.some((position) => position.id === selectedPositionId && isReallyOpenPosition(position))) {
      setSelectedPositionId(null);
    }
  }, [positions, selectedPositionId]);

  useEffect(() => {
    if (closePositionId && !positions.some((position) => position.id === closePositionId && isReallyOpenPosition(position))) {
      setClosePositionId(null);
    }
  }, [closePositionId, positions]);

  useEffect(() => {
    function handleTradeExecutionMarkerSettingsChanged() {
      setTradeExecutionMarkerSettings(readTradeExecutionMarkerSettings());
    }

    window.addEventListener(tradeExecutionMarkersChangedEvent, handleTradeExecutionMarkerSettingsChanged);
    return () => window.removeEventListener(tradeExecutionMarkersChangedEvent, handleTradeExecutionMarkerSettingsChanged);
  }, []);

  useEffect(() => {
    const handleChartDensityChanged = () => setChartDensity(readChartDensity());
    window.addEventListener(chartDensityChangedEvent, handleChartDensityChanged);
    return () => window.removeEventListener(chartDensityChangedEvent, handleChartDensityChanged);
  }, []);

  useEffect(() => {
    if (selectedPositionId === null) {
      return;
    }

    function handleOutsidePositionPointerDown(event: globalThis.PointerEvent) {
      const target = event.target;

      if (!(target instanceof Element)) {
        return;
      }

      if (
        target.closest(".trade-line") ||
        target.closest(".position-bottom-sheet") ||
        target.closest(".position-close-modal")
      ) {
        return;
      }

      setSelectedPositionId(null);
    }

    window.addEventListener("pointerdown", handleOutsidePositionPointerDown, true);
    return () => {
      window.removeEventListener("pointerdown", handleOutsidePositionPointerDown, true);
    };
  }, [selectedPositionId]);

  useEffect(() => {
    void getSymbols()
      .then((response) => {
        const available = response.filter((mapping) => !deprecatedSymbols.has(mapping.internal_symbol));
        setSymbolMappings(available);
        const selectedStillEnabled = available.some((mapping) => mapping.enabled && mapping.internal_symbol === selectedSymbol);
        const firstEnabled = available.find((mapping) => mapping.enabled);
        if (!selectedStillEnabled && firstEnabled) {
          handleSymbolChange(firstEnabled.internal_symbol);
        }
      })
      .catch((requestError) => {
        setError(requestError instanceof Error ? requestError.message : "No se pudieron cargar los simbolos");
      });

    void getMockMarketStatus()
      .then(setMockStatus)
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    void refreshTradingData();
    const intervalId = window.setInterval(() => void refreshTradingData(), 15000);
    return () => window.clearInterval(intervalId);
  }, [selectedSymbol, mt5Status?.account?.login, mt5Status?.account?.server]);

  useEffect(() => {
    void refreshTradingSettings();
    const intervalId = window.setInterval(() => void refreshTradingSettings(), 30000);
    return () => window.clearInterval(intervalId);
  }, []);

  useEffect(() => {
    void refreshTorumV1Status();
    const intervalId = window.setInterval(() => void refreshTorumV1Status(), 30000);
    return () => window.clearInterval(intervalId);
  }, []);

  useEffect(() => {
    if (isAnalysisOnlySymbol(selectedSymbol) && selectedTimeframe !== "D1") {
      handleTimeframeChange("D1");
    }
  }, [selectedSymbol, selectedTimeframe]);

  useEffect(() => {
    let active = true;

    async function refreshMt5Status() {
      try {
        const status = await getMt5Status();
        if (active) {
          setMt5Status(status);
        }
      } catch {
        if (active) {
          setMt5Status(null);
        }
      }
    }

    void refreshMt5Status();
    const intervalId = window.setInterval(refreshMt5Status, 10000);
    return () => {
      active = false;
      window.clearInterval(intervalId);
    };
  }, []);

useEffect(() => {
  const symbolChanged = previousSymbolRef.current !== selectedSymbol;
  previousSymbolRef.current = selectedSymbol;

  marketGenerationRef.current += 1;
  activeMarketKeyRef.current = `${selectedSymbol}:${selectedTimeframe}`;

  const generation = marketGenerationRef.current;
  const symbol = selectedSymbol;
  const timeframe = selectedTimeframe;
  const analysisOnly = isAnalysisOnlySymbol(symbol);

  setChartAutoFollowEnabled(true);
  setLatestTick(analysisOnly ? null : latestTickBySymbolRef.current.get(symbol) ?? null);
  setBackendLatestTick(null);
  const cachedCandles = readCachedCandles(symbol, timeframe);
  if (cachedCandles) {
    setCandles(cachedCandles);
  } else {
    setCandles([]);
  }
  setNoTradeZones([]);
  setIndicatorLines([]);
  setStrategyDebugPullbacks([]);
  setAthZones([]);
  setPriceAlerts([]);
  const cachedDrawings = readCachedDrawings(symbol, timeframe);
  if (symbolChanged) {
    setDrawings(cachedDrawings ?? []);
    setSelectedDrawingId(null);
  } else if (cachedDrawings) {
    setDrawings(cachedDrawings);
    setSelectedDrawingId((current) => (current && cachedDrawings.some((drawing) => drawing.id === current) ? current : null));
  }
  setSelectedPositionId(null);
  setClosePositionId(null);
  setTradeMessage(null);
  tickCounterRef.current = 0;
  setTicksPerSecond(0);

  if (symbolChanged) {
    setChartSymbolResetToken((current) => current + 1);
  }

  if (!analysisOnly) {
    void refreshMarketDiagnostics(generation, symbol);
  }
  void refreshCandlesAndLatestTick(generation, symbol, timeframe);
}, [selectedSymbol, selectedTimeframe]);

  useEffect(() => {
    void refreshChartOverlays();
    void refreshDrawings();
    void refreshPriceAlerts();
    void refreshMarketDiagnostics();
  }, [selectedSymbol, selectedTimeframe]);

 useEffect(() => {
  socketManagerRef.current?.disconnect();

 const generation = marketGenerationRef.current;
 const symbol = selectedSymbol;
 const timeframe = selectedTimeframe;
 const socketKey = `${symbol}:${timeframe}`;

  if (isAnalysisOnlySymbol(symbol)) {
    setSocketStatus("disconnected");
    setStreamConnected(false);
    socketManagerRef.current = null;
    return;
  }

  const manager = new MarketSocketManager({
    onMessage: (message) => {
      if (generation !== marketGenerationRef.current || activeMarketKeyRef.current !== socketKey) {
        return;
      }

      handleMarketMessage(message);
    },
    onStatusChange: (status) => {
      if (generation !== marketGenerationRef.current || activeMarketKeyRef.current !== socketKey) {
        return;
      }

      setSocketStatus(status);
      setStreamConnected(status === "connected");
    },
    onReconnect: () => {
      if (generation !== marketGenerationRef.current || activeMarketKeyRef.current !== socketKey) {
        return;
      }

      void resyncAfterReconnect();
    }
  });

  socketManagerRef.current = manager;
  manager.connect(symbol, timeframe);

  return () => {
    manager.disconnect();

    if (socketManagerRef.current === manager) {
      socketManagerRef.current = null;
    }
  };
}, [selectedSymbol, selectedTimeframe]);

  usePwaResume({
    symbol: selectedSymbol,
    timeframe: selectedTimeframe,
    socketManagerRef,
    resync: resyncAfterReconnect,
    setAppVisible,
    setResumeGraceUntil,
    setSocketStatus,
    setStreamConnected,
  });

  async function handleMockToggle() {
    try {
      const nextStatus = mockStatus?.running ? await stopMockMarket() : await startMockMarket();
      setMockStatus(nextStatus);
      setLastTickTime(nextStatus.last_tick_time);
      void refreshMarketDiagnostics();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "No se pudo cambiar el mock market");
    }
  }

  function handleMarketMessage(message: MarketMessage) {
    const activeKey = activeMarketKeyRef.current;

  if (message.type === "candle_update") {
    const messageKey = `${message.symbol}:${message.timeframe}`;

    if (messageKey !== activeKey || message.symbol !== selectedSymbol || message.timeframe !== selectedTimeframe) {
      return;
    }

    const cachedMessageCandles = candleMemoryCache.get(messageKey);
    const previousLatestTime = cachedMessageCandles?.length
      ? cachedMessageCandles[cachedMessageCandles.length - 1].time
      : null;
    const isNewM5Candle =
      message.timeframe === "M5" && previousLatestTime !== null && message.candle.time > previousLatestTime;

    setCandles((current) => {
      const next = upsertCandle(current, message.candle);
      return writeCachedCandles(message.symbol, message.timeframe, next);
    });
    setStreamSource(message.candle.source);
    if (showPullbackOverlays && message.timeframe === "M5") {
      setStrategyDebugPullbacks((current) => {
        const next = updateLivePullbackDebug(current, message.candle.low, message.candle.time * 1000);
        pullbackMemoryCache.set(pullbackCacheKey(message.symbol), clonePullbacks(next));
        return next;
      });
      // Recalculate the complete segment once per new M5 candle, never once per
      // tick.  The previous implementation requested a cached snapshot on every
      // candle_update broadcast (which itself occurs on every tick), allowing a
      // stale response to raise the low from the wick back to the body/price.
      if (isNewM5Candle) void refreshPullbacks(true, message.symbol);
    }
    return;
  }
    if (message.type === "market_status") {
      setStreamConnected(message.connected);
      setStreamSource(message.source);
      setLastTickTime(message.last_tick_time);
    }
    if ((message.type === "latest_tick_update" || message.type === "market_tick") && message.symbol === selectedSymbol) {
      const parsedMessageTime = Date.parse(message.time);
      const messageTimeMsc = message.time_msc ?? (Number.isFinite(parsedMessageTime) ? parsedMessageTime : Date.now());
      queueTickForUi({
        time: message.time,
        time_msc: messageTimeMsc,
        internal_symbol: message.symbol,
        broker_symbol: message.broker_symbol ?? "",
        bid: message.bid,
        ask: message.ask,
        last: message.last,
        volume: message.volume,
        source: message.source ?? "UNKNOWN"
      });
      return;
    }
    if (message.type === "price_alert_triggered") {
      setPriceAlerts((current) => current.filter((alert) => alert.id !== message.alert_id));
      setTradeMessage(`Alerta ${message.symbol} disparada en ${message.triggered_price.toFixed(2)}`);
      void refreshPriceAlertHistory();
    }
    if (message.type === "price_alert_updated") {
      void refreshPriceAlerts();
    }
    if (message.type === "position_opened" || message.type === "position_closed" || message.type === "position_updated") {
      const eventPosition = message.position;
      if (eventPosition) {
        tradingMutationVersionRef.current += 1;
        if (message.type === "position_closed" || eventPosition.status === "CLOSED") {
          setPendingClosing(eventPosition.id, false);
          setPositions((current) => current.filter((position) => position.id !== eventPosition.id));
          setTradeHistory((current) => [
            positionToTradeHistoryItem(eventPosition),
            ...current.filter((item) => item.position_id !== eventPosition.id)
          ].slice(0, 300));
          setSelectedPositionId((current) => current === eventPosition.id ? null : current);
        } else if (isReallyOpenPosition(eventPosition)) {
          setPositions((current) => [
            eventPosition,
            ...current.filter((position) => position.id !== eventPosition.id)
          ].filter((position) => !pendingClosingPositionIdsRef.current.has(position.id)));
        }
      } else {
        void refreshTradingData();
      }
    }
  }

  async function refreshCandlesAndLatestTick(
  generation = marketGenerationRef.current,
  symbol = selectedSymbol,
  timeframe = selectedTimeframe
) {
  setLoadingCandles(true);
  setError(null);
  candleAbortRef.current?.abort();
  const controller = new AbortController();
  candleAbortRef.current = controller;

  try {
    const cachedBeforeFetch = await readAnyCachedCandles(symbol, timeframe);
    if (!isCurrentMarketContext(symbol, timeframe, generation)) {
      return;
    }

    if (cachedBeforeFetch) {
      setCandles(cachedBeforeFetch);
    }

    if (!isAnalysisOnlySymbol(symbol)) {
    void getTicks(symbol, 1)
      .then((ticks) => {
        if (!isCurrentMarketContext(symbol, timeframe, generation)) {
          return;
        }
        const tick = ticks[ticks.length - 1] ?? null;
        if (tick && tick.internal_symbol === symbol) {
          latestTickBySymbolRef.current.set(symbol, tick);
          setLatestTick(tick);
          patchOpenPositionsWithTick(tick);
        } else if (!latestTickBySymbolRef.current.has(symbol)) {
          setLatestTick(null);
        }
      })
      .catch(() => {
        if (isCurrentMarketContext(symbol, timeframe, generation) && !latestTickBySymbolRef.current.has(symbol)) {
          setLatestTick(null);
        }
      });
    }

    const nextCandles = await getCandles(symbol, timeframe, candleInitialLimit, { signal: controller.signal });

    if (!isCurrentMarketContext(symbol, timeframe, generation)) {
      return;
    }

    const mergedCandles = writeCachedCandles(symbol, timeframe, mergeCandles(cachedBeforeFetch ?? [], nextCandles));

    setCandles(mergedCandles);
    prefetchNearbyCandles(symbol, timeframe);

    const after = latestCandleTime(cachedBeforeFetch);
    if (after) {
      void getCandles(symbol, timeframe, candleNewerSyncLimit, { signal: controller.signal, after })
        .then((newerCandles) => {
          if (!isCurrentMarketContext(symbol, timeframe, generation) || newerCandles.length === 0) {
            return;
          }
          setCandles((current) => writeCachedCandles(symbol, timeframe, mergeCandles(current, newerCandles)));
        })
        .catch(() => undefined);
    }

    const before = oldestCandleTime(mergedCandles);
    if (before) {
      void getCandles(symbol, timeframe, candleOlderPageLimit, { signal: controller.signal, before })
        .then((olderCandles) => {
          if (!isCurrentMarketContext(symbol, timeframe, generation) || olderCandles.length === 0) {
            return;
          }
          setCandles((current) => writeCachedCandles(symbol, timeframe, mergeCandles(olderCandles, current)));
        })
        .catch(() => undefined);
    }
  } catch (requestError) {
    if (isAbortError(requestError)) {
      return;
    }

    if (!isCurrentMarketContext(symbol, timeframe, generation)) {
      return;
    }

    setError(requestError instanceof Error ? requestError.message : "No se pudieron cargar las velas");
  } finally {
    if (candleAbortRef.current === controller) {
      candleAbortRef.current = null;
    }

    if (isCurrentMarketContext(symbol, timeframe, generation) && candleAbortRef.current === null) {
      setLoadingCandles(false);
    }
  }
}

  async function resyncAfterReconnect() {
  const generation = marketGenerationRef.current;
  const symbol = selectedSymbol;
  const timeframe = selectedTimeframe;

  await Promise.allSettled([
    refreshCandlesAndLatestTick(generation, symbol, timeframe),
    refreshTradingData(),
    refreshTradingSettings(),
    refreshMarketDiagnostics(generation, symbol),
    refreshChartOverlays(generation, symbol, timeframe),
    refreshDrawings(generation, symbol, timeframe),
    refreshPriceAlerts(generation, symbol),
    getMockMarketStatus().then((status) => {
      if (generation === marketGenerationRef.current) {
        setMockStatus(status);
      }
    }),
    getMt5Status().then((status) => {
      if (generation === marketGenerationRef.current) {
        setMt5Status(status);
      }
    })
  ]);
}
  async function refreshTradingData(): Promise<void> {
    if (tradingRefreshPromiseRef.current) {
      tradingRefreshQueuedRef.current = true;
      return tradingRefreshPromiseRef.current;
    }
    const generation = ++tradingRefreshGenerationRef.current;
    const mutationVersion = tradingMutationVersionRef.current;
    const request = (async () => {
      try {
        const [ordersResponse, openPositionsResponse, historyResponse] = await Promise.all([
          getOrders(),
          getPositions({ status: "OPEN", limit: 100 }),
          getTradeHistory({
            accountLogin: mt5Status?.account?.login ?? null,
            accountServer: mt5Status?.account?.server ?? null
          })
        ]);
        if (
          generation !== tradingRefreshGenerationRef.current ||
          mutationVersion !== tradingMutationVersionRef.current
        ) {
          return;
        }
        const pendingClosing = pendingClosingPositionIdsRef.current;
        setOrders(ordersResponse);
        setPositions(openPositionsResponse.filter(isReallyOpenPosition).filter((position) => !pendingClosing.has(position.id)));
        setTradeHistory(historyResponse);
      } catch (requestError) {
        console.warn("[trading-refresh] failed", requestError);
      }
    })();
    tradingRefreshPromiseRef.current = request;
    void request.finally(() => {
      if (tradingRefreshPromiseRef.current === request) {
        tradingRefreshPromiseRef.current = null;
        if (tradingRefreshQueuedRef.current) {
          tradingRefreshQueuedRef.current = false;
          void refreshTradingData();
        }
      }
    });
    return request;
  }
  async function refreshTradingSettings() {
    try {
      setTradingSettings(await getTradingSettings());
    } catch {
      // The buy panel fetches settings independently; keep the chart alive if settings refresh fails.
    }
  }

  async function refreshTorumV1Status() {
    try {
      setTorumV1Status(await getTorumV1Status());
    } catch {
      setTorumV1Status(null);
    }
  }

  async function refreshMarketDiagnostics(
  generation = marketGenerationRef.current,
  symbol = selectedSymbol
) {
  try {
    if (isAnalysisOnlySymbol(symbol)) {
      if (generation === marketGenerationRef.current && symbol === selectedSymbol) {
        setBackendLatestTick(null);
        setLatestTick(null);
      }
      return;
    }
    const tick = await getLatestTick(symbol);

    if (generation !== marketGenerationRef.current || symbol !== selectedSymbol) {
      return;
    }

    setBackendLatestTick(tick);
    latestTickBySymbolRef.current.set(symbol, tick);
    setLatestTick((current) => {
      if (current && current.internal_symbol === tick.internal_symbol && current.time_msc > tick.time_msc) {
        return current;
      }

      return tick;
    });
    patchOpenPositionsWithTick(tick);
  } catch {
    if (generation === marketGenerationRef.current && symbol === selectedSymbol) {
      setBackendLatestTick(null);
    }
  }
}
  async function refreshPullbacks(force = false, symbol = selectedSymbol) {
    const requestSeq = ++pullbackRequestSeqRef.current;
    const key = pullbackCacheKey(symbol);
    const cached = pullbackMemoryCache.get(key);
    if (!force && cached && showPullbackOverlays) {
      setStrategyDebugPullbacks((current) => mergePullbackSnapshot(current, cached));
    }
    try {
      const response = await getTorumV1Pullbacks(symbol, { force, limit: 600 });
      if (requestSeq !== pullbackRequestSeqRef.current || symbol !== selectedSymbol) return;
      if (showPullbackOverlays) {
        startTransition(() => {
          setStrategyDebugPullbacks((current) => {
            const merged = mergePullbackSnapshot(current, response.pullbacks);
            pullbackMemoryCache.set(key, clonePullbacks(merged));
            return merged;
          });
        });
      } else {
        pullbackMemoryCache.set(key, clonePullbacks(response.pullbacks));
      }
    } catch (requestError) {
      if (!cached && requestSeq === pullbackRequestSeqRef.current && symbol === selectedSymbol) {
        setError(requestError instanceof Error ? requestError.message : "No se pudieron calcular los pullbacks");
      }
    }
  }

  async function refreshChartOverlays(
  generation = marketGenerationRef.current,
  symbol = selectedSymbol,
  timeframe = selectedTimeframe,
  pullbackVisible = showPullbackOverlays
) {
  const from = new Date(Date.now() - 14 * 24 * 60 * 60 * 1000).toISOString();
  const to = new Date(Date.now() + futureOverlayLookaheadDays * 24 * 60 * 60 * 1000).toISOString();

  try {
    const response = await getChartOverlays(symbol, timeframe, from, to);

    if (!isCurrentMarketContext(symbol, timeframe, generation)) {
      return;
    }

    startTransition(() => {
      setNoTradeZones(response.no_trade_zones);
      setIndicatorLines(response.indicators.filter(isLineOutput));
      if (!pullbackVisible) setStrategyDebugPullbacks([]);
      setAthZones(response.ath_zones ?? []);
      setPriceAlerts(response.price_alerts ?? []);
    });

    // if (response.positions?.length) {
    //   setPositions(response.positions.filter(isReallyOpenPosition));
    // }
  } catch {
    if (!isCurrentMarketContext(symbol, timeframe, generation)) {
      return;
    }

    startTransition(() => {
      setNoTradeZones([]);
      setIndicatorLines([]);
      if (!pullbackVisible) setStrategyDebugPullbacks([]);
      setAthZones([]);
      setPriceAlerts([]);
    });
  }
}

  async function refreshPriceAlerts(
  generation = marketGenerationRef.current,
  symbol = selectedSymbol
) {
  try {
    const response = await getPriceAlerts(symbol, "ACTIVE");

    if (generation !== marketGenerationRef.current || symbol !== selectedSymbol) {
      return;
    }

    setPriceAlerts(response);
    void refreshPriceAlertHistory(symbol);
  } catch {
    if (generation === marketGenerationRef.current && symbol === selectedSymbol) {
      setPriceAlerts([]);
    }
  }
}

  async function refreshPriceAlertHistory(symbol = selectedSymbol) {
  try {
    const history = await getPriceAlertHistory(symbol);

    if (symbol !== selectedSymbol) {
      return;
    }

    setPriceAlertHistory(history);
  } catch {
    if (symbol === selectedSymbol) {
      setPriceAlertHistory([]);
    }
  }
}

  async function refreshDrawings(
  generation = marketGenerationRef.current,
  symbol = selectedSymbol,
  timeframe = selectedTimeframe
) {
  try {
    const response = await getDrawings(symbol, timeframe, true);

    if (!isCurrentMarketContext(symbol, timeframe, generation)) {
      return;
    }

    const cached = writeCachedDrawings(symbol, timeframe, response);
    setDrawings(cached);
    setSelectedDrawingId((current) => (current && cached.some((drawing) => drawing.id === current) ? current : null));
  } catch (requestError) {
    if (!isCurrentMarketContext(symbol, timeframe, generation)) {
      return;
    }

    setError(requestError instanceof Error ? requestError.message : "No se pudieron cargar los dibujos");
  }
}

  async function handleCreateDrawing(drawing: ChartDrawingCreate) {
    const temporaryId = `local-${crypto.randomUUID()}`;
    const now = new Date().toISOString();
    const optimistic: ChartDrawingRead = {
      id: temporaryId,
      user_id: 0,
      internal_symbol: drawing.internal_symbol,
      timeframe: drawing.timeframe ?? null,
      drawing_type: drawing.drawing_type,
      name: drawing.name ?? null,
      payload: { ...drawing.payload },
      style: { ...(drawing.style ?? {}) },
      metadata: { ...(drawing.metadata ?? {}) },
      locked: drawing.locked ?? false,
      visible: drawing.visible ?? true,
      source: drawing.source ?? "MANUAL",
      revision: 0,
      created_at: now,
      updated_at: now
    };
    setDrawings((current) => writeCachedDrawings(selectedSymbol, selectedTimeframe, [...current, optimistic]));
    setSelectedDrawingId(temporaryId);
    setDrawingTool("select");
    setDrawingMenuOpen(false);
    try {
      const created = await createDrawing(drawing);
      setDrawings((current) =>
        writeCachedDrawings(
          selectedSymbol,
          selectedTimeframe,
          current.map((item) => (item.id === temporaryId ? created : item))
        )
      );
      setSelectedDrawingId((current) => (current === temporaryId ? created.id : current));
      if (drawingAffectsStrategy(created)) void refreshPullbacks(true);
    } catch (requestError) {
      setDrawings((current) => writeCachedDrawings(selectedSymbol, selectedTimeframe, current.filter((item) => item.id !== temporaryId)));
      setSelectedDrawingId((current) => (current === temporaryId ? null : current));
      setError(requestError instanceof Error ? requestError.message : "No se pudo guardar el dibujo");
    }
  }

  async function handleUpdateDrawing(drawing: ChartDrawingRead, patch: ChartDrawingUpdate) {
    if (drawing.id.startsWith("local-")) return;
    const previous = drawings.find((item) => item.id === drawing.id) ?? drawing;
    const sequence = (drawingMutationSeqRef.current.get(drawing.id) ?? 0) + 1;
    drawingMutationSeqRef.current.set(drawing.id, sequence);
    const optimistic: ChartDrawingRead = {
      ...previous,
      ...patch,
      payload: patch.payload ?? previous.payload,
      style: patch.style ?? previous.style,
      metadata: patch.metadata ?? previous.metadata,
      updated_at: new Date().toISOString()
    };
    setDrawings((current) =>
      writeCachedDrawings(selectedSymbol, selectedTimeframe, current.map((item) => (item.id === drawing.id ? optimistic : item)))
    );
    try {
      const updated = await patchDrawing(drawing.id, { ...patch, expected_revision: previous.revision });
      if (drawingMutationSeqRef.current.get(drawing.id) !== sequence) return;
      setDrawings((current) =>
        writeCachedDrawings(selectedSymbol, selectedTimeframe, current.map((item) => (item.id === updated.id ? updated : item)))
      );
      if (drawingAffectsStrategy(updated)) void refreshPullbacks(true);
    } catch (requestError) {
      if (drawingMutationSeqRef.current.get(drawing.id) === sequence) {
        setDrawings((current) =>
          writeCachedDrawings(selectedSymbol, selectedTimeframe, current.map((item) => (item.id === previous.id ? previous : item)))
        );
        setError(requestError instanceof Error ? requestError.message : "No se pudo actualizar el dibujo");
      }
    }
  }

  async function handleDeleteDrawing(drawingId: string) {
    const previous = drawings.find((drawing) => drawing.id === drawingId);
    if (!previous) return;
    setDrawings((current) => writeCachedDrawings(selectedSymbol, selectedTimeframe, current.filter((drawing) => drawing.id !== drawingId)));
    setSelectedDrawingId((current) => (current === drawingId ? null : current));
    if (drawingId.startsWith("local-")) return;
    try {
      await deleteDrawing(drawingId);
      if (drawingAffectsStrategy(previous)) void refreshPullbacks(true);
    } catch (requestError) {
      setDrawings((current) =>
        writeCachedDrawings(selectedSymbol, selectedTimeframe, current.some((item) => item.id === previous.id) ? current : [...current, previous])
      );
      setError(requestError instanceof Error ? requestError.message : "No se pudo eliminar el dibujo");
    }
  }

  async function handleDeleteSelectedDrawing() {
    if (!selectedDrawingId) {
      return;
    }
    await handleDeleteDrawing(selectedDrawingId);
  }

  async function handleCreatePriceAlert(price: number) {
    try {
      const pushStatus = await preparePushForPriceAlert();
      const alert = await createPriceAlert({
        internal_symbol: selectedSymbol,
        timeframe: null,
        target_price: price,
        message: `${selectedSymbol} <= ${price.toFixed(2)}`,
        source: "CHART"
      });
      setPriceAlerts((current) => [...current, alert]);
      setAlertToolActive(false);
      setDrawingMenuOpen(false);
      const pushText = pushStatus ? ` ${pushStatusLabel(pushStatus)}.` : " Push no activado.";
      setTradeMessage(`Alerta creada en ${price.toFixed(2)}.${pushText}`);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "No se pudo crear la alerta");
    }
  }

  async function handleUpdatePriceAlert(alert: PriceAlertRead, targetPrice: number) {
    try {
      const updated = await patchPriceAlert(alert.id, {
        target_price: targetPrice,
        message: `${alert.internal_symbol} <= ${targetPrice.toFixed(2)}`
      });
      setPriceAlerts((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      setTradeMessage(`Alerta actualizada a ${targetPrice.toFixed(2)}`);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "No se pudo actualizar la alerta");
      void refreshPriceAlerts();
    }
  }

  async function handleCancelPriceAlert(alertId: string) {
    setPriceAlerts((current) => current.filter((alert) => alert.id !== alertId));
    try {
      await cancelPriceAlert(alertId);
      void refreshPriceAlertHistory();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "No se pudo cancelar la alerta");
      void refreshPriceAlerts();
    }
  }


  function handleOrderStarted(message: string) {
    setTradeMessage(message);
    const markerPrice = latestAsk ?? latestBid ?? lastPrice;
    if (typeof markerPrice !== "number" || !Number.isFinite(markerPrice)) return;
    const markerTime = Math.floor((latestTick?.time_msc ?? Date.now()) / 1000) as Time;
    setPendingOrderMarker({
      id: `pending-buy:${selectedSymbol}:${Date.now()}`,
      time: markerTime,
      price: markerPrice,
      kind: "BUY",
      label: "Enviando..."
    });
  }

  function handleOrderCompleted(response: ManualOrderResponse) {
    setPendingOrderMarker(null);
    tradingMutationVersionRef.current += 1;
    setTradeMessage(response.ok ? response.message : response.reasons.join("; ") || response.message);
    if (response.order) {
      setOrders((current) => [response.order as OrderRead, ...current.filter((order) => order.id !== response.order?.id)].slice(0, 50));
    }
    if (response.ok && response.position && isReallyOpenPosition(response.position)) {
      setPositions((current) => {
        const next = [response.position as PositionRead, ...current.filter((position) => position.id !== response.position?.id)];
        return next.filter((position) => !pendingClosingPositionIdsRef.current.has(position.id));
      });
      setSelectedPositionId(response.position.id);
      if (response.tp_status === "PENDING") {
        setTradeMessage("Orden ejecutada. TP pendiente de confirmar.");
      } else if (response.tp_status === "FAILED") {
        setTradeMessage("Orden ejecutada. TP no confirmado.");
      }
      return;
    }
    void refreshTradingData();
  }

  function handleClosePosition(positionId: number) {
    const position = positions.find((item) => item.id === positionId);
    if (position?.status !== "OPEN") {
      setTradeMessage("La posicion ya no esta abierta");
      void refreshTradingData();
      return;
    }
    if (position.mode !== "PAPER" && !marketConnectionHealthy) {
      setTradeMessage(staleTradingReason);
      void resyncAfterReconnect();
      return;
    }
    setClosePositionId(positionId);
  }

  async function closePositionNow(position: PositionRead, successMessage = "Posicion cerrada") {
    if (position.status !== "OPEN") {
      setTradeMessage("La posicion ya no esta abierta");
      void refreshTradingData();
      return;
    }

    if (position.mode !== "PAPER" && !marketConnectionHealthy) {
      setTradeMessage(staleTradingReason);
      void resyncAfterReconnect();
      return;
    }

    const previousPosition = position;
    const previousTradeHistory = tradeHistory;
    tradingMutationVersionRef.current += 1;
    setTradeMessage("Cerrando posicion en MT5...");
    setClosePositionId(null);
    setSelectedPositionId((current) => (current === position.id ? null : current));
    setPendingClosing(position.id, true);
    setPositions((current) => current.filter((item) => item.id !== position.id));
    setTradeHistory((current) => current.filter((item) => item.position_id !== position.id));
    setClosingPosition(true);

    try {
      const closed = await closePosition(position.id);
      tradingMutationVersionRef.current += 1;
      setTradeMessage(successMessage);
      if (closed.status === "CLOSED") {
        setTradeHistory((current) => {
          const nextItem = positionToTradeHistoryItem(closed);
          return [nextItem, ...current.filter((item) => item.position_id !== closed.id)].slice(0, 300);
        });
      }
    } catch (requestError) {
      tradingMutationVersionRef.current += 1;
      setPositions((current) => [previousPosition, ...current.filter((item) => item.id !== previousPosition.id)]);
      setTradeHistory(previousTradeHistory);
      setTradeMessage(requestError instanceof Error ? requestError.message : "No se pudo cerrar la posicion");
      void refreshTradingData();
    } finally {
      setPendingClosing(position.id, false);
      setClosingPosition(false);
    }
  }

  function tpClosesWinningPositionNow(position: PositionRead, tp: number, draggedChartClosePrice?: number | null): boolean {
    const useLiveSelectedPrices = position.internal_symbol === selectedSymbol;
    const fallbackValuation = positionValuation(
      position,
      symbolMappings,
      useLiveSelectedPrices ? latestBid : null,
      useLiveSelectedPrices ? latestAsk : null,
      useLiveSelectedPrices ? liveTickFresh : false
    );
    const closePrice =
      typeof draggedChartClosePrice === "number" && Number.isFinite(draggedChartClosePrice)
        ? draggedChartClosePrice
        : fallbackValuation.closePrice;

    if (closePrice === null || !Number.isFinite(closePrice)) {
      return false;
    }

    const profit = calculatePriceDistanceProfit(
      position,
      closePrice,
      contractSizeFor(symbolMappings, position.internal_symbol),
      profitConversionRateFor(symbolMappings, position.internal_symbol)
    );

    if (profit <= 0) {
      return false;
    }

    if (position.side === "BUY") {
      return tp > position.open_price && tp <= closePrice;
    }

    return tp < position.open_price && tp >= closePrice;
  }

  function toggleHistoryRow(rowId: string) {
    setExpandedHistoryRows((current) => {
      const next = new Set(current);
      if (next.has(rowId)) {
        next.delete(rowId);
      } else {
        next.add(rowId);
      }
      return next;
    });
  }

  async function confirmClosePosition() {
    const position = closePositionCandidate;
    if (!position || position.status !== "OPEN") {
      setTradeMessage("La posicion ya no esta abierta");
      setClosePositionId(null);
      void refreshTradingData();
      return;
    }
    if (position.mode !== "PAPER" && !marketConnectionHealthy) {
      setTradeMessage(staleTradingReason);
      void resyncAfterReconnect();
      return;
    }
    await closePositionNow(position);
  }

  async function handleModifyPositionTp(positionId: number, tp: number, closePrice?: number | null) {
    const position = positions.find((item) => item.id === positionId);
    if (!position || position.status !== "OPEN") {
      setTradeMessage("No se puede modificar TP: la posicion no esta abierta");
      void refreshTradingData();
      return;
    }
    if (tpClosesWinningPositionNow(position, tp, closePrice)) {
      await closePositionNow(position, "Posicion cerrada por TP manual");
      return;
    }
    const tpCrossesEntry = position.side === "BUY" ? tp <= position.open_price : tp >= position.open_price;
    if (tpCrossesEntry) {
      handleClosePosition(positionId);
      return;
    }
    if (selectedPositionId !== positionId) {
      setTradeMessage("Selecciona primero la linea BUY para modificar su TP");
      return;
    }
    if (position.mode !== "PAPER" && !marketConnectionHealthy) {
      setTradeMessage(staleTradingReason);
      void resyncAfterReconnect();
      return;
    }
    try {
      const updated = await modifyPositionTp(positionId, tp);
      setPositions((current) => current.map((position) => (position.id === updated.id ? updated : position)));
      setTradeMessage(`TP actualizado a ${tp.toFixed(2)}`);
      void refreshTradingData();
    } catch (requestError) {
      setTradeMessage(requestError instanceof Error ? requestError.message : "No se pudo modificar el TP");
      void refreshTradingData();
    }
  }

  function toggleAlertTool() {
    setAlertToolActive((current) => {
      const next = !current;
      setDrawingTool("select");
      setDrawingMenuOpen(false);
      setTradeMessage(next ? "Modo alerta activo: toca el grafico para crear una alerta por debajo" : "Modo alerta desactivado");
      return next;
    });
  }

  function activateDrawingTool(tool: DrawingTool) {
    setAlertToolActive(false);
    setDrawingTool(tool);
    setDrawingMenuOpen(false);
    setTradeMessage(tool === "select" ? "Modo dibujo desactivado" : `Modo dibujo: ${drawingToolText(tool)}`);
  }

  function renderMarketDiagnosticPanel() {
    return (
      <section className="panel market-diagnostic-card">
        <div className="panel-title">
          <Database size={18} />
          Diagnostico de mercado
        </div>
        <dl className="metric-list">
          <div>
            <dt>Internal symbol</dt>
            <dd>{selectedSymbol}</dd>
          </div>
          <div>
            <dt>Broker mapping</dt>
            <dd>{selectedMapping?.broker_symbol ?? "--"}</dd>
          </div>
          <div>
            <dt>Fuente actual</dt>
            <dd>{sourceLabel} / cfg {tradingSettings?.market_data_source ?? "--"}</dd>
          </div>
          <div>
            <dt>Backend latest</dt>
            <dd>{backendLatestTick ? `${backendLatestTick.source} ${backendLatestTick.bid?.toFixed(2) ?? "--"} / ${backendLatestTick.ask?.toFixed(2) ?? "--"}` : "--"}</dd>
          </div>
          <div>
            <dt>Backend broker</dt>
            <dd>{backendLatestTick?.broker_symbol ?? "--"}</dd>
          </div>
          <div>
            <dt>Backend age</dt>
            <dd>{backendLatestTick ? `${backendLatestTick.age_ms} ms` : "--"}</dd>
          </div>
          <div>
            <dt>Backend time_msc</dt>
            <dd>{backendLatestTick?.time_msc ?? "--"}</dd>
          </div>
          <div>
            <dt>Frontend latest</dt>
            <dd>{latestTick ? `${latestTick.source} ${latestTick.bid?.toFixed(2) ?? "--"} / ${latestTick.ask?.toFixed(2) ?? "--"}` : "--"}</dd>
          </div>
          <div>
            <dt>Frontend time_msc</dt>
            <dd>{latestTick?.time_msc ?? "--"}</dd>
          </div>
          <div>
            <dt>Frontend age</dt>
            <dd>{frontendTickAgeMs !== null ? `${frontendTickAgeMs} ms` : "--"}</dd>
          </div>
          <div>
            <dt>Ticks/s frontend</dt>
            <dd>{ticksPerSecond.toFixed(2)}</dd>
          </div>
          <div>
            <dt>Latencia backend</dt>
            <dd>{backendLatestTick ? `${backendLatestTick.age_ms} ms` : "--"}</dd>
          </div>
          <div>
            <dt>Candle close</dt>
            <dd>{currentCandle ? `${currentCandle.close.toFixed(2)} (${currentCandle.price_source ?? "?"})` : "--"}</dd>
          </div>
          <div>
            <dt>MT5</dt>
            <dd>{mt5Status?.connected_to_mt5 ? "conectado" : "desconectado"} / {accountMode}</dd>
          </div>
          <div>
            <dt>Order execution</dt>
            <dd>{tradingSettings?.mt5_order_execution_enabled ? "habilitado en Torum" : "bloqueado en Torum"}</dd>
          </div>
          <div>
            <dt>Mock</dt>
            <dd>{mockStatus?.running ? "activo" : "apagado"}</dd>
          </div>
        </dl>
        <div className="modal-actions">
          <button className="toolbar-action" type="button" onClick={() => void refreshMarketDiagnostics()}>
            Refrescar diagnostico
          </button>
          {mockStatus?.running ? (
            <button className="toolbar-action toolbar-action--danger" type="button" onClick={() => void handleMockToggle()}>
              Detener mock
            </button>
          ) : null}
        </div>
      </section>
    );
  }

  function renderTradeHistoryPanel() {
    const closedRows = [...tradeHistory]
      .filter((item) => item.status === "CLOSED")
      .sort((left, right) => {
        const leftTime = Date.parse(left.closed_at ?? left.opened_at);
        const rightTime = Date.parse(right.closed_at ?? right.opened_at);
        return (Number.isFinite(rightTime) ? rightTime : 0) - (Number.isFinite(leftTime) ? leftTime : 0);
      });
    const openRows = [...positions]
      .filter(isReallyOpenPosition)
      .sort((left, right) => {
        const leftTime = Date.parse(left.opened_at);
        const rightTime = Date.parse(right.opened_at);
        return (Number.isFinite(rightTime) ? rightTime : 0) - (Number.isFinite(leftTime) ? leftTime : 0);
      });
    const accountBalance = mt5Status?.account?.balance;
    const confirmedRows = closedRows.filter((item) => !item.enrichment_status?.includes("PENDING"));
    const grossProfit = confirmedRows.reduce((total, item) => total + historyGrossProfit(item, symbolMappings), 0);
    const swap = confirmedRows.reduce((total, item) => total + (item.swap ?? 0), 0);
    const commission = confirmedRows.reduce((total, item) => total + (item.commission ?? 0) + (item.fee ?? 0), 0);
    const balance = typeof accountBalance === "number" && Number.isFinite(accountBalance) ? accountBalance : 0;
    const summaryRows = [
      { label: "Neto MT5:", value: grossProfit, tone: grossProfit >= 0 ? "positive" : "negative" },
      { label: "Swap:", value: swap, tone: swap >= 0 ? "positive" : "negative" },
      { label: "Comision + fee:", value: commission, tone: commission >= 0 ? "positive" : "negative" },
      { label: "Balance MT5:", value: balance, tone: "neutral" }
    ];

    return (
      <section className="trade-history-page">
        <div className="trade-history-tabs">
          <button className={historyTab === "OPEN" ? "trade-history-tabs__item trade-history-tabs__item--active" : "trade-history-tabs__item"} type="button" onClick={() => { setHistoryTab("OPEN"); setHistoryVisibleCount(100); }}>
            Abiertas
          </button>
          <button className={historyTab === "CLOSED" ? "trade-history-tabs__item trade-history-tabs__item--active" : "trade-history-tabs__item"} type="button" onClick={() => { setHistoryTab("CLOSED"); setHistoryVisibleCount(100); }}>
            Cerradas
          </button>
        </div>
        <dl className="trade-history-summary">
          {summaryRows.map((row) => (
            <div className="trade-history-summary__row" key={row.label}>
              <dt>{row.label}</dt>
              <dd className={row.tone === "positive" ? "history-money history-money--positive" : row.tone === "negative" ? "history-money history-money--negative" : "history-money"}>
                {row.value.toFixed(2)}
              </dd>
            </div>
          ))}
        </dl>
        <div className="trade-history-list">
          {historyTab === "OPEN" && openRows.length === 0 ? <div className="table-empty">Sin operaciones abiertas</div> : null}
          {historyTab === "OPEN"
            ? openRows.slice(0, historyVisibleCount).map((item) => {
                const rowId = `open-${item.id}`;
                const isExpanded = expandedHistoryRows.has(rowId);
                const liveBid = item.internal_symbol === selectedSymbol ? latestBid : null;
                const liveAsk = item.internal_symbol === selectedSymbol ? latestAsk : null;
                const valuation = positionValuation(item, symbolMappings, liveBid, liveAsk, item.internal_symbol === selectedSymbol ? liveTickFresh : false);
                const profit = valuation.estimated || item.mode === "PAPER" ? valuation.profit : item.profit ?? 0;
                const isProfit = profit >= 0;
                return (
                  <article className={isExpanded ? "trade-history-row trade-history-row--open trade-history-row--expanded" : "trade-history-row trade-history-row--open"} key={rowId}>
                    <button className="trade-history-row__button" type="button" onClick={() => toggleHistoryRow(rowId)}>
                      <div>
                        <strong>
                          {item.internal_symbol}, <span>{item.side.toLowerCase()} {item.volume.toFixed(2)}</span>
                        </strong>
                        <p>{item.open_price.toFixed(2)} -&gt; {item.current_price?.toFixed(2) ?? valuation.closePrice?.toFixed(2) ?? "--"}</p>
                      </div>
                      <div>
                        <time>{formatHistoryDate(item.opened_at)}</time>
                        <strong className={isProfit ? "history-money history-money--positive" : "history-money history-money--negative"}>
                          {valuation.estimated ? "≈" : ""}{profit.toFixed(2)}
                        </strong>
                      </div>
                    </button>
                    <button
                      aria-label="Cerrar posicion"
                      className="trade-history-row__close"
                      type="button"
                      onClick={(event) => {
                        event.stopPropagation();
                        handleClosePosition(item.id);
                      }}
                    >
                      <X size={16} />
                    </button>
                    {isExpanded ? (
                      <dl className="trade-history-row__details">
                        <div>
                          <dt>#{item.mt5_position_ticket ?? item.id}</dt>
                          <dd>Apertura: {formatHistoryDate(item.opened_at)}</dd>
                          <dd>Modo: {item.mode}</dd>
                          <dd>Lado: {item.side}</dd>
                        </div>
                        <div>
                          <dt>Precio actual: {valuation.closePrice?.toFixed(2) ?? item.current_price?.toFixed(2) ?? "--"}</dt>
                          <dd>S / L: {item.sl?.toFixed(2) ?? "--"}</dd>
                          <dd>T / P: {item.tp?.toFixed(2) ?? "--"}</dd>
                          <dd>Swap: {(item.swap ?? 0).toFixed(2)}</dd>
                          <dd>Comision: {(item.commission ?? 0).toFixed(2)}</dd>
                        </div>
                      </dl>
                    ) : null}
                  </article>
                );
              })
            : null}
          {historyTab === "CLOSED" && closedRows.length === 0 ? <div className="table-empty">Sin operaciones cerradas</div> : null}
          {historyTab === "CLOSED"
            ? closedRows.slice(0, historyVisibleCount).map((item) => {
                const rowId = `closed-${item.id}`;
                const isExpanded = expandedHistoryRows.has(rowId);
                const pendingMt5 = item.enrichment_status?.includes("PENDING") === true;
                const profit = historyGrossProfit(item, symbolMappings);
                const isProfit = profit >= 0;
                return (
                  <article className={isExpanded ? "trade-history-row trade-history-row--expanded" : "trade-history-row"} key={rowId}>
                    <button className="trade-history-row__button" type="button" onClick={() => toggleHistoryRow(rowId)}>
                      <div>
                        <strong>
                          {item.internal_symbol}, <span>{item.side.toLowerCase()} {item.volume.toFixed(2)}</span>
                        </strong>
                        <p>{item.open_price.toFixed(2)} -&gt; {pendingMt5 ? "Sincronizando MT5" : item.close_price?.toFixed(2) ?? "--"}</p>
                      </div>
                      <div>
                        <time>{formatHistoryDate(item.closed_at ?? item.opened_at)}</time>
                        <strong className={isProfit ? "history-money history-money--positive" : "history-money history-money--negative"}>
                          {pendingMt5 ? "--" : profit.toFixed(2)}
                        </strong>
                      </div>
                    </button>
                    {isExpanded ? (
                      <dl className="trade-history-row__details">
                        <div>
                          <dt>#{item.mt5_position_ticket ?? item.position_id}</dt>
                          <dd>Apertura: {formatHistoryDate(item.opened_at)}</dd>
                          <dd>Cierre: {formatHistoryDate(item.closed_at)}</dd>
                          <dd>Modo: {item.mode}</dd>
                          <dd>Estado: {pendingMt5 ? "CLOSED_PENDING_MT5" : item.status}</dd>
                        </div>
                        <div>
                          <dt>Deal: {item.closing_deal_ticket ?? "--"}</dt>
                          <dd>Entrada: {item.open_price.toFixed(2)}</dd>
                          <dd>Cierre: {item.close_price?.toFixed(2) ?? "--"}</dd>
                          <dd>T / P: {item.tp?.toFixed(2) ?? "--"}</dd>
                          <dd>Swap: {(item.swap ?? 0).toFixed(2)}</dd>
                          <dd>Comision: {(item.commission ?? 0).toFixed(2)}</dd>
                        </div>
                      </dl>
                    ) : null}
                  </article>
                );
              })
            : null}
          {(historyTab === "OPEN" ? openRows.length : closedRows.length) > historyVisibleCount ? (
            <button className="toolbar-action" type="button" onClick={() => setHistoryVisibleCount((count) => count + 100)}>
              Cargar 100 mas
            </button>
          ) : null}
        </div>
      </section>
    );
  }

  function renderPositionBottomSheet() {
    if (!selectedPosition || selectedPosition.status !== "OPEN") {
      return null;
    }
    const profit = selectedPositionValuation?.profit ?? selectedPosition.profit ?? 0;
    const closeLabel = profit >= 0 ? `CERRAR CON BENEFICIO ${profit.toFixed(2)} ${accountCurrency}` : `CERRAR CON PERDIDA ${Math.abs(profit).toFixed(2)} ${accountCurrency}`;
    const tpPercent = selectedPosition.tp_percent ?? (selectedPosition.tp ? ((selectedPosition.tp - selectedPosition.open_price) / selectedPosition.open_price) * 100 : null);
    return (
      <section className="position-bottom-sheet">
        <div className="position-bottom-sheet__header">
          <div>
            <strong>{selectedPosition.internal_symbol} {selectedPosition.side} {selectedPosition.volume.toFixed(2)}</strong>
            <span>Entrada {selectedPosition.open_price.toFixed(2)} / Cierre {selectedPositionValuation?.closePrice?.toFixed(2) ?? "--"} / TP {selectedPosition.tp?.toFixed(2) ?? "--"} {tpPercent !== null ? `(${tpPercent.toFixed(2)}%)` : ""}</span>
          </div>
          <button className="mobile-icon-button" type="button" onClick={() => setSelectedPositionId(null)}>x</button>
        </div>
        <button
          className={profit >= 0 ? "position-close-button position-close-button--profit" : "position-close-button position-close-button--loss"}
          type="button"
          onClick={() => void handleClosePosition(selectedPosition.id)}
        >
          {closeLabel}
        </button>
      </section>
    );
  }

  function renderClosePositionModal() {
    if (!closePositionCandidate || closePositionCandidate.status !== "OPEN") {
      return null;
    }

    const profit = closePositionValuation?.profit ?? closePositionCandidate.profit ?? 0;
    const tpPercent = closePositionCandidate.tp_percent ?? (closePositionCandidate.tp ? ((closePositionCandidate.tp - closePositionCandidate.open_price) / closePositionCandidate.open_price) * 100 : null);
    const resultLabel = profit >= 0 ? `Beneficio ${profit.toFixed(2)} ${accountCurrency}` : `Perdida ${Math.abs(profit).toFixed(2)} ${accountCurrency}`;

    return (
      <div className="modal-backdrop" role="presentation">
        <div className="confirm-modal buy-confirm-modal position-close-modal" role="dialog" aria-modal="true" aria-label="Confirmar cierre">
          <div className="position-close-modal__title">
            <div className="modal-title-row">
              <ShieldAlert size={20} />
              <h2>Confirmar cierre</h2>
            </div>
            <button aria-label="Cancelar cierre" className="mobile-icon-button" type="button" onClick={() => setClosePositionId(null)}>
              <X size={18} />
            </button>
          </div>
          <dl className="confirm-summary">
            <div>
              <dt>Simbolo</dt>
              <dd>{closePositionCandidate.internal_symbol}</dd>
            </div>
            <div>
              <dt>Lado</dt>
              <dd>{closePositionCandidate.side}</dd>
            </div>
            <div>
              <dt>Lotaje</dt>
              <dd>{closePositionCandidate.volume.toFixed(2)}</dd>
            </div>
            <div>
              <dt>Entrada</dt>
              <dd>{closePositionCandidate.open_price.toFixed(2)}</dd>
            </div>
            <div>
              <dt>Cierre aprox.</dt>
              <dd>{closePositionValuation?.closePrice?.toFixed(2) ?? "--"}</dd>
            </div>
            <div>
              <dt>TP</dt>
              <dd>{closePositionCandidate.tp?.toFixed(2) ?? "--"} {tpPercent !== null ? `(${tpPercent.toFixed(2)}%)` : ""}</dd>
            </div>
            <div>
              <dt>Resultado aprox.</dt>
              <dd className={profit >= 0 ? "profit-positive" : "profit-negative"}>{resultLabel}</dd>
            </div>
          </dl>
          <p>El backend recalcula precio y resultado antes de cerrar.</p>
          <div className="modal-actions">
            <button className="toolbar-action" type="button" onClick={() => setClosePositionId(null)}>
              Cancelar
            </button>
            <button
              className={profit >= 0 ? "position-close-button position-close-button--profit" : "position-close-button position-close-button--loss"}
              disabled={closeActionBusy}
              type="button"
              onClick={() => void confirmClosePosition()}
            >
              {closeActionBusy ? "Cerrando" : "Confirmar cierre"}
            </button>
          </div>
        </div>
      </div>
    );
  }
  function handleHardResetChartView() {
  setChartAutoFollowEnabled(true);
  setChartRecenterToken((current) => current + 1);
  setChartHardResetToken((current) => current + 1);
}

  function handleTimeframeChange(nextTimeframe: Timeframe) {
    if (selectedAnalysisOnly && nextTimeframe !== "D1") {
      return;
    }
    if (nextTimeframe === selectedTimeframe) {
      return;
    }

    setChartAutoFollowEnabled(true);
    marketGenerationRef.current += 1;
    activeMarketKeyRef.current = `${selectedSymbol}:${nextTimeframe}`;
    candleAbortRef.current?.abort();
    setCandles([]);
    setNoTradeZones([]);
    setIndicatorLines([]);
    setStrategyDebugPullbacks([]);
    setAthZones([]);
    setPriceAlerts([]);
    setSelectedTimeframe(nextTimeframe);
  }

  function handlePullbackOverlayToggle(visible: boolean) {
    setShowPullbackOverlays(visible);
    saveBooleanPreference(showPullbackOverlaysStorageKey, visible);
    if (!visible) {
      setStrategyDebugPullbacks([]);
      return;
    }
    const cached = pullbackMemoryCache.get(pullbackCacheKey(selectedSymbol));
    if (cached) setStrategyDebugPullbacks(clonePullbacks(cached));
    // Paint the memory snapshot immediately, then refresh once in the background
    // so the live segment is current even if the cached closed-candle snapshot is older.
    void refreshPullbacks(true);
  }

  function queuePullbackOverlayRefresh() {
    // Backward-compatible caller: recompute only on candle/parameter changes.
    if (showPullbackOverlays) void refreshPullbacks(false);
  }

  function handleChartSplitChange(count: ChartSplitCount, orientation: ChartSplitOrientation) {
    setChartSplitCount(count);
    setChartSplitOrientation(orientation);
    setDrawingMenuOpen(false);
  }

  function updateSecondaryChart(index: number, patch: Partial<SplitChartSelection>) {
    setSecondaryCharts((current) => current.map((chart, chartIndex) => (chartIndex === index ? { ...chart, ...patch } : chart)));
  }

  return (
    <section
      className={`trading-grid trading-grid--view-${activeMobileView} trading-grid--split-${chartSplitOrientation}${spyModeEnabled ? " trading-grid--spy" : ""}`}
    >
      <MobileTopBar
        alertToolActive={alertToolActive}
        chartSplitCount={chartSplitCount}
        chartSplitOrientation={chartSplitOrientation}
        chartSymbols={chartSymbols}
        connected={streamConnectedForUi}
        connectionStatus={connectionStatusForUi}
        drawingTool={drawingTool}
        drawingMenuOpen={drawingMenuOpen}
        marketClosed={marketClosedWarning}
        onAlertClick={toggleAlertTool}
        onChartSplitChange={handleChartSplitChange}
        onDrawingMenuClick={() => setDrawingMenuOpen((current) => !current)}
        onMenuClick={() => setDrawerOpen(true)}
        onSystemStatusClick={() => setSystemStatusOpen(true)}
        onSymbolChange={handleSymbolChange}
        onTimeframeChange={handleTimeframeChange}
        selectedSymbol={selectedSymbol}
        selectedTimeframe={selectedTimeframe}
        symbolLabels={strategySymbolLabels}
        symbolStatusTones={topbarSymbolStatusTones}
        timeframes={visibleTimeframes}
      />
      <AccountDrawer
        activeView={activeMobileView}
        backendOk={!error}
        marketSource={sourceLabel}
        mt5Status={mt5Status}
        onClose={() => setDrawerOpen(false)}
        onNavigate={setActiveMobileView}
        open={drawerOpen}
      />
      <SystemStatusModal open={systemStatusOpen} onClose={() => setSystemStatusOpen(false)} />
      <div className={drawingMenuOpen ? "mobile-drawing-menu mobile-drawing-menu--open" : "mobile-drawing-menu"}>
        {mobileDrawingTools.map((tool) => (
          <button
            className={drawingTool === tool ? "mobile-drawing-menu__item mobile-drawing-menu__item--active" : "mobile-drawing-menu__item"}
            aria-label={drawingToolText(tool)}
            key={tool}
            title={drawingToolText(tool)}
            type="button"
            onClick={() => activateDrawingTool(tool)}
          >
            {drawingToolIcon(tool)}
          </button>
        ))}
      </div>

      <TradingWorkspacePanels
        activeView={activeMobileView}
        chartSymbols={chartSymbols}
        diagnostics={renderMarketDiagnosticPanel()}
        history={renderTradeHistoryPanel()}
        indicatorLines={indicatorLines}
        onChartContextChanged={() => void refreshChartOverlays()}
        onStrategyChanged={() => {
          void refreshTorumV1Status();
          void refreshChartOverlays();
        }}
        symbol={selectedSymbol}
        timeframe={selectedTimeframe}
        timeframes={visibleTimeframes}
      />

      <div className="market-toolbar">
        <div className="segmented-control" aria-label="Simbolo">
          {chartSymbols.map((symbol) => (
            <button
              className={symbol === selectedSymbol ? "segment segment--active" : "segment"}
              key={symbol}
              type="button"
              onClick={() => handleSymbolChange(symbol)}
            >
              {torumAssetLabel(torumV1Status, symbol)}
            </button>
          ))}
        </div>

        <div className="segmented-control" aria-label="Timeframe">
          {visibleTimeframes.map((timeframe) => (
            <button
              className={timeframe === selectedTimeframe ? "segment segment--active" : "segment"}
              key={timeframe}
              type="button"
              onClick={() => handleTimeframeChange(timeframe)}
            >
              {timeframe}
            </button>
          ))}
        </div>

        <button className="toolbar-action" type="button" onClick={handleMockToggle}>
          {mockStatus?.running ? <Pause size={18} /> : <Play size={18} />}
          {mockStatus?.running ? "Parar mock" : "Iniciar mock"}
        </button>

        <button
          className={alertToolActive ? "toolbar-action toolbar-action--active" : "toolbar-action"}
          type="button"
          onClick={() => {
            toggleAlertTool();
          }}
        >
          <Bell size={18} />
          Alerta por debajo
        </button>

        <DrawingToolbar
          activeTool={drawingTool}
          drawingsVisible={drawingsVisible}
          onDeleteSelected={() => void handleDeleteSelectedDrawing()}
          onToggleDrawings={() => setDrawingsVisible((current) => !current)}
          onToolChange={setDrawingTool}
          selectedDrawingId={selectedDrawingId}
        />
      </div>

      {!selectedAnalysisOnly ? (
      <BuyOnlyOrderPanel
        accountMode={accountMode}
        disabledReason={symbolTradingNotice}
        lastPrice={lastPrice}
        marketConnectionHealthy={marketConnectionHealthy}
        marketStaleReason={staleTradingReason}
        mt5Connected={mt5Status?.connected_to_mt5 ?? false}
        mt5Status={mt5Status}
        onOrderCompleted={handleOrderCompleted}
        onOrderStarted={handleOrderStarted}
        onOrderFinished={() => setPendingOrderMarker(null)}
        symbol={selectedSymbol}
        tradable={symbolTradable}
      />
      ) : null}

      <section className={chartSplitCount > 1 ? "chart-panel chart-panel--split" : "chart-panel"} aria-label="Grafico">
        {chartSplitCount === 1 ? (
          <div className="chart-panel__header">
            <div>
              <h2>{torumAssetLabel(torumV1Status, selectedSymbol)}</h2>
            </div>
            <div className="price-cluster">
              <span className="price-value">{typeof lastPrice === "number" ? `BID ${lastPrice.toFixed(2)}` : "BID --"}</span>
              <button className="system-status-open-button" title="Estado del sistema" type="button" onClick={() => setSystemStatusOpen(true)}>
                <RadioTower size={16} />
              </button>
              <StatusPill
                label={streamStatusLabel}
                tone={streamStatusTone}
              />
              <StatusPill label={sourceLabel} tone={sourceLabel === "MT5" ? "success" : "neutral"} />
            </div>
          </div>
        ) : null}

        <div className={`chart-split-grid chart-split-grid--${chartSplitCount} chart-split-grid--${chartSplitCount}-${chartSplitOrientation}`}>
          <div className="chart-split-pane chart-split-pane--primary">
            {chartSplitCount > 1 ? (
              <div className="chart-split-pane__controls" onPointerDown={(event) => event.stopPropagation()}>
                <select aria-label="Simbolo grafico principal" value={selectedSymbol} onChange={(event) => handleSymbolChange(event.target.value)}>
                  {chartSymbols.map((symbol) => (
                    <option key={symbol} value={symbol}>
                      {torumAssetLabel(torumV1Status, symbol)}
                    </option>
                  ))}
                </select>
              </div>
            ) : null}
            <div className="chart-shell">
          <MarketChart
            candles={candles}
            loadingCandles={loadingCandles}
            preferredBarSpacing={chartDensity.barSpacing}
            minimumBarSpacing={chartDensity.minBarSpacing}
            hardResetToken={chartHardResetToken}
            symbolResetToken={chartSymbolResetToken}
            drawingTool={drawingTool}
            drawings={drawingsVisible ? drawings.filter((drawing) => drawing.visible) : []}
            indicatorLines={indicatorLines}
            athZones={athZones}
            strategyDebugPullbacks={strategyDebugPullbacks}
            noTradeZones={noTradeZones}
            alertToolActive={alertToolActive}
            onCreateDrawing={(drawing) => void handleCreateDrawing(drawing)}
            onCreatePriceAlert={(price) => void handleCreatePriceAlert(price)}
            onDeleteDrawing={(drawingId) => void handleDeleteDrawing(drawingId)}
            onSelectDrawing={setSelectedDrawingId}
            onSelectPosition={setSelectedPositionId}
            onCancelPriceAlert={(alertId) => void handleCancelPriceAlert(alertId)}
            onUpdateDrawing={handleUpdateDrawing}
            onUpdatePriceAlert={(alert, price) => void handleUpdatePriceAlert(alert, price)}
            onUpdatePositionTp={handleModifyPositionTp}
            askPrice={latestAsk}
            autoExtendToFutureNews={autoExtendToFutureNews}
            autoFollowEnabled={chartAutoFollowEnabled}
            bidPrice={latestBid}
            livePrice={latestBid ?? latestTick?.last ?? latestAsk}
            centerRequestKey={`${selectedSymbol}:${selectedTimeframe}`}
            onAutoFollowChange={setChartAutoFollowEnabled}
            recenterToken={chartRecenterToken}
            priceAlerts={priceAlerts}
            resetKey={`${selectedSymbol}:${selectedTimeframe}`}
            selectedDrawingId={selectedDrawingId}
            showAskLine={tradingSettings?.show_ask_line ?? true}
            showBidLine={tradingSettings?.show_bid_line ?? true}
            showFutureNewsZones={showFutureNewsZones}
            pullbackDebugVisible={showPullbackOverlays}
            onPullbackDebugToggle={handlePullbackOverlayToggle}
            symbol={selectedSymbol}
            timeframe={selectedTimeframe}
            tradeLines={tradeLines}
            tradeMarkers={tradeMarkers}
            tradeExecutionMarkers={tradeExecutionMarkers}
            dollarStrengthBadge={<DollarStrengthBadge />}
          />
          {selectedAnalysisOnly ? <div className="analysis-only-pill">DXY sintetico - Solo analisis</div> : null}
          <button
            className="chart-hard-reset-button"
            type="button"
            onClick={handleHardResetChartView}
          >
            ⊙ 
          </button>
          {candles.length === 0 ? (
            <div className="chart-empty-state">
              <RefreshCw size={34} />
              <span>{loadingCandles ? "Cargando velas" : "Inicia el mock market para generar ticks"}</span>
            </div>
          ) : null}
            </div>
          </div>
          {secondaryCharts.slice(0, chartSplitCount - 1).map((chart, index) => (
            <SplitMarketChart
              accountCurrency={accountCurrency}
              alertToolActive={alertToolActive}
              chartSymbols={chartSymbols}
              drawingTool={drawingTool}
              drawingsVisible={drawingsVisible}
              key={`secondary-chart-${index}`}
              onSelectPosition={setSelectedPositionId}
              onSymbolChange={(symbol) => updateSecondaryChart(index, { symbol })}
              onUpdatePositionTp={handleModifyPositionTp}
              positions={positions}
              tradeHistory={tradeHistory}
              tradeExecutionMarkerSettings={tradeExecutionMarkerSettings}
              chartDensity={chartDensity}
              selectedPositionId={selectedPositionId}
              autoExtendToFutureNews={autoExtendToFutureNews}
              showAskLine={tradingSettings?.show_ask_line ?? true}
              showBidLine={tradingSettings?.show_bid_line ?? true}
              showFutureNewsZones={showFutureNewsZones}
              showPullbackOverlays={showPullbackOverlays}
              onPullbackOverlayToggle={handlePullbackOverlayToggle}
              symbol={chart.symbol}
              symbolMappings={symbolMappings}
              symbolLabels={strategySymbolLabels}
              timeframe={chart.symbol === "DXY" ? "D1" : selectedTimeframe}
            />
          ))}
        </div>
      </section>

      <aside className="right-rail">
        <section className="panel">
          <div className="panel-title">
            <RadioTower size={18} />
            Conexion
          </div>
          <dl className="metric-list">
            <div>
              <dt>Backend</dt>
              <dd>Activo</dd>
            </div>
            <div>
              <dt>Stream</dt>
              <dd>{streamStatusLabel}</dd>
            </div>
            <div>
              <dt>Fuente</dt>
              <dd>{sourceLabel} / cfg {tradingSettings?.market_data_source ?? "--"}</dd>
            </div>
            <div>
              <dt>Broker symbol</dt>
              <dd>{selectedMapping?.broker_symbol ?? "--"}</dd>
            </div>
            <div>
              <dt>Ultimo tick</dt>
              <dd>{mt5LastTickTime ? new Date(mt5LastTickTime).toLocaleTimeString() : lastTickTime ? new Date(lastTickTime).toLocaleTimeString() : "--"}</dd>
            </div>
          </dl>
        </section>

        <section className="panel">
          <div className="panel-title">
            <AlertTriangle size={18} />
            Riesgo
          </div>
          <div className="notice-strip">
            PAPER simula en Torum. DEMO/LIVE pasan por backend, risk manager y mt5_bridge.
          </div>
          {!symbolTradable ? <div className="notice-strip">{symbolTradingNotice}</div> : null}
        </section>

        {!selectedAnalysisOnly ? (
        <BuyOnlyOrderPanel
          accountMode={accountMode}
          disabledReason={symbolTradingNotice}
          lastPrice={lastPrice}
          marketConnectionHealthy={marketConnectionHealthy}
          marketStaleReason={staleTradingReason}
          mt5Connected={mt5Status?.connected_to_mt5 ?? false}
          mt5Status={mt5Status}
          onOrderCompleted={handleOrderCompleted}
          onOrderStarted={handleOrderStarted}
        onOrderFinished={() => setPendingOrderMarker(null)}
          symbol={selectedSymbol}
          tradable={symbolTradable}
        />
        ) : (
          <section className="panel">
            <div className="notice-strip">DXY sintetico. Solo analisis.</div>
          </section>
        )}

        <PriceAlertPanel
          activeAlerts={priceAlerts}
          history={priceAlertHistory}
          onCancel={(alertId) => void handleCancelPriceAlert(alertId)}
        />

        {renderMarketDiagnosticPanel()}

        <section className="panel">
          <div className="panel-title">
            <Database size={18} />
            Sistema
          </div>
          <dl className="metric-list">
            <div>
              <dt>MT5</dt>
              <dd>{mt5Status?.connected_to_mt5 ? "Conectado" : "Desconectado"}</dd>
            </div>
            <div>
              <dt>Cuenta</dt>
              <dd>{accountMode}</dd>
            </div>
            <div>
              <dt>Ticks MT5</dt>
              <dd>{mt5Status?.ticks_sent_total ?? 0}</dd>
            </div>
            <div>
              <dt>Ticks vela</dt>
              <dd>{currentCandle?.tick_count ?? "--"}</dd>
            </div>
            <div>
              <dt>Velas cargadas</dt>
              <dd>{candles.length}</dd>
            </div>
          </dl>
        </section>

        {error ? (
          <section className="panel panel--danger">
            <div className="panel-title">
              <AlertTriangle size={18} />
              Error
            </div>
            <div className="form-error">{error}</div>
          </section>
        ) : null}
      </aside>

      <OrdersPositionsPanel orders={orders} positions={positions} onClosePosition={(id) => void handleClosePosition(id)} />

      {renderPositionBottomSheet()}
      {renderClosePositionModal()}

      <IndicatorsPanel
        indicatorLines={indicatorLines}
        onChanged={() => void refreshChartOverlays()}
        symbol={selectedSymbol}
        timeframe={selectedTimeframe}
      />

      <DrawingPanel
        drawings={drawings}
        onDelete={(drawingId) => handleDeleteDrawing(drawingId)}
        onSelect={setSelectedDrawingId}
        onUpdate={(drawing, patch) => handleUpdateDrawing(drawing, patch)}
        selectedDrawingId={selectedDrawingId}
      />

      <NewsPanel symbol={selectedSymbol} zones={noTradeZones} onChanged={() => void refreshChartOverlays()} />

      {tradeMessage ? (
        <section className="panel trade-message">
          <div>{translateTradeMessage(tradeMessage)}</div>
        </section>
      ) : null}
    </section>
  );
}
