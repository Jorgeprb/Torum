import { useEffect, useMemo, useRef, useState } from "react";
import type { Time } from "lightweight-charts";
import { AlertTriangle, Bell, Database, Pause, Play, RadioTower, RefreshCw } from "lucide-react";

import { StatusPill } from "../../components/ui/StatusPill";
import { MarketChart, type TradeLine, type TradeMarker } from "../chart/MarketChart";
import { DrawingPanel } from "../drawings/DrawingPanel";
import { DrawingToolbar } from "../drawings/DrawingToolbar";
import { IndicatorsPanel } from "../indicators/IndicatorsPanel";
import { NewsPanel } from "../news/NewsPanel";
import { StrategyPanel } from "../strategies/StrategyPanel";
import { PriceAlertPanel } from "../alerts/PriceAlertPanel";
import { AccountDrawer, type MobileView } from "../mobile/AccountDrawer";
import { MobileTopBar } from "../mobile/MobileTopBar";
import { TradingSettingsPage } from "../settings/TradingSettingsPage";
import { BuyOnlyOrderPanel } from "./BuyOnlyOrderPanel";
import { OrdersPositionsPanel } from "./OrdersPositionsPanel";
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
import { type IndicatorLineOutput, getChartOverlays, isLineOutput } from "../../services/indicators";
import { type NoTradeZone } from "../../services/news";
import {
  type PriceAlertRead,
  cancelPriceAlert,
  createPriceAlert,
  getPriceAlertHistory,
  getPriceAlerts,
  patchPriceAlert
} from "../../services/alerts";

const fallbackSymbols = ["XAUUSD", "XAUEUR", "XAUAUD", "XAUJPY", "DXY"];
const timeframes: Timeframe[] = ["M1", "M5", "H1", "H2", "H4", "D1", "W1"];

function normalizeCandleTime(time: number): number {
  if (!Number.isFinite(time)) {
    return 0;
  }

  return time > 10_000_000_000 ? Math.floor(time / 1000) : Math.floor(time);
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
    .slice(-500);
}

function isReallyOpenPosition(position: PositionRead): boolean {
  if (position.status !== "OPEN") {
    return false;
  }

  if (position.closed_at) {
    return false;
  }

  if (position.close_price !== null && position.close_price !== undefined) {
    return false;
  }

  if (position.mode !== "PAPER" && position.mt5_position_ticket === null) {
    return false;
  }

  return true;
}

function uniqueMarkers(markers: TradeMarker[]): TradeMarker[] {
  const seen = new Set<string>();

  return markers.filter((marker) => {
    const key = marker.id;

    if (seen.has(key)) {
      return false;
    }

    seen.add(key);
    return true;
  });
}

function positionOpenTime(position: PositionRead | TradeHistoryItem): Time {
  return Math.floor(new Date(position.opened_at).getTime() / 1000) as Time;
}

function positionCloseTime(position: PositionRead | TradeHistoryItem): Time | null {
  if (!position.closed_at) {
    return null;
  }

  return Math.floor(new Date(position.closed_at).getTime() / 1000) as Time;
}

