import { useEffect, useRef, useState } from "react";
import { Bell, ChevronDown, Columns2, Columns3, Menu, PencilLine, Rows2, Rows3, Signal } from "lucide-react";

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
  onSystemStatusClick: () => void;
  onSymbolChange: (symbol: string) => void;
  onTimeframeChange: (timeframe: Timeframe) => void;
  marketClosed?: boolean;
  selectedSymbol: string;
  selectedTimeframe: Timeframe;
  symbolLabels?: Record<string, string>;
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
  onSystemStatusClick,
  onSymbolChange,
  onTimeframeChange,
  marketClosed = false,
  selectedSymbol,
  selectedTimeframe,
  symbolLabels,
  timeframes
}: MobileTopBarProps) {
  const [openMenu, setOpenMenu] = useState<"symbol" | "timeframe" | "split" | null>(null);
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
  const splitOptions: Array<{ className?: string; count: 1 | 2 | 3; orientation: "vertical" | "horizontal"; label: string }> = [
    { className: "mobile-split-menu__item--wide", count: 1, orientation: chartSplitOrientation, label: "1" },
    { count: 2, orientation: "horizontal", label: "2H" },
    { count: 2, orientation: "vertical", label: "2V" },
    { count: 3, orientation: "horizontal", label: "3H" },
    { count: 3, orientation: "vertical", label: "3V" }
  ];

  const splitIcon =
    chartSplitOrientation === "horizontal"
      ? chartSplitCount === 3
        ? <Rows3 size={22} />
        : <Rows2 size={22} />
      : chartSplitCount === 3
        ? <Columns3 size={22} />
        : <Columns2 size={22} />;

  useEffect(() => {
    function handlePointerDown(event: PointerEvent) {
      const target = event.target as Element | null;
      if (
        !dropdownRootRef.current?.contains(event.target as Node) ||
        (!target?.closest(".mobile-topbar-dropdown") && !target?.closest(".mobile-split-picker"))
      ) {
        setOpenMenu(null);
      }
    }

    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, []);

  function toggleMenu(menu: "symbol" | "timeframe" | "split") {
    setOpenMenu((current) => (current === menu ? null : menu));
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
          className="mobile-topbar-dropdown__button"
          type="button"
          onClick={() => toggleMenu("symbol")}
        >
          <span>{symbolLabels?.[selectedSymbol] ?? selectedSymbol}</span>
          <ChevronDown size={14} />
        </button>
        {openMenu === "symbol" ? (
          <div className="mobile-topbar-dropdown__menu">
            {chartSymbols.map((symbol) => (
              <button
                className={symbol === selectedSymbol ? "mobile-dropdown-item mobile-dropdown-item--active" : "mobile-dropdown-item"}
                key={symbol}
                type="button"
                onClick={() => {
                  onSymbolChange(symbol);
                  setOpenMenu(null);
                }}
              >
                {symbolLabels?.[symbol] ?? symbol}
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
      <div className="mobile-split-picker">
        <button
          aria-label="Elegir graficos divididos"
          aria-expanded={openMenu === "split"}
          className={chartSplitCount > 1 ? "mobile-icon-button mobile-icon-button--active" : "mobile-icon-button"}
          type="button"
          onClick={() => toggleMenu("split")}
        >
          {splitIcon}
          <span>{chartSplitCount}</span>
        </button>
        {openMenu === "split" ? (
          <div className="mobile-split-menu">
            {splitOptions.map((option) => (
              <button
                className={
                  chartSplitCount === option.count && (option.count === 1 || chartSplitOrientation === option.orientation)
                    ? `mobile-split-menu__item ${option.className ?? ""} mobile-split-menu__item--active`
                    : `mobile-split-menu__item ${option.className ?? ""}`
                }
                key={`${option.count}-${option.orientation}`}
                type="button"
                onClick={() => {
                  onChartSplitChange(option.count, option.orientation);
                  setOpenMenu(null);
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
