import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  type IChartApi,
  type ISeriesApi,
  type MouseEventParams,
  type UTCTimestamp,
  createChart,
} from "lightweight-charts";

import type { TorumV1Backtest, TorumV1BacktestTrade } from "../../../services/strategies";

interface StrategySimulationChartProps {
  result: TorumV1Backtest;
  focusTrade: TorumV1BacktestTrade | null;
  focusTime?: string | null;
  showPullbacks: boolean;
  showSupports: boolean;
  showZones: boolean;
  showRejections?: boolean;
  onFocusCleared?: () => void;
}

interface OverlayGeometry {
  zones: Array<{ id: string; x: number; y: number; width: number; height: number; label: string }>;
  supports: Array<{ id: string; y1: number; y2: number; label: string; level: number }>;
  pullbacks: Array<{ id: string; x1: number; y1: number; x2: number; y2: number; label: string }>;
  trades: Array<{
    id: string;
    entryX: number;
    entryY: number;
    exitX: number | null;
    exitY: number | null;
    positive: boolean;
  }>;
  rejections: Array<{ id: string; x: number; y: number; label: string }>;
}

function unixSeconds(value: string): UTCTimestamp {
  return Math.floor(new Date(value).getTime() / 1000) as UTCTimestamp;
}

function lowerBound(values: readonly number[], target: number): number {
  let low = 0;
  let high = values.length;
  while (low < high) {
    const middle = (low + high) >>> 1;
    if (values[middle] < target) low = middle + 1;
    else high = middle;
  }
  return low;
}

