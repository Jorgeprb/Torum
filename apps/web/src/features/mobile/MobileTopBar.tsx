import { useState } from "react";
import { Bell, Columns2, Columns3, Menu, PencilLine, Rows2, Rows3, Signal } from "lucide-react";

import type { Timeframe } from "../../services/market";
import type { MarketSocketStatus } from "../../services/marketSocket";
import type { DrawingTool } from "../../services/drawings";

interface MobileTopBarProps {
  alertToolActive: boolean;
  chartSplitCount: 1 | 2 | 3;
  chartSplitOrientation: "vertical" | "horizontal";
  chartSymbols: string[];
  connected: boolean;
  connectionStatus: MarketSocketStatus;
  drawingTool: DrawingTool;
  drawingMenuOpen: boolean;
  onAlertClick: () => void;
  onChartSplitChange: (count: 1 | 2 | 3, orientation: "vertical" | "horizontal") => void;
  onDrawingMenuClick: () => void;
  onMenuClick: () => void;
  onSymbolChange: (symbol: string) => void;
  onTimeframeChange: (timeframe: Timeframe) => void;
  selectedSymbol: string;
  selectedTimeframe: Timeframe;
  timeframes: Timeframe[];
}

export function MobileTopBar({
  alertToolActive,
  chartSplitCount,
  chartSplitOrientation,
  chartSymbols,
  connected,
  connectionStatus,
  drawingTool,
  drawingMenuOpen,
  onAlertClick,
  onChartSplitChange,
  onDrawingMenuClick,
  onMenuClick,
  onSymbolChange,
  onTimeframeChange,
  selectedSymbol,
  selectedTimeframe,
  timeframes
}: MobileTopBarProps) {
  const [splitMenuOpen, setSplitMenuOpen] = useState(false);
  const statusClass =
    connectionStatus === "connected"
      ? "mobile-status mobile-status--ok"
      : connectionStatus === "connecting" || connectionStatus === "reconnecting" || connectionStatus === "stale"
        ? "mobile-status mobile-status--warning"
        : "mobile-status mobile-status--error";
  const statusTitle =
    connectionStatus === "connected"
      ? "Stream conectado"
      : connectionStatus === "connecting"
        ? "Conectando"
        : connectionStatus === "reconnecting"
          ? "Reconectando"
          : connectionStatus === "stale"
            ? "Datos desactualizados"
            : connected
              ? "Stream pendiente"
              : "Stream desconectado";
  const splitOptions: Array<{ count: 1 | 2 | 3; orientation: "vertical" | "horizontal"; label: string }> = [
    { count: 1, orientation: chartSplitOrientation, label: "1" },
    { count: 2, orientation: "vertical", label: "2V" },
    { count: 3, orientation: "vertical", label: "3V" },
    { count: 2, orientation: "horizontal", label: "2H" },
    { count: 3, orientation: "horizontal", label: "3H" }
  ];

  const splitIcon =
    chartSplitOrientation === "horizontal"
      ? chartSplitCount === 3
        ? <Rows3 size={22} />
        : <Rows2 size={22} />
      : chartSplitCount === 3
        ? <Columns3 size={22} />
        : <Columns2 size={22} />;

  return (
    <header className="mobile-topbar">
      <button aria-label="Abrir menu" className="mobile-icon-button" type="button" onClick={onMenuClick}>
        <Menu size={26} />
      </button>
      <select
        className="mobile-topbar-select mobile-topbar-select--symbol"
        aria-label="Simbolo"
        value={selectedSymbol}
        onChange={(event) => onSymbolChange(event.target.value)}
      >
        {chartSymbols.map((symbol) => (
          <option key={symbol} value={symbol}>
            {symbol}
          </option>
        ))}
      </select>
      <select className="mobile-topbar-select mobile-topbar-select--timeframe" aria-label="Timeframe" value={selectedTimeframe} onChange={(event) => onTimeframeChange(event.target.value as Timeframe)}>
        {timeframes.map((timeframe) => (
          <option key={timeframe} value={timeframe}>
            {timeframe}
          </option>
        ))}
      </select>
      <div className="mobile-split-picker">
        <button
          aria-label="Elegir graficos divididos"
          className={chartSplitCount > 1 ? "mobile-icon-button mobile-icon-button--active" : "mobile-icon-button"}
          type="button"
          onClick={() => setSplitMenuOpen((current) => !current)}
        >
          {splitIcon}
          <span>{chartSplitCount}</span>
        </button>
        {splitMenuOpen ? (
          <div className="mobile-split-menu">
            {splitOptions.map((option) => (
              <button
                className={
                  chartSplitCount === option.count && (option.count === 1 || chartSplitOrientation === option.orientation)
                    ? "mobile-split-menu__item mobile-split-menu__item--active"
                    : "mobile-split-menu__item"
                }
                key={`${option.count}-${option.orientation}`}
                type="button"
                onClick={() => {
                  onChartSplitChange(option.count, option.orientation);
                  setSplitMenuOpen(false);
                }}
              >
                {option.orientation === "horizontal" ? (
                  option.count === 3 ? <Rows3 size={18} /> : <Rows2 size={18} />
                ) : option.count === 3 ? (
                  <Columns3 size={18} />
                ) : (
                  <Columns2 size={18} />
                )}
                <span>{option.label}</span>
              </button>
            ))}
          </div>
        ) : null}
      </div>
      <button
        aria-label="Herramientas de dibujo"
        className={drawingMenuOpen || drawingTool !== "select" ? "mobile-icon-button mobile-icon-button--active" : "mobile-icon-button"}
        type="button"
        onClick={onDrawingMenuClick}
      >
        <PencilLine size={22} />
      </button>
      <button
        aria-label="Crear alerta"
        className={alertToolActive ? "mobile-icon-button mobile-icon-button--active" : "mobile-icon-button"}
        type="button"
        onClick={onAlertClick}
      >
        <Bell size={22} />
      </button>
      <span className={statusClass} title={statusTitle}>
        <Signal size={18} />
      </span>
    </header>
  );
}