export function TradingDashboard() {
  const [selectedSymbol, setSelectedSymbol] = useState("XAUUSD");
  const [selectedTimeframe, setSelectedTimeframe] = useState<Timeframe>("M1");
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
  const [loadingCandles, setLoadingCandles] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tradeMessage, setTradeMessage] = useState<string | null>(null);
  const [orders, setOrders] = useState<OrderRead[]>([]);
  const [positions, setPositions] = useState<PositionRead[]>([]);
  const [tradeHistory, setTradeHistory] = useState<TradeHistoryItem[]>([]);
  const [selectedPositionId, setSelectedPositionId] = useState<number | null>(null);
  const [noTradeZones, setNoTradeZones] = useState<NoTradeZone[]>([]);
  const [indicatorLines, setIndicatorLines] = useState<IndicatorLineOutput[]>([]);
  const [drawings, setDrawings] = useState<ChartDrawingRead[]>([]);
  const [drawingTool, setDrawingTool] = useState<DrawingTool>("select");
  const [selectedDrawingId, setSelectedDrawingId] = useState<string | null>(null);
  const [drawingsVisible, setDrawingsVisible] = useState(true);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [activeMobileView, setActiveMobileView] = useState<MobileView>("chart");
  const [alertToolActive, setAlertToolActive] = useState(false);
  const [drawingMenuOpen, setDrawingMenuOpen] = useState(false);
  const [chartAutoFollowEnabled, setChartAutoFollowEnabled] = useState(true);
  const [chartRecenterToken, setChartRecenterToken] = useState(0);
  const [chartSymbolResetToken, setChartSymbolResetToken] = useState(0);
  const [chartHardResetToken, setChartHardResetToken] = useState(0);
  const [priceAlerts, setPriceAlerts] = useState<PriceAlertRead[]>([]);
  const [priceAlertHistory, setPriceAlertHistory] = useState<PriceAlertRead[]>([]);
  const previousSymbolRef = useRef(selectedSymbol);
  const tickTimestampsRef = useRef<number[]>([]);
  const socketManagerRef = useRef<MarketSocketManager | null>(null);
  const marketGenerationRef = useRef(0);
  const activeMarketKeyRef = useRef(`${selectedSymbol}:${selectedTimeframe}`);
  const [ticksPerSecond, setTicksPerSecond] = useState(0);

  const selectedMapping = useMemo(
    () => symbolMappings.find((mapping) => mapping.internal_symbol === selectedSymbol),
    [selectedSymbol, symbolMappings]
  );
  const chartSymbols = useMemo(
    () => (symbolMappings.length > 0 ? symbolMappings.filter((mapping) => mapping.enabled).map((mapping) => mapping.internal_symbol) : fallbackSymbols),
    [symbolMappings]
  );
  const currentCandle = candles.length > 0 ? candles[candles.length - 1] : undefined;
  const latestBid = latestTick?.bid ?? null;
  const latestAsk = latestTick?.ask ?? null;
  const lastPrice = latestBid ?? undefined;
  const frontendTickAgeMs = latestTick ? Math.max(0, Date.now() - latestTick.time_msc) : null;
  const marketDataStale = socketStatus === "stale" || socketStatus === "reconnecting" || socketStatus === "disconnected" || (frontendTickAgeMs !== null && frontendTickAgeMs > 30000);
  const marketConnectionHealthy = socketStatus === "connected" && !marketDataStale;
  const staleTradingReason = "Datos desconectados o desactualizados. Reconectando...";
  const sourceLabel = mt5Status?.connected_to_mt5 ? "MT5" : mockStatus?.running ? "MOCK" : streamSource;
  const streamStatusLabel =
    socketStatus === "connected"
      ? "Stream conectado"
      : socketStatus === "reconnecting"
        ? "Reconectando"
        : socketStatus === "stale"
          ? "Datos stale"
          : socketStatus === "connecting"
            ? "Conectando"
            : "Stream desconectado";
  const streamStatusTone = socketStatus === "connected" ? "success" : socketStatus === "reconnecting" || socketStatus === "stale" || socketStatus === "connecting" ? "warning" : "danger";
  const accountMode = mt5Status?.account_trade_mode ?? "UNKNOWN";
  const mt5LastTickTime = mt5Status?.last_tick_time_by_symbol[selectedSymbol] ?? null;
  const symbolTradable = selectedMapping ? selectedMapping.tradable && !selectedMapping.analysis_only : true;
  const symbolTradingNotice = selectedMapping?.analysis_only
    ? `${selectedSymbol} es un activo de analisis. Trading deshabilitado.`
    : `${selectedSymbol} no esta habilitado para trading.`;
  
  
