import { type MouseEvent, useCallback, useEffect, useRef, useState } from "react";
import {
  type CandlestickData,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  LineStyle,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
  createChart
} from "lightweight-charts";

import type { Candle } from "../../services/market";
import type { NoTradeZone } from "../../services/news";
import { type IndicatorLineOutput } from "../../services/indicators";
import type { ChartDrawingCreate, ChartDrawingRead, DrawingTool } from "../../services/drawings";
import { DrawingLayer } from "../drawings/DrawingLayer";
import type { DrawingCoordinate, DrawingPoint, DrawingShape } from "../drawings/drawingTypes";
import { createBaseDrawing, drawingLabel, numericStyleValue, styleValue } from "../drawings/drawingUtils";

interface MarketChartProps {
  candles: Candle[];
  noTradeZones?: NoTradeZone[];
  indicatorLines?: IndicatorLineOutput[];
  drawings?: ChartDrawingRead[];
  drawingTool?: DrawingTool;
  selectedDrawingId?: string | null;
  symbol: string;
  timeframe: string;
  onCreateDrawing?: (drawing: ChartDrawingCreate) => void;
  onSelectDrawing?: (drawingId: string | null) => void;
  tradeLines?: TradeLine[];
  tradeMarkers?: SeriesMarker<Time>[];
}

interface ZoneOverlay {
  id: number;
  left: number;
  width: number;
  zone: NoTradeZone;
}

export interface TradeLine {
  id: string;
  price: number;
  label: string;
  tone: "entry" | "tp" | "close";
}

interface TradeLineOverlay extends TradeLine {
  y: number;
}

function toChartCandle(candle: Candle): CandlestickData {
  return {
    time: candle.time as UTCTimestamp,
    open: candle.open,
    high: candle.high,
    low: candle.low,
    close: candle.close
  };
}

function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
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

