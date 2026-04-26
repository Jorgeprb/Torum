import { useEffect, useMemo, useState } from "react";
import type { SeriesMarker, Time } from "lightweight-charts";
import { AlertTriangle, Database, Pause, Play, RadioTower, RefreshCw } from "lucide-react";

import { StatusPill } from "../../components/ui/StatusPill";
import { MarketChart, type TradeLine } from "../chart/MarketChart";
import { DrawingPanel } from "../drawings/DrawingPanel";
import { DrawingToolbar } from "../drawings/DrawingToolbar";
import { IndicatorsPanel } from "../indicators/IndicatorsPanel";
import { NewsPanel } from "../news/NewsPanel";
import { StrategyPanel } from "../strategies/StrategyPanel";
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
  type SymbolMapping,
  type Timeframe,
  createMarketWebSocket,
  getCandles,
  getMockMarketStatus,
  getMt5Status,
  getSymbols,
  startMockMarket,
  stopMockMarket
} from "../../services/market";
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
  closePosition,
  getOrders,
  getPositions
} from "../../services/trading";
import { type IndicatorLineOutput, getChartOverlays, isLineOutput } from "../../services/indicators";
import { type NoTradeZone } from "../../services/news";

const fallbackSymbols = ["XAUUSD", "XAUEUR", "XAUAUD", "XAUJPY", "DXY"];
const timeframes: Timeframe[] = ["M1", "M5", "H1", "H2", "H4", "D1", "W1"];

function upsertCandle(candles: Candle[], update: Candle): Candle[] {
  const index = candles.findIndex((candle) => candle.time === update.time);
  if (index >= 0) {
    const next = [...candles];
    next[index] = update;
    return next;
  }
  return [...candles, update].sort((a, b) => a.time - b.time).slice(-500);
}

