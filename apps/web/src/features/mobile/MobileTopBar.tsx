import { Bell, Menu, PencilLine, Plus, Signal } from "lucide-react";

import type { Timeframe } from "../../services/market";
import type { DrawingTool } from "../../services/drawings";

interface MobileTopBarProps {
  connected: boolean;
  drawingTool: DrawingTool;
  onAlertClick: () => void;
  onMenuClick: () => void;
  onToolChange: (tool: DrawingTool) => void;
  selectedTimeframe: Timeframe;
}

export function MobileTopBar({ connected, drawingTool, onAlertClick, onMenuClick, onToolChange, selectedTimeframe }: MobileTopBarProps) {
  return (
    <header className="mobile-topbar">
      <button aria-label="Abrir menu" className="mobile-icon-button" type="button" onClick={onMenuClick}>
        <Menu size={26} />
      </button>
      <button
        aria-label="Dibujar linea horizontal"
        className={drawingTool === "horizontal_line" ? "mobile-icon-button mobile-icon-button--active" : "mobile-icon-button"}
        type="button"
        onClick={() => onToolChange(drawingTool === "horizontal_line" ? "select" : "horizontal_line")}
      >
        <PencilLine size={22} />
      </button>
      <button aria-label="Crear alerta" className="mobile-icon-button" type="button" onClick={onAlertClick}>
        <Bell size={22} />
      </button>
      <span className="mobile-timeframe-chip">{selectedTimeframe}</span>
      <span className={connected ? "mobile-status mobile-status--ok" : "mobile-status"} title={connected ? "Stream conectado" : "Stream desconectado"}>
        <Signal size={18} />
      </span>
      <button
        aria-label="Zona manual"
        className={drawingTool === "manual_zone" ? "mobile-icon-button mobile-icon-button--active" : "mobile-icon-button"}
        type="button"
        onClick={() => onToolChange(drawingTool === "manual_zone" ? "select" : "manual_zone")}
      >
        <Plus size={22} />
      </button>
    </header>
  );
}