export function StrategySimulationChart({
  result,
  focusTrade,
  focusTime = null,
  showPullbacks,
  showSupports,
  showZones,
  showRejections = false,
  onFocusCleared,
}: StrategySimulationChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const resizeObserverRef = useRef<ResizeObserver | null>(null);
  const overlayFrameRef = useRef<number | null>(null);
  const recalculateRef = useRef<() => void>(() => undefined);
  const [geometry, setGeometry] = useState<OverlayGeometry>({ zones: [], supports: [], pullbacks: [], trades: [], rejections: [] });
  const [tooltip, setTooltip] = useState<{ x: number; y: number; text: string } | null>(null);

  const candleTimes = useMemo(() => result.candles.map((item) => unixSeconds(item.time)), [result.candles]);

  const recalculate = useCallback(() => {
    const chart = chartRef.current;
    const series = seriesRef.current;
    const container = containerRef.current;
    if (!chart || !series || !container || result.candles.length === 0) return;

    const timeScale = chart.timeScale();
    const firstTime = Number(candleTimes[0]);
    const lastTime = Number(candleTimes[candleTimes.length - 1]);
    const firstX = timeScale.timeToCoordinate(candleTimes[0]) ?? 0;
    const lastX = timeScale.timeToCoordinate(candleTimes[candleTimes.length - 1]) ?? container.clientWidth;
    const xForSeconds = (target: number): number | null => {
      const direct = timeScale.timeToCoordinate(target as UTCTimestamp);
      if (direct != null) return direct;
      if (target <= firstTime) return firstX;
      if (target >= lastTime) return lastX;
      const upperIndex = lowerBound(candleTimes as number[], target);
      const lowerIndex = Math.max(0, upperIndex - 1);
      const safeUpper = Math.min(candleTimes.length - 1, upperIndex);
      const lowerTime = Number(candleTimes[lowerIndex]);
      const upperTime = Number(candleTimes[safeUpper]);
      const lowerX = timeScale.timeToCoordinate(candleTimes[lowerIndex]);
      const upperX = timeScale.timeToCoordinate(candleTimes[safeUpper]);
      if (lowerX == null || upperX == null || upperTime <= lowerTime) return lowerX ?? upperX;
      return lowerX + (upperX - lowerX) * ((target - lowerTime) / (upperTime - lowerTime));
    };
    const xFor = (raw: string | null, rightFallback = false): number | null => {
      if (!raw) return rightFallback ? lastX : firstX;
      return xForSeconds(Number(unixSeconds(raw)));
    };
    const yFor = (price: number): number | null => series.priceToCoordinate(price);

    const zones = showZones
      ? result.operation_zones.flatMap((zone) => {
          const x1 = xFor(zone.time1);
          const x2 = xFor(zone.time2, true);
          const yTop = yFor(zone.price_max);
          const yBottom = yFor(zone.price_min);
          if (x1 == null || x2 == null || yTop == null || yBottom == null) return [];
          return [{ id: zone.id, x: Math.min(x1, x2), y: Math.min(yTop, yBottom), width: Math.max(1, Math.abs(x2 - x1)), height: Math.max(1, Math.abs(yBottom - yTop)), label: zone.name || "Zona Torum" }];
        })
      : [];

    const supports = showSupports
      ? result.supports.flatMap((support) => {
          const y1 = yFor(support.upper_price);
          const y2 = yFor(support.lower_price);
          if (y1 == null || y2 == null) return [];
          return [{ id: support.id, y1: Math.min(y1, y2), y2: Math.max(y1, y2), label: support.name || `S${support.level}`, level: support.level }];
        })
      : [];

    const pullbacks = showPullbacks
      ? result.pullbacks.flatMap((pullback, index) => {
          const x1 = xFor(pullback.swing_high_time);
          const x2 = xFor(pullback.pullback_low_time);
          const y1 = yFor(pullback.swing_high);
          const y2 = yFor(pullback.pullback_low);
          if (x1 == null || x2 == null || y1 == null || y2 == null) return [];
          return [{ id: `pb-${index}-${pullback.pullback_low_time}`, x1, y1, x2, y2, label: `${pullback.pullback_pct.toFixed(2)}%` }];
        })
      : [];

    const trades = result.trades.flatMap((trade) => {
      const entryX = xFor(trade.entry_time);
      const entryY = yFor(trade.entry_price);
      if (entryX == null || entryY == null) return [];
      const exitX = trade.exit_time ? xFor(trade.exit_time) : null;
      const exitY = trade.exit_price != null ? yFor(trade.exit_price) : null;
      return [{ id: trade.id, entryX, entryY, exitX, exitY, positive: trade.net_profit >= 0 }];
    });

    const rejections = showRejections
      ? result.debug_events.filter((event) => event.status === "REJECT" && event.price != null).slice(-400).flatMap((event, index) => {
          const x = xFor(event.time);
          const y = event.price == null ? null : yFor(event.price);
          if (x == null || y == null) return [];
          return [{ id: `reject-${event.candle_index}-${event.reason_code}-${index}`, x, y, label: event.summary }];
        })
      : [];

    setGeometry({ zones, supports, pullbacks, trades, rejections });
  }, [candleTimes, result.debug_events, result.operation_zones, result.pullbacks, result.supports, result.trades, showPullbacks, showRejections, showSupports, showZones]);

  useEffect(() => {
    recalculateRef.current = recalculate;
  }, [recalculate]);

  const queueRecalculate = useCallback(() => {
    if (overlayFrameRef.current != null) cancelAnimationFrame(overlayFrameRef.current);
    overlayFrameRef.current = requestAnimationFrame(() => {
      overlayFrameRef.current = null;
      recalculateRef.current();
    });
  }, []);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const chart = createChart(container, {
      width: container.clientWidth,
      height: Math.max(440, container.clientHeight || 560),
      layout: { background: { color: "#081018" }, textColor: "#9fb1c5" },
      grid: { vertLines: { color: "rgba(133, 160, 186, 0.08)" }, horzLines: { color: "rgba(133, 160, 186, 0.08)" } },
      rightPriceScale: { borderColor: "rgba(133, 160, 186, 0.25)", autoScale: true },
      timeScale: { borderColor: "rgba(133, 160, 186, 0.25)", timeVisible: true, secondsVisible: false, minBarSpacing: 0.5 },
      crosshair: { vertLine: { color: "rgba(255,255,255,.3)" }, horzLine: { color: "rgba(255,255,255,.3)" } },
      handleScale: { axisPressedMouseMove: true, mouseWheel: true, pinch: true },
      handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: true },
    });
    const series = chart.addCandlestickSeries({
      upColor: "#1fc8b5",
      downColor: "#f2636f",
      borderUpColor: "#1fc8b5",
      borderDownColor: "#f2636f",
      wickUpColor: "#1fc8b5",
      wickDownColor: "#f2636f",
      lastValueVisible: false,
      priceLineVisible: false,
    });
    chartRef.current = chart;
    seriesRef.current = series;

    const crosshairHandler = (param: MouseEventParams) => {
      if (!param.point || !param.time) {
        setTooltip(null);
        return;
      }
      const data = param.seriesData.get(series);
      if (!data || !("close" in data)) {
        setTooltip(null);
        return;
      }
      setTooltip({
        x: Math.min(container.clientWidth - 190, Math.max(8, param.point.x + 12)),
        y: Math.min(container.clientHeight - 76, Math.max(8, param.point.y + 12)),
        text: `O ${data.open.toFixed(2)} · H ${data.high.toFixed(2)} · L ${data.low.toFixed(2)} · C ${data.close.toFixed(2)}`,
      });
    };
    chart.subscribeCrosshairMove(crosshairHandler);
    chart.timeScale().subscribeVisibleTimeRangeChange(queueRecalculate);
    resizeObserverRef.current = new ResizeObserver(() => {
      chart.applyOptions({ width: container.clientWidth, height: Math.max(440, container.clientHeight || 560) });
      queueRecalculate();
    });
    resizeObserverRef.current.observe(container);

    return () => {
      if (overlayFrameRef.current != null) cancelAnimationFrame(overlayFrameRef.current);
      resizeObserverRef.current?.disconnect();
      chart.unsubscribeCrosshairMove(crosshairHandler);
      chart.timeScale().unsubscribeVisibleTimeRangeChange(queueRecalculate);
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, [queueRecalculate]);

  useEffect(() => {
    const series = seriesRef.current;
    const chart = chartRef.current;
    if (!series || !chart) return;
    series.setData(result.candles.map((item) => ({ time: unixSeconds(item.time), open: item.open, high: item.high, low: item.low, close: item.close })));
    chart.timeScale().fitContent();
    queueRecalculate();
  }, [queueRecalculate, result.candles]);

  useEffect(() => {
    const chart = chartRef.current;
    const targetRaw = focusTrade?.entry_time ?? focusTime;
    if (!chart || !targetRaw || candleTimes.length === 0) return;
    const target = Number(unixSeconds(targetRaw));
    const exit = focusTrade?.exit_time ? Number(unixSeconds(focusTrade.exit_time)) : target;
    const targetIndex = Math.min(candleTimes.length - 1, lowerBound(candleTimes as number[], target));
    const exitIndex = Math.min(candleTimes.length - 1, lowerBound(candleTimes as number[], exit));
    const startIndex = Math.max(0, Math.min(targetIndex, exitIndex) - 18);
    const endIndex = Math.min(candleTimes.length - 1, Math.max(targetIndex, exitIndex) + 18);
    chart.timeScale().setVisibleRange({ from: candleTimes[startIndex], to: candleTimes[endIndex] });
    queueRecalculate();
    const timer = window.setTimeout(() => onFocusCleared?.(), 1200);
    return () => window.clearTimeout(timer);
  }, [candleTimes, focusTime, focusTrade, onFocusCleared, queueRecalculate]);

  useEffect(() => queueRecalculate(), [queueRecalculate, showPullbacks, showRejections, showSupports, showZones]);

  return (
    <div className="strategy-sim-chart-shell">
      <div className="strategy-sim-chart" ref={containerRef} />
      <svg className="strategy-sim-chart-overlay" aria-hidden="true">
        {geometry.zones.map((zone) => <g key={zone.id}><rect className="strategy-sim-zone" height={zone.height} width={zone.width} x={zone.x} y={zone.y} /><text className="strategy-sim-zone-label" x={zone.x + 5} y={zone.y + 15}>{zone.label}</text></g>)}
        {geometry.supports.map((support) => <g key={support.id}><rect className={`strategy-sim-support strategy-sim-support--s${support.level}`} height={Math.max(2, support.y2 - support.y1)} width="100%" x="0" y={support.y1} /><text className="strategy-sim-support-label" x="8" y={support.y1 + 13}>{support.label}</text></g>)}
        {geometry.pullbacks.map((pullback) => <g key={pullback.id}><line className="strategy-sim-pullback" x1={pullback.x1} x2={pullback.x2} y1={pullback.y1} y2={pullback.y2} /><text className="strategy-sim-pullback-label" x={pullback.x2 + 4} y={pullback.y2 - 4}>{pullback.label}</text></g>)}
        {geometry.trades.map((trade) => (
          <g key={trade.id}>
            {trade.exitX != null && trade.exitY != null ? <line className={trade.positive ? "strategy-sim-trade-line is-profit" : "strategy-sim-trade-line is-loss"} x1={trade.entryX} x2={trade.exitX} y1={trade.entryY} y2={trade.exitY} /> : null}
            <path className="strategy-sim-entry-arrow" d={`M ${trade.entryX - 5} ${trade.entryY + 9} L ${trade.entryX} ${trade.entryY} L ${trade.entryX + 5} ${trade.entryY + 9} M ${trade.entryX} ${trade.entryY} L ${trade.entryX} ${trade.entryY + 15}`} />
            {trade.exitX != null && trade.exitY != null ? <path className="strategy-sim-exit-arrow" d={`M ${trade.exitX - 5} ${trade.exitY - 9} L ${trade.exitX} ${trade.exitY} L ${trade.exitX + 5} ${trade.exitY - 9} M ${trade.exitX} ${trade.exitY} L ${trade.exitX} ${trade.exitY - 15}`} /> : null}
          </g>
        ))}
        {geometry.rejections.map((marker) => <g key={marker.id}><title>{marker.label}</title><line className="strategy-sim-rejection-marker" x1={marker.x - 4} x2={marker.x + 4} y1={marker.y - 4} y2={marker.y + 4} /><line className="strategy-sim-rejection-marker" x1={marker.x - 4} x2={marker.x + 4} y1={marker.y + 4} y2={marker.y - 4} /></g>)}
      </svg>
      {tooltip ? <div className="strategy-sim-chart-tooltip" style={{ left: tooltip.x, top: tooltip.y }}>{tooltip.text}</div> : null}
      <div className="strategy-sim-chart-legend">
        <span><i className="is-entry" /> Compra</span><span><i className="is-exit" /> Salida</span>
        {showPullbacks ? <span><i className="is-pullback" /> Pullback</span> : null}{showZones ? <span><i className="is-zone" /> Región Torum</span> : null}{showRejections ? <span><i className="is-rejection" /> Bloqueo</span> : null}
      </div>
    </div>
  );
}
