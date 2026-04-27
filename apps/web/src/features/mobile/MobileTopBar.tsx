import { Bell, Menu, PencilLine, Signal } from "lucide-react";

import type { Timeframe } from "../../services/market";
import type { DrawingTool } from "../../services/drawings";

interface MobileTopBarProps {
  alertToolActive: boolean;
  chartSymbols: string[];
  connected: boolean;
  drawingTool: DrawingTool;
  drawingMenuOpen: boolean;
  onAlertClick: () => void;
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
  chartSymbols,
  connected,
  drawingTool,
  drawingMenuOpen,
  onAlertClick,
  onDrawingMenuClick,
  onMenuClick,
  onSymbolChange,
  onTimeframeChange,
  selectedSymbol,
  selectedTimeframe,
  timeframes
}: MobileTopBarProps) {
  return (
    <header className="mobile-topbar">
      <button aria-label="Abrir menu" className="mobile-icon-button" type="button" onClick={onMenuClick}>
        <Menu size={26} />
      </button>
      <select className="mobile-topbar-select mobile-topbar-select--symbol" aria-label="Simbolo" value={selectedSymbol} onChange={(event) => onSymbolChange(event.target.value)}>
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
      <span className={connected ? "mobile-status mobile-status--ok" : "mobile-status"} title={connected ? "Stream conectado" : "Stream desconectado"}>
        <Signal size={18} />
      </span>
    </header>
  );
}
