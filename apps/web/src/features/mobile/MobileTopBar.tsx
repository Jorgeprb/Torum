import { useEffect, useRef, useState } from "react";
import { Bell, ChevronDown, LockKeyhole, Menu, PencilLine, Signal } from "lucide-react";

import type { Timeframe } from "../../services/market";
import type { MarketSocketStatus } from "../../services/marketSocket";
import type { DrawingTool } from "../../services/drawings";

interface MobileTopBarProps {
  alertToolActive: boolean;
  assetLockOpen: boolean;
  chartSymbols: string[];
  connected: boolean;
  connectionStatus: MarketSocketStatus;
  drawingTool: DrawingTool;
  drawingMenuOpen: boolean;
  onAlertClick: () => void;
  onAssetLockClick: () => void;
  onDrawingMenuClick: () => void;
  onMenuClick: () => void;
  onSystemStatusClick: () => void;
  onSymbolChange: (symbol: string) => void;
  onTimeframeChange: (timeframe: Timeframe) => void;
  marketClosed?: boolean;
  selectedSymbol: string;
  selectedTimeframe: Timeframe;
  symbolLabels?: Record<string, string>;
  symbolStatusTones?: Record<string, "unlocked" | "locked">;
  timeframes: Timeframe[];
}

export function MobileTopBar({
  alertToolActive,
  assetLockOpen,
  chartSymbols,
  connected,
  connectionStatus,
  drawingTool,
  drawingMenuOpen,
  onAlertClick,
  onAssetLockClick,
  onDrawingMenuClick,
  onMenuClick,
  onSystemStatusClick,
  onSymbolChange,
  onTimeframeChange,
  marketClosed = false,
  selectedSymbol,
  selectedTimeframe,
  symbolStatusTones,
  timeframes
}: MobileTopBarProps) {
  const [openMenu, setOpenMenu] = useState<"symbol" | "timeframe" | null>(null);
  const dropdownRootRef = useRef<HTMLDivElement | null>(null);
  const statusClass =
    marketClosed
      ? "mobile-status mobile-status--warning"
      : connectionStatus === "connected"
      ? "mobile-status mobile-status--ok"
      : connectionStatus === "connecting" || connectionStatus === "reconnecting" || connectionStatus === "stale"
        ? "mobile-status mobile-status--warning"
        : "mobile-status mobile-status--error";
  const statusTitle =
    marketClosed
      ? "Mercado cerrado"
      : connectionStatus === "connected"
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
  useEffect(() => {
    function handlePointerDown(event: PointerEvent) {
      const target = event.target as Element | null;
      if (
        !dropdownRootRef.current?.contains(event.target as Node) ||
        !target?.closest(".mobile-topbar-dropdown")
      ) {
        setOpenMenu(null);
      }
    }

    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, []);

  function toggleMenu(menu: "symbol" | "timeframe") {
    setOpenMenu((current) => (current === menu ? null : menu));
  }

  function symbolStatusClass(symbol: string): string {
    const tone = symbolStatusTones?.[symbol];
    if (tone === "unlocked") return " mobile-symbol-status mobile-symbol-status--unlocked";
    if (tone === "locked") return " mobile-symbol-status mobile-symbol-status--locked";
    return "";
  }

  return (
    <header className="mobile-topbar" ref={dropdownRootRef}>
      <button aria-label="Abrir menu" className="mobile-icon-button" type="button" onClick={onMenuClick}>
        <Menu size={26} />
      </button>
      <div className="mobile-topbar-dropdown mobile-topbar-dropdown--symbol">
        <button
          aria-expanded={openMenu === "symbol"}
          aria-label="Simbolo"
          className={`mobile-topbar-dropdown__button${symbolStatusClass(selectedSymbol)}`}
          type="button"
          onClick={() => toggleMenu("symbol")}
        >
          <span>{selectedSymbol}</span>
          <ChevronDown size={14} />
        </button>
        {openMenu === "symbol" ? (
          <div className="mobile-topbar-dropdown__menu">
            {chartSymbols.map((symbol) => (
              <button
                className={`${symbol === selectedSymbol ? "mobile-dropdown-item mobile-dropdown-item--active" : "mobile-dropdown-item"}${symbolStatusClass(symbol)}`}
                key={symbol}
                type="button"
                onClick={() => {
                  onSymbolChange(symbol);
                  setOpenMenu(null);
                }}
              >
                {symbol}
              </button>
            ))}
          </div>
        ) : null}
      </div>
      <div className="mobile-topbar-dropdown mobile-topbar-dropdown--timeframe">
        <button
          aria-expanded={openMenu === "timeframe"}
          aria-label="Timeframe"
          className="mobile-topbar-dropdown__button"
          type="button"
          onClick={() => toggleMenu("timeframe")}
        >
          <span>{selectedTimeframe}</span>
          <ChevronDown size={14} />
        </button>
        {openMenu === "timeframe" ? (
          <div className="mobile-topbar-dropdown__menu">
            {timeframes.map((timeframe) => (
              <button
                className={timeframe === selectedTimeframe ? "mobile-dropdown-item mobile-dropdown-item--active" : "mobile-dropdown-item"}
                key={timeframe}
                type="button"
                onClick={() => {
                  onTimeframeChange(timeframe);
                  setOpenMenu(null);
                }}
              >
                {timeframe}
              </button>
            ))}
          </div>
        ) : null}
      </div>
      <button
        aria-label="Bloquear o desbloquear activos Torum"
        aria-pressed={assetLockOpen}
        className={assetLockOpen ? "mobile-icon-button mobile-icon-button--active" : "mobile-icon-button"}
        type="button"
        onClick={onAssetLockClick}
      >
        <LockKeyhole size={22} />
      </button>
      <button
        aria-label="Herramientas de dibujo"
        className={drawingMenuOpen || drawingTool !== "select" ? "mobile-icon-button mobile-icon-button--active" : "mobile-icon-button"}
        data-mobile-drawing-toggle="true"
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
      <button className={`${statusClass} mobile-status-button`} title={statusTitle} type="button" onClick={onSystemStatusClick}>
        <Signal size={18} />
      </button>
    </header>
  );
}