export function MarketChart({
  candles,
  noTradeZones = [],
  indicatorLines = [],
  drawings = [],
  drawingTool = "select",
  selectedDrawingId = null,
  symbol,
  timeframe,
  onCreateDrawing,
  onSelectDrawing,
  tradeLines = [],
  tradeMarkers = []
}: MarketChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const lineSeriesRef = useRef<Map<string, ISeriesApi<"Line">>>(new Map());
  const [overlays, setOverlays] = useState<ZoneOverlay[]>([]);
  const [tradeLineOverlays, setTradeLineOverlays] = useState<TradeLineOverlay[]>([]);
  const [drawingShapes, setDrawingShapes] = useState<DrawingShape[]>([]);
  const [pendingPoint, setPendingPoint] = useState<DrawingPoint | null>(null);
  const [pendingCoordinate, setPendingCoordinate] = useState<DrawingCoordinate | null>(null);

  const recalculateOverlays = useCallback(() => {
    const chart = chartRef.current;
    const series = seriesRef.current;
    const container = containerRef.current;
    if (!chart || !series || !container) {
      setOverlays([]);
      setDrawingShapes([]);
      setTradeLineOverlays([]);
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
        return { id: zone.id, left, width: Math.max(2, right - left), zone };
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
        const base = { id: drawing.id, drawing, color, lineWidth, label };
        const payload = drawing.payload;

        if (drawing.drawing_type === "horizontal_line") {
          const price = numberValue(payload.price);
          const y = price === null ? null : series.priceToCoordinate(price);
          return y === null ? null : ({ ...base, kind: "horizontal_line", x1: 0, x2: containerWidth, y } satisfies DrawingShape);
        }
        if (drawing.drawing_type === "vertical_line") {
          const time = numberValue(payload.time);
          if (time === null) {
            return null;
          }
          const x = chart.timeScale().timeToCoordinate(time as UTCTimestamp);
          return x === null ? null : ({ ...base, kind: "vertical_line", x, y1: 0, y2: containerHeight } satisfies DrawingShape);
        }
        if (drawing.drawing_type === "trend_line") {
          const points = Array.isArray(payload.points) ? payload.points : [];
          if (points.length !== 2 || typeof points[0] !== "object" || points[0] === null || typeof points[1] !== "object" || points[1] === null) {
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
            : ({ ...base, kind: "trend_line", x1, y1, x2, y2 } satisfies DrawingShape);
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
          return x === null || y === null ? null : ({ ...base, kind: "text", x, y, text, textColor } satisfies DrawingShape);
        }
        return null;
      })
      .filter((shape): shape is DrawingShape => shape !== null);
    setDrawingShapes(shapes);

    setTradeLineOverlays(
      tradeLines
        .map((line): TradeLineOverlay | null => {
          const y = series.priceToCoordinate(line.price);
          return y === null ? null : { ...line, y };
        })
        .filter((line): line is TradeLineOverlay => line !== null)
    );

    if (pendingPoint) {
      const x = chart.timeScale().timeToCoordinate(pendingPoint.time as UTCTimestamp);
      const y = series.priceToCoordinate(pendingPoint.price);
      setPendingCoordinate(x === null || y === null ? null : { x, y });
    } else {
      setPendingCoordinate(null);
    }
  }, [drawings, noTradeZones, pendingPoint, tradeLines]);

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
        borderColor: "#3a434a"
      },
      timeScale: {
        borderColor: "#293033",
        timeVisible: true,
        secondsVisible: false
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
      wickDownColor: "#f45d5d"
    });

    chartRef.current = chart;
    seriesRef.current = series;

    return () => {
      lineSeriesRef.current.clear();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!seriesRef.current) {
      return;
    }

    seriesRef.current.setData(candles.map(toChartCandle));
    seriesRef.current.setMarkers(tradeMarkers);
    chartRef.current?.timeScale().fitContent();
    window.setTimeout(recalculateOverlays, 0);
  }, [candles, recalculateOverlays, tradeMarkers]);

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
      const data: LineData[] = line.points.map((point) => ({ time: point.time as UTCTimestamp, value: point.value }));
      lineSeries.setData(data);
    }
  }, [indicatorLines]);

  function chartPointFromClick(event: MouseEvent<HTMLDivElement>): DrawingPoint | null {
    const chart = chartRef.current;
    const series = seriesRef.current;
    const container = containerRef.current;
    if (!chart || !series || !container) {
      return null;
    }
    const bounds = container.getBoundingClientRect();
    const x = event.clientX - bounds.left;
    const y = event.clientY - bounds.top;
    const time = chartTimeToUnix(chart.timeScale().coordinateToTime(x));
    const price = series.coordinateToPrice(y);
    if (time === null || price === null) {
      return null;
    }
    return { time, price };
  }

  function handleDrawingClick(event: MouseEvent<HTMLDivElement>) {
    if (drawingTool === "select" || !onCreateDrawing) {
      return;
    }
    const point = chartPointFromClick(event);
    if (!point) {
      return;
    }

    if (drawingTool === "horizontal_line") {
      onCreateDrawing(createBaseDrawing(symbol, timeframe, "horizontal_line", { price: Number(point.price.toFixed(5)), label: "Horizontal" }, "Horizontal line"));
      return;
    }
    if (drawingTool === "vertical_line") {
      onCreateDrawing(createBaseDrawing(symbol, timeframe, "vertical_line", { time: point.time, label: "Vertical" }, "Vertical line"));
      return;
    }
    if (drawingTool === "text") {
      const text = window.prompt("Texto del dibujo", "Nota");
      if (text?.trim()) {
        onCreateDrawing(createBaseDrawing(symbol, timeframe, "text", { time: point.time, price: Number(point.price.toFixed(5)), text: text.trim() }, "Text"));
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
              { time: pendingPoint.time, price: Number(pendingPoint.price.toFixed(5)) },
              { time: point.time, price: Number(point.price.toFixed(5)) }
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

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) {
      return;
    }
    chart.timeScale().subscribeVisibleTimeRangeChange(recalculateOverlays);
    window.addEventListener("resize", recalculateOverlays);
    recalculateOverlays();
    return () => {
      chart.timeScale().unsubscribeVisibleTimeRangeChange(recalculateOverlays);
      window.removeEventListener("resize", recalculateOverlays);
    };
  }, [recalculateOverlays]);

  return (
    <div className={drawingTool === "select" ? "market-chart market-chart-frame" : "market-chart market-chart-frame market-chart-frame--drawing"} ref={containerRef} onClick={handleDrawingClick}>
      <div className="news-zone-layer" aria-hidden="true">
        {overlays.map((overlay) => (
          <div
            className={overlay.zone.blocks_trading ? "news-zone-overlay news-zone-overlay--blocking" : "news-zone-overlay"}
            key={overlay.id}
            style={{ left: overlay.left, width: overlay.width }}
            title={overlay.zone.reason}
          >
            <span className="news-zone-line news-zone-line--start" />
            <span className="news-zone-line news-zone-line--end" />
          </div>
        ))}
      </div>
      <DrawingLayer
        onSelect={(drawingId) => onSelectDrawing?.(drawingId)}
        pendingPoint={pendingCoordinate}
        selectedDrawingId={selectedDrawingId}
        shapes={drawingShapes}
      />
      <div className="trade-line-layer" aria-hidden="true">
        {tradeLineOverlays.map((line) => (
          <div className={`trade-line trade-line--${line.tone}`} key={line.id} style={{ top: line.y }}>
            <span>{line.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
