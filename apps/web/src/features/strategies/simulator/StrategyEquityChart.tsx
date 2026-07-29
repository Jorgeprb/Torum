import { useEffect, useRef } from "react";
import { type UTCTimestamp, createChart } from "lightweight-charts";

import type { TorumV1BacktestEquityPoint } from "../../../services/strategies";

function unixSeconds(value: string): UTCTimestamp {
  return Math.floor(new Date(value).getTime() / 1000) as UTCTimestamp;
}

export function StrategyEquityChart({ points }: { points: TorumV1BacktestEquityPoint[] }) {
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const chart = createChart(container, {
      width: container.clientWidth,
      height: 220,
      layout: { background: { color: "#0a141e" }, textColor: "#9fb1c5" },
      grid: { vertLines: { color: "rgba(133,160,186,.07)" }, horzLines: { color: "rgba(133,160,186,.07)" } },
      rightPriceScale: { borderColor: "rgba(133,160,186,.2)" },
      timeScale: { borderColor: "rgba(133,160,186,.2)", timeVisible: true, minBarSpacing: 1 },
      handleScale: { mouseWheel: true, pinch: true, axisPressedMouseMove: true },
      handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true },
    });
    const balanceSeries = chart.addLineSeries({ color: "#7c9cff", lineWidth: 2, title: "Balance", priceLineVisible: false, lastValueVisible: true });
    const equitySeries = chart.addLineSeries({ color: "#23d3b8", lineWidth: 1, title: "Equity", priceLineVisible: false, lastValueVisible: true });
    balanceSeries.setData(points.map((item) => ({ time: unixSeconds(item.time), value: item.balance })));
    equitySeries.setData(points.map((item) => ({ time: unixSeconds(item.time), value: item.equity })));
    chart.timeScale().fitContent();
    const observer = new ResizeObserver(() => chart.applyOptions({ width: container.clientWidth }));
    observer.observe(container);
    return () => {
      observer.disconnect();
      chart.remove();
    };
  }, [points]);

  return <div className="strategy-sim-equity-chart" ref={containerRef} />;
}