const tradeMarkers = useMemo(() => {
  const openPositionMarkers: TradeMarker[] = positions
    .filter((position) => position.internal_symbol === selectedSymbol)
    .filter(isReallyOpenPosition)
    .map((position) => ({
      id: `open-buy-${position.id}`,
      time: positionOpenTime(position),
      price: position.open_price,
      kind: "BUY" as const,
      label: `BUY ${position.volume.toFixed(2)}`
    }));

  const historyOpenMarkers: TradeMarker[] = tradeHistory
    .filter((item) => item.internal_symbol === selectedSymbol)
    .map((item) => ({
      id: `history-buy-${item.id}`,
      time: positionOpenTime(item),
      price: item.open_price,
      kind: "BUY" as const,
      label: `BUY ${item.volume.toFixed(2)}`
    }));

  const historyCloseMarkers: TradeMarker[] = tradeHistory
    .filter((item) => item.internal_symbol === selectedSymbol)
    .filter((item) => item.status === "CLOSED" && Boolean(item.closed_at))
    .flatMap((item) => {
      const closeTime = positionCloseTime(item);

      if (closeTime === null || item.close_price === null || item.close_price === undefined) {
        return [];
      }

      return [
        {
          id: `history-close-${item.id}`,
          time: closeTime,
          price: item.close_price,
          kind: "CLOSE" as const,
          label: "CLOSE"
        }
      ];
    });

  return uniqueMarkers([
    ...historyOpenMarkers,
    ...openPositionMarkers,
    ...historyCloseMarkers
  ]);
}, [positions, selectedSymbol, tradeHistory]);


  const tradeLines = useMemo(
  () =>
    positions
      .filter((position) => position.internal_symbol === selectedSymbol)
      .filter(isReallyOpenPosition)
      .flatMap((position) => {
        const lines: TradeLine[] = [
          {
            id: `entry-${position.id}`,
            positionId: position.id,
            price: position.open_price,
            label: `BUY ${position.volume.toFixed(2)}, ${(position.profit ?? 0).toFixed(2)} EUR`,
            tone: "entry" as const,
            selected: selectedPositionId === position.id
          }
        ];

        if (position.tp) {
          const tpPercent = position.tp_percent ?? ((position.tp - position.open_price) / position.open_price) * 100;
          const tpProfit = (position.tp - position.open_price) * position.volume;
          const selected = selectedPositionId === position.id;

          lines.push({
            id: `tp-${position.id}`,
            positionId: position.id,
            price: position.tp,
            label: `TP, +${tpProfit.toFixed(2)} EUR, ${tpPercent.toFixed(2)}%`,
            tone: "tp" as const,
            editable: selected,
            muted: !selected
          });
        }

        return lines;
      }),
  [positions, selectedPositionId, selectedSymbol]
);


 const selectedPosition = useMemo(
  () => positions.find((position) => position.id === selectedPositionId && isReallyOpenPosition(position)) ?? null,
  [positions, selectedPositionId]
);
  function currentMarketKey(symbol = selectedSymbol, timeframe = selectedTimeframe) {
  return `${symbol}:${timeframe}`;
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
    if (selectedPositionId && !positions.some((position) => position.id === selectedPositionId && position.status === "OPEN")) {
      setSelectedPositionId(null);
    }
  }, [positions, selectedPositionId]);

  useEffect(() => {
    void getSymbols()
      .then((response) => {
        setSymbolMappings(response);
        const selectedStillEnabled = response.some((mapping) => mapping.enabled && mapping.internal_symbol === selectedSymbol);
        const firstEnabled = response.find((mapping) => mapping.enabled);
        if (!selectedStillEnabled && firstEnabled) {
          setSelectedSymbol(firstEnabled.internal_symbol);
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
    const intervalId = window.setInterval(() => void refreshTradingData(), 5000);
    return () => window.clearInterval(intervalId);
  }, [selectedSymbol]);

  useEffect(() => {
    void refreshTradingSettings();
    const intervalId = window.setInterval(() => void refreshTradingSettings(), 10000);
    return () => window.clearInterval(intervalId);
  }, []);

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
    const intervalId = window.setInterval(refreshMt5Status, 5000);
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

  setChartAutoFollowEnabled(true);
  setLatestTick(null);
  setBackendLatestTick(null);
  setCandles([]);
  setNoTradeZones([]);
  setIndicatorLines([]);
  setPriceAlerts([]);
  setDrawings([]);
  setSelectedDrawingId(null);
  setSelectedPositionId(null);
  setTradeMessage(null);
  tickTimestampsRef.current = [];
  setTicksPerSecond(0);

  if (symbolChanged) {
    setChartSymbolResetToken((current) => current + 1);
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

  useEffect(() => {
    function resumeAndResync() {
      if (document.visibilityState === "hidden") {
        return;
      }
      socketManagerRef.current?.ensureFresh("foreground");
      void resyncAfterReconnect();
    }

    function handleOffline() {
      socketManagerRef.current?.markOffline();
      setSocketStatus("disconnected");
      setStreamConnected(false);
    }

    document.addEventListener("visibilitychange", resumeAndResync);
    window.addEventListener("focus", resumeAndResync);
    window.addEventListener("online", resumeAndResync);
    window.addEventListener("pageshow", resumeAndResync);
    window.addEventListener("offline", handleOffline);
    return () => {
      document.removeEventListener("visibilitychange", resumeAndResync);
      window.removeEventListener("focus", resumeAndResync);
      window.removeEventListener("online", resumeAndResync);
      window.removeEventListener("pageshow", resumeAndResync);
      window.removeEventListener("offline", handleOffline);
    };
  }, [selectedSymbol, selectedTimeframe]);

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

    setCandles((current) => upsertCandle(current, message.candle));
    setStreamSource(message.candle.source);
    return;
  }
    if (message.type === "market_status") {
      setStreamConnected(message.connected);
      setStreamSource(message.source);
      setLastTickTime(message.last_tick_time);
    }
      if ((message.type === "latest_tick_update" || message.type === "market_tick") && message.symbol === selectedSymbol) {
    if (message.symbol !== selectedSymbol) {
      return;
    }

    const now = Date.now();
    tickTimestampsRef.current = [...tickTimestampsRef.current, now].filter((timestamp) => now - timestamp <= 5000);
    setTicksPerSecond(Number((tickTimestampsRef.current.length / 5).toFixed(2)));
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
    setStreamSource(message.source ?? "UNKNOWN");
    setLastTickTime(message.time);
  }
    if (message.type === "price_alert_triggered") {
      setPriceAlerts((current) => current.filter((alert) => alert.id !== message.alert_id));
      setTradeMessage(`Alerta ${message.symbol} disparada en ${message.triggered_price.toFixed(2)}`);
      void refreshPriceAlertHistory();
    }
    if (message.type === "price_alert_updated") {
      void refreshPriceAlerts();
    }
    if (message.type === "position_closed" || message.type === "position_updated") {
      void refreshTradingData();
    }
  }

  async function refreshCandlesAndLatestTick(
  generation = marketGenerationRef.current,
  symbol = selectedSymbol,
  timeframe = selectedTimeframe
) {
  setLoadingCandles(true);
  setError(null);

  try {
    const [nextCandles, ticks] = await Promise.all([
      getCandles(symbol, timeframe),
      getTicks(symbol, 1).catch(() => [])
    ]);

    if (!isCurrentMarketContext(symbol, timeframe, generation)) {
      return;
    }

    const normalizedCandles = [...nextCandles]
      .filter((candle) => Number.isFinite(candle.time))
      .sort((a, b) => a.time - b.time);

    setCandles(normalizedCandles);
    setLatestTick(ticks[ticks.length - 1] ?? null);
  } catch (requestError) {
    if (!isCurrentMarketContext(symbol, timeframe, generation)) {
      return;
    }

    setCandles([]);
    setError(requestError instanceof Error ? requestError.message : "No se pudieron cargar las velas");
  } finally {
    if (isCurrentMarketContext(symbol, timeframe, generation)) {
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
  async function refreshTradingData() {
  try {
    const [ordersResponse, openPositionsResponse, historyResponse] = await Promise.all([
      getOrders(),
      getPositions({ status: "OPEN", symbol: selectedSymbol, limit: 100 }),
      getTradeHistory({ symbol: selectedSymbol })
    ]);

    setOrders(ordersResponse);
    setPositions(openPositionsResponse.filter(isReallyOpenPosition));
    setTradeHistory(historyResponse);
  } catch {
    // Auth refresh errors are already surfaced by order submission; keep market chart usable.
  }
}
  async function refreshTradingSettings() {
    try {
      setTradingSettings(await getTradingSettings());
    } catch {
      // The buy panel fetches settings independently; keep the chart alive if settings refresh fails.
    }
  }

  async function refreshMarketDiagnostics(
  generation = marketGenerationRef.current,
  symbol = selectedSymbol
) {
  try {
    const tick = await getLatestTick(symbol);

    if (generation !== marketGenerationRef.current || symbol !== selectedSymbol) {
      return;
    }

    setBackendLatestTick(tick);
    setLatestTick((current) => {
      if (current && current.internal_symbol === tick.internal_symbol && current.time_msc > tick.time_msc) {
        return current;
      }

      return tick;
    });
  } catch {
    if (generation === marketGenerationRef.current && symbol === selectedSymbol) {
      setBackendLatestTick(null);
    }
  }
}
  async function refreshChartOverlays(
  generation = marketGenerationRef.current,
  symbol = selectedSymbol,
  timeframe = selectedTimeframe
) {
  const from = new Date(Date.now() - 14 * 24 * 60 * 60 * 1000).toISOString();
  const to = new Date(Date.now() + 14 * 24 * 60 * 60 * 1000).toISOString();

  try {
    const response = await getChartOverlays(symbol, timeframe, from, to);

    if (!isCurrentMarketContext(symbol, timeframe, generation)) {
      return;
    }

    setNoTradeZones(response.no_trade_zones);
    setIndicatorLines(response.indicators.filter(isLineOutput));
    setPriceAlerts(response.price_alerts ?? []);

    // if (response.positions?.length) {
    //   setPositions(response.positions.filter(isReallyOpenPosition));
    // }
  } catch {
    if (!isCurrentMarketContext(symbol, timeframe, generation)) {
      return;
    }

    setNoTradeZones([]);
    setIndicatorLines([]);
    setPriceAlerts([]);
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

    setDrawings(response);
    setSelectedDrawingId((current) => (current && response.some((drawing) => drawing.id === current) ? current : null));
  } catch (requestError) {
    if (!isCurrentMarketContext(symbol, timeframe, generation)) {
      return;
    }

    setDrawings([]);
    setSelectedDrawingId(null);
    setError(requestError instanceof Error ? requestError.message : "No se pudieron cargar los dibujos");
  }
}

  async function handleCreateDrawing(drawing: ChartDrawingCreate) {
    try {
      const created = await createDrawing(drawing);
      setDrawings((current) => [...current, created]);
      setSelectedDrawingId(created.id);
      setDrawingTool("select");
      setDrawingMenuOpen(false);
      void refreshChartOverlays();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "No se pudo guardar el dibujo");
    }
  }

  async function handleUpdateDrawing(drawing: ChartDrawingRead, patch: ChartDrawingUpdate) {
    try {
      const updated = await patchDrawing(drawing.id, patch);
      setDrawings((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      void refreshChartOverlays();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "No se pudo actualizar el dibujo");
    }
  }

  async function handleDeleteDrawing(drawingId: string) {
    try {
      await deleteDrawing(drawingId);
      setDrawings((current) => current.filter((drawing) => drawing.id !== drawingId));
      setSelectedDrawingId((current) => (current === drawingId ? null : current));
      void refreshChartOverlays();
    } catch (requestError) {
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
      setTradeMessage(`Alerta BELOW creada en ${price.toFixed(2)}`);
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
    try {
      await cancelPriceAlert(alertId);
      setPriceAlerts((current) => current.filter((alert) => alert.id !== alertId));
      void refreshPriceAlertHistory();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "No se pudo cancelar la alerta");
    }
  }

  function handleOrderCompleted(response: ManualOrderResponse) {
    setTradeMessage(response.ok ? response.message : response.reasons.join("; ") || response.message);
    void refreshTradingData();
  }

  async function handleClosePosition(positionId: number) {
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
    const pnl = position?.profit ?? 0;
    const label = pnl >= 0 ? `beneficio ${pnl.toFixed(2)}` : `perdida ${Math.abs(pnl).toFixed(2)}`;
    if (!window.confirm(`Cerrar posicion ${position?.internal_symbol ?? ""} con ${label}?`)) {
      return;
    }
    setTradeMessage(null);
    try {
      await closePosition(positionId);
      setTradeMessage("Posicion cerrada");
      setSelectedPositionId(null);
      void refreshTradingData();
    } catch (requestError) {
      setTradeMessage(requestError instanceof Error ? requestError.message : "No se pudo cerrar la posicion");
    }
  }

  async function handleModifyPositionTp(positionId: number, tp: number) {
    const position = positions.find((item) => item.id === positionId);
    if (!position || position.status !== "OPEN") {
      setTradeMessage("No se puede modificar TP: la posicion no esta abierta");
      void refreshTradingData();
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
      setTradeMessage(next ? "Modo alerta activo: toca el grafico para crear una alerta BELOW" : "Modo alerta desactivado");
      return next;
    });
  }

  function activateDrawingTool(tool: DrawingTool) {
    setAlertToolActive(false);
    setDrawingTool(tool);
    setDrawingMenuOpen(false);
    setTradeMessage(tool === "select" ? "Modo dibujo desactivado" : `Modo dibujo: ${tool.replace(/_/g, " ")}`);
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
    return (
      <section className="panel trade-history-page">
        <div className="panel-title">Historial de operaciones</div>
        <div className="history-filter-strip">
          <span>{selectedSymbol}</span>
          <span>{tradeHistory.length} registros</span>
        </div>
        <div className="trade-history-list">
          {tradeHistory.length === 0 ? <div className="table-empty">Sin historial</div> : null}
          {tradeHistory.map((item) => (
            <article className="trade-history-card" key={item.id}>
              <div>
                <strong>{item.internal_symbol} {item.side}</strong>
                <span>{item.status} / {item.mode}</span>
              </div>
              <dl>
                <div>
                  <dt>Apertura</dt>
                  <dd>{new Date(item.opened_at).toLocaleString()}</dd>
                </div>
                <div>
                  <dt>Cierre</dt>
                  <dd>{item.closed_at ? new Date(item.closed_at).toLocaleString() : "--"}</dd>
                </div>
                <div>
                  <dt>Volumen</dt>
                  <dd>{item.volume.toFixed(2)}</dd>
                </div>
                <div>
                  <dt>Entrada</dt>
                  <dd>{item.open_price.toFixed(2)}</dd>
                </div>
                <div>
                  <dt>Cierre</dt>
                  <dd>{item.close_price?.toFixed(2) ?? "--"}</dd>
                </div>
                <div>
                  <dt>TP</dt>
                  <dd>{item.tp?.toFixed(2) ?? "--"}</dd>
                </div>
                <div>
                  <dt>Resultado</dt>
                  <dd className={(item.profit ?? 0) >= 0 ? "profit-positive" : "profit-negative"}>{item.profit?.toFixed(2) ?? "--"}</dd>
                </div>
                <div>
                  <dt>Ticket</dt>
                  <dd>{item.mt5_position_ticket ?? "--"}</dd>
                </div>
              </dl>
            </article>
          ))}
        </div>
      </section>
    );
  }

  function renderPositionBottomSheet() {
    if (!selectedPosition || selectedPosition.status !== "OPEN") {
      return null;
    }
    const profit = selectedPosition.profit ?? 0;
    const closeLabel = profit >= 0 ? `CERRAR CON BENEFICIO ${profit.toFixed(2)}` : `CERRAR CON PERDIDA ${Math.abs(profit).toFixed(2)}`;
    const tpPercent = selectedPosition.tp_percent ?? (selectedPosition.tp ? ((selectedPosition.tp - selectedPosition.open_price) / selectedPosition.open_price) * 100 : null);
    return (
      <section className="position-bottom-sheet">
        <div className="position-bottom-sheet__header">
          <div>
            <strong>{selectedPosition.internal_symbol} BUY {selectedPosition.volume.toFixed(2)}</strong>
            <span>Entrada {selectedPosition.open_price.toFixed(2)} / TP {selectedPosition.tp?.toFixed(2) ?? "--"} {tpPercent !== null ? `(${tpPercent.toFixed(2)}%)` : ""}</span>
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
  function handleHardResetChartView() {
  setChartAutoFollowEnabled(true);
  setChartRecenterToken((current) => current + 1);
  setChartHardResetToken((current) => current + 1);
}
  return (
    <section className={`trading-grid trading-grid--view-${activeMobileView}`}>
      <MobileTopBar
        alertToolActive={alertToolActive}
        chartSymbols={chartSymbols}
        connected={streamConnected}
        connectionStatus={socketStatus}
        drawingTool={drawingTool}
        drawingMenuOpen={drawingMenuOpen}
        onAlertClick={toggleAlertTool}
        onDrawingMenuClick={() => setDrawingMenuOpen((current) => !current)}
        onMenuClick={() => setDrawerOpen(true)}
        onSymbolChange={setSelectedSymbol}
        onTimeframeChange={setSelectedTimeframe}
        selectedSymbol={selectedSymbol}
        selectedTimeframe={selectedTimeframe}
        timeframes={timeframes}
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
      <div className={drawingMenuOpen ? "mobile-drawing-menu mobile-drawing-menu--open" : "mobile-drawing-menu"}>
        {(["horizontal_line", "vertical_line", "trend_line", "rectangle", "text", "manual_zone"] as DrawingTool[]).map((tool) => (
          <button
            className={drawingTool === tool ? "mobile-drawing-menu__item mobile-drawing-menu__item--active" : "mobile-drawing-menu__item"}
            key={tool}
            type="button"
            onClick={() => activateDrawingTool(tool)}
          >
            {tool.replace(/_/g, " ")}
          </button>
        ))}
        <button className="mobile-drawing-menu__item" type="button" onClick={() => activateDrawingTool("select")}>
          seleccionar
        </button>
      </div>

      <div className="mobile-view-panel">
        {activeMobileView === "strategies" ? <StrategyPanel symbols={chartSymbols} timeframes={timeframes} /> : null}
        {activeMobileView === "indicators" ? (
          <IndicatorsPanel
            indicatorLines={indicatorLines}
            onChanged={() => void refreshChartOverlays()}
            symbol={selectedSymbol}
            timeframe={selectedTimeframe}
          />
        ) : null}
        {activeMobileView === "settings" ? (
          <>
            <TradingSettingsPage />
            {renderMarketDiagnosticPanel()}
          </>
        ) : null}
        {activeMobileView === "history" ? renderTradeHistoryPanel() : null}
      </div>

      <div className="market-toolbar">
        <div className="segmented-control" aria-label="Simbolo">
          {chartSymbols.map((symbol) => (
            <button
              className={symbol === selectedSymbol ? "segment segment--active" : "segment"}
              key={symbol}
              type="button"
              onClick={() => setSelectedSymbol(symbol)}
            >
              {symbol}
            </button>
          ))}
        </div>

        <div className="segmented-control" aria-label="Timeframe">
          {timeframes.map((timeframe) => (
            <button
              className={timeframe === selectedTimeframe ? "segment segment--active" : "segment"}
              key={timeframe}
              type="button"
              onClick={() => setSelectedTimeframe(timeframe)}
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
          Alerta BELOW
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

      <BuyOnlyOrderPanel
        accountMode={accountMode}
        disabledReason={symbolTradingNotice}
        lastPrice={lastPrice}
        marketConnectionHealthy={marketConnectionHealthy}
        marketStaleReason={staleTradingReason}
        mt5Connected={mt5Status?.connected_to_mt5 ?? false}
        mt5Status={mt5Status}
        onOrderCompleted={handleOrderCompleted}
        symbol={selectedSymbol}
        tradable={symbolTradable}
      />

      <section className="chart-panel" aria-label="Grafico">
        <div className="chart-panel__header">
          <div>
            <p className="eyebrow">{selectedTimeframe}</p>
            <h2>{selectedMapping?.display_name ?? selectedSymbol}</h2>
          </div>
          <div className="price-cluster">
            <span className="price-value">{typeof lastPrice === "number" ? `BID ${lastPrice.toFixed(2)}` : "BID --"}</span>
            <StatusPill
              label={streamStatusLabel}
              tone={streamStatusTone}
            />
            <StatusPill label={sourceLabel} tone={sourceLabel === "MT5" ? "success" : "neutral"} />
          </div>
        </div>

        <div className="chart-shell">
          <MarketChart
            candles={candles}
            loadingCandles={loadingCandles}
            hardResetToken={chartHardResetToken}
            symbolResetToken={chartSymbolResetToken}
            drawingTool={drawingTool}
            drawings={drawingsVisible ? drawings.filter((drawing) => drawing.visible) : []}
            indicatorLines={indicatorLines}
            noTradeZones={noTradeZones}
            alertToolActive={alertToolActive}
            onCreateDrawing={(drawing) => void handleCreateDrawing(drawing)}
            onCreatePriceAlert={(price) => void handleCreatePriceAlert(price)}
            onDeleteDrawing={(drawingId) => void handleDeleteDrawing(drawingId)}
            onSelectDrawing={setSelectedDrawingId}
            onSelectPosition={setSelectedPositionId}
            onCancelPriceAlert={(alertId) => void handleCancelPriceAlert(alertId)}
            onUpdateDrawing={(drawing, patch) => void handleUpdateDrawing(drawing, patch)}
            onUpdatePriceAlert={(alert, price) => void handleUpdatePriceAlert(alert, price)}
            onUpdatePositionTp={(positionId, tp) => void handleModifyPositionTp(positionId, tp)}
            askPrice={latestAsk}
            autoFollowEnabled={chartAutoFollowEnabled}
            bidPrice={latestBid}
            onAutoFollowChange={setChartAutoFollowEnabled}
            recenterToken={chartRecenterToken}
            priceAlerts={priceAlerts}
            resetKey={`${selectedSymbol}:${selectedTimeframe}`}
            selectedDrawingId={selectedDrawingId}
            showAskLine={tradingSettings?.show_ask_line ?? true}
            showBidLine={tradingSettings?.show_bid_line ?? true}
            symbol={selectedSymbol}
            timeframe={selectedTimeframe}
            tradeLines={tradeLines}
            tradeMarkers={tradeMarkers}
          />
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

        <BuyOnlyOrderPanel
          accountMode={accountMode}
          disabledReason={symbolTradingNotice}
          lastPrice={lastPrice}
          marketConnectionHealthy={marketConnectionHealthy}
          marketStaleReason={staleTradingReason}
          mt5Connected={mt5Status?.connected_to_mt5 ?? false}
          mt5Status={mt5Status}
          onOrderCompleted={handleOrderCompleted}
          symbol={selectedSymbol}
          tradable={symbolTradable}
        />

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

      <StrategyPanel symbols={chartSymbols} timeframes={timeframes} />

      {tradeMessage ? (
        <section className="panel trade-message">
          <div>{tradeMessage}</div>
        </section>
      ) : null}
    </section>
  );
}