export function TradingDashboard() {
  const [selectedSymbol, setSelectedSymbol] = useState("XAUUSD");
  const [selectedTimeframe, setSelectedTimeframe] = useState<Timeframe>("M1");
  const [symbolMappings, setSymbolMappings] = useState<SymbolMapping[]>([]);
  const [candles, setCandles] = useState<Candle[]>([]);
  const [mockStatus, setMockStatus] = useState<MockMarketStatus | null>(null);
  const [mt5Status, setMt5Status] = useState<MT5Status | null>(null);
  const [streamConnected, setStreamConnected] = useState(false);
  const [streamSource, setStreamSource] = useState("MOCK");
  const [lastTickTime, setLastTickTime] = useState<string | null>(null);
  const [loadingCandles, setLoadingCandles] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tradeMessage, setTradeMessage] = useState<string | null>(null);
  const [orders, setOrders] = useState<OrderRead[]>([]);
  const [positions, setPositions] = useState<PositionRead[]>([]);
  const [noTradeZones, setNoTradeZones] = useState<NoTradeZone[]>([]);
  const [indicatorLines, setIndicatorLines] = useState<IndicatorLineOutput[]>([]);
  const [drawings, setDrawings] = useState<ChartDrawingRead[]>([]);
  const [drawingTool, setDrawingTool] = useState<DrawingTool>("select");
  const [selectedDrawingId, setSelectedDrawingId] = useState<string | null>(null);
  const [drawingsVisible, setDrawingsVisible] = useState(true);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [activeMobileView, setActiveMobileView] = useState<MobileView>("chart");

  const selectedMapping = useMemo(
    () => symbolMappings.find((mapping) => mapping.internal_symbol === selectedSymbol),
    [selectedSymbol, symbolMappings]
  );
  const chartSymbols = useMemo(
    () => (symbolMappings.length > 0 ? symbolMappings.filter((mapping) => mapping.enabled).map((mapping) => mapping.internal_symbol) : fallbackSymbols),
    [symbolMappings]
  );
  const currentCandle = candles.length > 0 ? candles[candles.length - 1] : undefined;
  const lastPrice = currentCandle?.close;
  const sourceLabel = mt5Status?.connected_to_mt5 ? "MT5" : mockStatus?.running ? "MOCK" : streamSource;
  const accountMode = mt5Status?.account_trade_mode ?? "UNKNOWN";
  const mt5LastTickTime = mt5Status?.last_tick_time_by_symbol[selectedSymbol] ?? null;
  const symbolTradable = selectedMapping ? selectedMapping.tradable && !selectedMapping.analysis_only : true;
  const symbolTradingNotice = selectedMapping?.analysis_only
    ? `${selectedSymbol} es un activo de analisis. Trading deshabilitado.`
    : `${selectedSymbol} no esta habilitado para trading.`;
  const tradeMarkers = useMemo<SeriesMarker<Time>[]>(() => {
    const executedOrders = orders
      .filter((order) => order.internal_symbol === selectedSymbol && order.status === "EXECUTED")
      .map((order) => ({
        time: Math.floor(new Date(order.executed_at ?? order.created_at).getTime() / 1000) as Time,
        position: "belowBar" as const,
        color: "#2be0d0",
        shape: "arrowUp" as const,
        text: `BUY ${order.volume}`
      }));
    const closedPositions = positions
      .filter((position) => position.internal_symbol === selectedSymbol && position.status === "CLOSED" && position.closed_at)
      .map((position) => ({
        time: Math.floor(new Date(position.closed_at ?? position.opened_at).getTime() / 1000) as Time,
        position: "aboveBar" as const,
        color: "#f45d5d",
        shape: "circle" as const,
        text: "CLOSE"
      }));
    return [...executedOrders, ...closedPositions];
  }, [orders, positions, selectedSymbol]);
  const tradeLines = useMemo(
    () =>
      positions
        .filter((position) => position.internal_symbol === selectedSymbol && position.status === "OPEN")
        .flatMap((position) => {
          const lines: TradeLine[] = [
            {
              id: `entry-${position.id}`,
              price: position.open_price,
              label: `BUY ${position.volume.toFixed(2)} @ ${position.open_price.toFixed(2)}`,
              tone: "entry" as const
            }
          ];
          if (position.tp) {
            lines.push({
              id: `tp-${position.id}`,
              price: position.tp,
              label: `TP ${position.tp.toFixed(2)}`,
              tone: "tp" as const
            });
          }
          return lines;
        }),
    [positions, selectedSymbol]
  );

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
    setLoadingCandles(true);
    setError(null);

    void getCandles(selectedSymbol, selectedTimeframe)
      .then(setCandles)
      .catch((requestError) => {
        setCandles([]);
        setError(requestError instanceof Error ? requestError.message : "No se pudieron cargar las velas");
      })
      .finally(() => setLoadingCandles(false));
  }, [selectedSymbol, selectedTimeframe]);

  useEffect(() => {
    void refreshChartOverlays();
    void refreshDrawings();
  }, [selectedSymbol, selectedTimeframe]);

  useEffect(() => {
    const socket = createMarketWebSocket(selectedSymbol, selectedTimeframe);

    socket.onopen = () => setStreamConnected(true);
    socket.onclose = () => setStreamConnected(false);
    socket.onerror = () => setStreamConnected(false);
    socket.onmessage = (event) => {
      const message = JSON.parse(event.data) as MarketMessage;
      if (message.type === "candle_update") {
        setCandles((current) => upsertCandle(current, message.candle));
        setStreamSource(message.candle.source);
      }
      if (message.type === "market_status") {
        setStreamConnected(message.connected);
        setStreamSource(message.source);
        setLastTickTime(message.last_tick_time);
      }
    };

    return () => socket.close();
  }, [selectedSymbol, selectedTimeframe]);

  async function handleMockToggle() {
    try {
      const nextStatus = mockStatus?.running ? await stopMockMarket() : await startMockMarket();
      setMockStatus(nextStatus);
      setLastTickTime(nextStatus.last_tick_time);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "No se pudo cambiar el mock market");
    }
  }

  async function refreshTradingData() {
    try {
      const [ordersResponse, positionsResponse] = await Promise.all([getOrders(), getPositions()]);
      setOrders(ordersResponse);
      setPositions(positionsResponse);
    } catch {
      // Auth refresh errors are already surfaced by order submission; keep market chart usable.
    }
  }

  async function refreshChartOverlays() {
    const from = new Date(Date.now() - 14 * 24 * 60 * 60 * 1000).toISOString();
    const to = new Date(Date.now() + 14 * 24 * 60 * 60 * 1000).toISOString();
    try {
      const response = await getChartOverlays(selectedSymbol, selectedTimeframe, from, to);
      setNoTradeZones(response.no_trade_zones);
      setIndicatorLines(response.indicators.filter(isLineOutput));
    } catch {
      setNoTradeZones([]);
      setIndicatorLines([]);
    }
  }

  async function refreshDrawings() {
    try {
      const response = await getDrawings(selectedSymbol, selectedTimeframe, true);
      setDrawings(response);
      setSelectedDrawingId((current) => (current && response.some((drawing) => drawing.id === current) ? current : null));
    } catch (requestError) {
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

  function handleOrderCompleted(response: ManualOrderResponse) {
    setTradeMessage(response.ok ? response.message : response.reasons.join("; ") || response.message);
    void refreshTradingData();
  }

  async function handleClosePosition(positionId: number) {
    setTradeMessage(null);
    try {
      await closePosition(positionId);
      setTradeMessage("Posicion cerrada en PAPER");
      void refreshTradingData();
    } catch (requestError) {
      setTradeMessage(requestError instanceof Error ? requestError.message : "No se pudo cerrar la posicion");
    }
  }

  return (
    <section className={`trading-grid trading-grid--view-${activeMobileView}`}>
      <MobileTopBar
        connected={streamConnected}
        drawingTool={drawingTool}
        onAlertClick={() => setTradeMessage("Acceso de alertas preparado. Las notificaciones push reales llegan en la fase de alertas.")}
        onMenuClick={() => setDrawerOpen(true)}
        onToolChange={setDrawingTool}
        selectedTimeframe={selectedTimeframe}
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
      <div className="mobile-symbol-strip">
        <select aria-label="Simbolo" value={selectedSymbol} onChange={(event) => setSelectedSymbol(event.target.value)}>
          {chartSymbols.map((symbol) => (
            <option key={symbol} value={symbol}>
              {symbol}
            </option>
          ))}
        </select>
        <select aria-label="Timeframe" value={selectedTimeframe} onChange={(event) => setSelectedTimeframe(event.target.value as Timeframe)}>
          {timeframes.map((timeframe) => (
            <option key={timeframe} value={timeframe}>
              {timeframe}
            </option>
          ))}
        </select>
        <span>{typeof lastPrice === "number" ? lastPrice.toFixed(2) : "--"}</span>
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
        {activeMobileView === "settings" ? <TradingSettingsPage /> : null}
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
            <span className="price-value">{typeof lastPrice === "number" ? lastPrice.toFixed(2) : "--"}</span>
            <StatusPill
              label={streamConnected ? "Stream conectado" : "Stream desconectado"}
              tone={streamConnected ? "success" : "warning"}
            />
            <StatusPill label={sourceLabel} tone={sourceLabel === "MT5" ? "success" : "neutral"} />
          </div>
        </div>

        <div className="chart-shell">
          <MarketChart
            candles={candles}
            drawingTool={drawingTool}
            drawings={drawingsVisible ? drawings.filter((drawing) => drawing.visible) : []}
            indicatorLines={indicatorLines}
            noTradeZones={noTradeZones}
            onCreateDrawing={(drawing) => void handleCreateDrawing(drawing)}
            onSelectDrawing={setSelectedDrawingId}
            selectedDrawingId={selectedDrawingId}
            symbol={selectedSymbol}
            timeframe={selectedTimeframe}
            tradeLines={tradeLines}
            tradeMarkers={tradeMarkers}
          />
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
              <dd>{streamConnected ? "Conectado" : "Desconectado"}</dd>
            </div>
            <div>
              <dt>Fuente</dt>
              <dd>{sourceLabel}</dd>
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
          mt5Connected={mt5Status?.connected_to_mt5 ?? false}
          mt5Status={mt5Status}
          onOrderCompleted={handleOrderCompleted}
          symbol={selectedSymbol}
          tradable={symbolTradable}
        />

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
