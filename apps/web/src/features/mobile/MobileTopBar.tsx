import { Bell, Menu, PencilLine, Signal } from "lucide-react";

import type { Timeframe } from "../../services/market";
import type { MarketSocketStatus } from "../../services/marketSocket";
import type { DrawingTool } from "../../services/drawings";

interface MobileTopBarProps {
  alertToolActive: boolean;
  chartSymbols: string[];
  connected: boolean;
  connectionStatus: MarketSocketStatus;
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
  connectionStatus,
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
      <span className={statusClass} title={statusTitle}>
        <Signal size={18} />
      </span>
    </header>
  );
}
