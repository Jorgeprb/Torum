import { useEffect, useRef } from "react";
import {
  createChart,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
} from "lightweight-charts";
import { formatChartCrosshairTime, formatChartTickMark } from "./chartTime";
import { initialCandleBarSpacing } from "./chartView";

export function useLightweightChart() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const futurePaddingSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      autoSize: true,
      layout: {
        background: { color: "#000000" },
        textColor: "#f2f4f5",
      },
      localization: {
        locale: "es-ES",
        timeFormatter: formatChartCrosshairTime,
      },
      grid: {
        vertLines: { color: "#24303a", style: LineStyle.Dashed },
        horzLines: { color: "#24303a", style: LineStyle.Dashed },
      },
      rightPriceScale: {
        borderColor: "#3a434a",
        scaleMargins: { top: 0.18, bottom: 0.18 },
      },
      timeScale: {
        borderColor: "#293033",
        barSpacing: initialCandleBarSpacing,
        minBarSpacing: 6,
        timeVisible: true,
        secondsVisible: false,
        tickMarkFormatter: formatChartTickMark,
      },
      handleScale: {
        axisPressedMouseMove: { time: true, price: true },
        mouseWheel: true,
        pinch: true,
      },
      handleScroll: {
        horzTouchDrag: true,
        vertTouchDrag: true,
        mouseWheel: true,
        pressedMouseMove: true,
      },
      crosshair: { mode: 1 },
    });

    const series = chart.addCandlestickSeries({
      upColor: "#20c9bd",
      downColor: "#f45d5d",
      borderUpColor: "#20c9bd",
      borderDownColor: "#f45d5d",
      wickUpColor: "#20c9bd",
      wickDownColor: "#f45d5d",
      lastValueVisible: false,
      priceLineVisible: false,
    });

    const futurePaddingSeries = chart.addLineSeries({
      color: "rgba(0,0,0,0)",
      lineWidth: 1,
      lastValueVisible: false,
      priceLineVisible: false,
      crosshairMarkerVisible: false,
    });

    chartRef.current = chart;
    seriesRef.current = series;
    futurePaddingSeriesRef.current = futurePaddingSeries;

    return () => {
      futurePaddingSeriesRef.current = null;
      seriesRef.current = null;
      chartRef.current = null;
      chart.remove();
    };
  }, []);

  return { containerRef, chartRef, seriesRef, futurePaddingSeriesRef };
}
