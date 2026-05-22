import type { ChartDrawingRead } from "../../../services/drawings";
import type { PriceAlertRead } from "../../../services/alerts";
import type { ChartLineStyle, PriceAlertVisualStyle } from "../chartTypes";
import { styleValue } from "../../drawings/drawingUtils";
import {
  clampedNumericStyleValue,
  colorInputValue,
  hexToRgba,
  lineStyleValue
} from "../chartStyle";

export interface TorumZoneVisualStyle {
  backLayer: boolean;
  color: string;
  opacity: number;
}

interface DrawingStyleEditorProps {
  styleEditorTarget: { kind: "drawing" | "alert"; id: string } | null;
  drawings: ChartDrawingRead[];
  priceAlerts: PriceAlertRead[];
  alertVisualStyles: Record<string, PriceAlertVisualStyle>;
  defaultAlertStyle: PriceAlertVisualStyle;
  torumZoneVisualStyle: TorumZoneVisualStyle;
  onClose: () => void;
  onUpdateDrawingStyle: (drawing: ChartDrawingRead, patch: Record<string, unknown>) => void;
  onUpdateDrawingMetadata: (drawing: ChartDrawingRead, patch: Record<string, unknown>) => void;
  onUpdateTorumZoneVisualStyle: (patch: Partial<TorumZoneVisualStyle>) => void;
  onUpdateAlertStyle: (alertId: string, patch: Partial<PriceAlertVisualStyle>) => void;
}

function stopBubble(event: React.PointerEvent) {
  event.stopPropagation();
  event.nativeEvent.stopImmediatePropagation?.();
}

function isTorumV1OperationZone(drawing: ChartDrawingRead): boolean {
  const metadata = drawing.metadata ?? {};
  const payload = drawing.payload ?? {};
  return metadata.torum_v1_zone_enabled === true || payload.torum_v1_zone_enabled === true;
}

export function DrawingStyleEditor({
  styleEditorTarget,
  drawings,
  priceAlerts,
  alertVisualStyles,
  defaultAlertStyle,
  torumZoneVisualStyle,
  onClose,
  onUpdateDrawingStyle,
  onUpdateDrawingMetadata,
  onUpdateTorumZoneVisualStyle,
  onUpdateAlertStyle
}: DrawingStyleEditorProps) {
  if (!styleEditorTarget) {
    return null;
  }

  if (styleEditorTarget.kind === "drawing") {
    const drawing = drawings.find((item) => item.id === styleEditorTarget.id);
    if (!drawing) {
      return null;
    }
    const activeDrawing = drawing;

    const isLine =
      drawing.drawing_type === "horizontal_line" ||
      drawing.drawing_type === "vertical_line" ||
      drawing.drawing_type === "trend_line";
    const isBox =
      drawing.drawing_type === "rectangle" || drawing.drawing_type === "manual_zone";
    const isText = drawing.drawing_type === "text";
    const isHorizontalLine = drawing.drawing_type === "horizontal_line";
    const isTorumZone = isBox && isTorumV1OperationZone(drawing);

    const color = colorInputValue(
      styleValue(drawing.style, "color", isText ? "#edf2ef" : "#f5c542"),
      isText ? "#edf2ef" : "#f5c542"
    );
    const textColor = colorInputValue(styleValue(drawing.style, "textColor", color), color);
    const lineWidth = clampedNumericStyleValue(drawing.style, "lineWidth", 2, 1, 6);
    const glow = clampedNumericStyleValue(drawing.style, "glow", 0, 0, 18);
    const opacity = clampedNumericStyleValue(
      drawing.style,
      "opacity",
      isBox && drawing.drawing_type === "manual_zone" ? 0.16 : 0.13,
      0,
      1
    );
    const fontSize = clampedNumericStyleValue(drawing.style, "fontSize", 14, 8, 48);
    const support = typeof drawing.metadata.support === "object" && drawing.metadata.support !== null ? drawing.metadata.support as Record<string, unknown> : drawing.metadata;
    const supportLevel = Number(support.supportLevel || 0);
    const supportEnabled = support.enabled !== false;
    const basePrice = Number(drawing.payload.price || 0);
    const supportUpperPrice = Number(support.supportUpperPrice || (basePrice ? basePrice * 1.001 : 0));
    const supportLowerPrice = Number(support.supportLowerPrice || (basePrice ? basePrice * 0.999 : 0));
    const supportOpacity = clampedNumericStyleValue(support, "opacity", 0.20, 0, 1);

    function updateSupport(patch: Record<string, unknown>) {
      onUpdateDrawingMetadata(activeDrawing, { ...activeDrawing.metadata, ...patch });
    }

    return (
      <div
        className="chart-style-popover"
        onPointerDown={stopBubble}
        onPointerUp={stopBubble}
      >
        <div className="chart-style-popover__head">
          <strong>{isText ? "Texto" : isBox ? "Rectangulo" : "Linea"}</strong>
          <button type="button" onClick={onClose}>x</button>
        </div>

        {isLine ? (
          <>
            <label>
              Color
              <input
                type="color"
                value={color}
                onChange={(e) => onUpdateDrawingStyle(drawing, { color: e.target.value })}
              />
            </label>
            <label>
              Tipo
              <select
                value={lineStyleValue(drawing.style)}
                onChange={(e) => onUpdateDrawingStyle(drawing, { lineStyle: e.target.value as ChartLineStyle })}
              >
                <option value="solid">Continua</option>
                <option value="dashed">Discontinua</option>
              </select>
            </label>
            <label>
              Grosor
              <input
                min="1" max="6" step="1" type="range" value={lineWidth}
                onChange={(e) => onUpdateDrawingStyle(drawing, { lineWidth: Number(e.target.value) })}
              />
              <span>{lineWidth}</span>
            </label>
            <label>
              Glow
              <input
                min="0" max="18" step="1" type="range" value={glow}
                onChange={(e) => onUpdateDrawingStyle(drawing, { glow: Number(e.target.value) })}
              />
              <span>{glow}</span>
            </label>
          </>
        ) : null}

        {isHorizontalLine ? (
          <div className="chart-style-popover__group">
            <label>
              Soporte
              <select
                value={supportLevel === 1 || supportLevel === 2 || supportLevel === 3 ? String(supportLevel) : "none"}
                onChange={(e) => {
                  const next = e.target.value === "none" ? null : Number(e.target.value);
                  if (next === null) {
                    updateSupport({ supportLevel: "none", enabled: false });
                    return;
                  }
                  updateSupport({
                    supportLevel: next,
                    enabled: true,
                    supportUpperPrice: supportUpperPrice || basePrice * 1.001,
                    supportLowerPrice: supportLowerPrice || basePrice * 0.999,
                    opacity: supportOpacity
                  });
                }}
              >
                <option value="none">Sin soporte</option>
                <option value="1">S1</option>
                <option value="2">S2</option>
                <option value="3">S3</option>
              </select>
            </label>
            {supportLevel === 1 || supportLevel === 2 || supportLevel === 3 ? (
              <>
                <label className="toggle-line">
                  <input
                    checked={supportEnabled}
                    type="checkbox"
                    onChange={(e) => updateSupport({ enabled: e.target.checked })}
                  />
                  Activo
                </label>
                <label>
                  Limite superior
                  <input
                    type="number"
                    step="0.01"
                    value={supportUpperPrice}
                    onChange={(e) => updateSupport({ supportUpperPrice: Number(e.target.value) })}
                  />
                </label>
                <label>
                  Limite inferior
                  <input
                    type="number"
                    step="0.01"
                    value={supportLowerPrice}
                    onChange={(e) => updateSupport({ supportLowerPrice: Number(e.target.value) })}
                  />
                </label>
                <label>
                  Opacidad
                  <input
                    min="0" max="1" step="0.01" type="range" value={supportOpacity}
                    onChange={(e) => updateSupport({ opacity: Number(e.target.value) })}
                  />
                  <span>{Math.round(supportOpacity * 100)}%</span>
                </label>
              </>
            ) : null}
          </div>
        ) : null}

        {isBox && isTorumZone ? (
          <div className="chart-style-popover__group">
            <div className="chart-style-popover__hint">
              Estilo global para todas las zonas Torum.
            </div>
            <label>
              Color zona Torum
              <input
                type="color"
                value={colorInputValue(torumZoneVisualStyle.color, "#2f8cff")}
                onChange={(e) => onUpdateTorumZoneVisualStyle({ color: e.target.value })}
              />
            </label>
            <label>
              Opacidad zona Torum
              <input
                min="0" max="1" step="0.01" type="range" value={torumZoneVisualStyle.opacity}
                onChange={(e) => onUpdateTorumZoneVisualStyle({ opacity: Number(e.target.value) })}
              />
              <span>{Math.round(torumZoneVisualStyle.opacity * 100)}%</span>
            </label>
            <label className="toggle-line">
              <input
                checked={torumZoneVisualStyle.backLayer}
                type="checkbox"
                onChange={(e) => onUpdateTorumZoneVisualStyle({ backLayer: e.target.checked })}
              />
              Fondo
            </label>
          </div>
        ) : null}

        {isBox && !isTorumZone ? (
          <>
            <label>
              Color
              <input
                type="color"
                value={color}
                onChange={(e) =>
                  onUpdateDrawingStyle(drawing, {
                    color: e.target.value,
                    backgroundColor: hexToRgba(e.target.value, opacity)
                  })
                }
              />
            </label>
            <label>
              Opacidad
              <input
                min="0" max="1" step="0.01" type="range" value={opacity}
                onChange={(e) => {
                  const nextOpacity = Number(e.target.value);
                  onUpdateDrawingStyle(drawing, {
                    opacity: nextOpacity,
                    backgroundColor: hexToRgba(color, nextOpacity)
                  });
                }}
              />
              <span>{Math.round(opacity * 100)}%</span>
            </label>
          </>
        ) : null}

        {isText ? (
          <>
            <label>
              Color
              <input
                type="color"
                value={textColor}
                onChange={(e) =>
                  onUpdateDrawingStyle(drawing, { color: e.target.value, textColor: e.target.value })
                }
              />
            </label>
            <label>
              Tamano
              <input
                min="8" max="48" step="1" type="range" value={fontSize}
                onChange={(e) => onUpdateDrawingStyle(drawing, { fontSize: Number(e.target.value) })}
              />
              <span>{fontSize}</span>
            </label>
            <label>
              Glow
              <input
                min="0" max="18" step="1" type="range" value={glow}
                onChange={(e) => onUpdateDrawingStyle(drawing, { glow: Number(e.target.value) })}
              />
              <span>{glow}</span>
            </label>
          </>
        ) : null}
      </div>
    );
  }

  const alert = priceAlerts.find((item) => item.id === styleEditorTarget.id);
  if (!alert) {
    return null;
  }

  const style = alertVisualStyles[alert.id] ?? defaultAlertStyle;
  const color = colorInputValue(style.color, defaultAlertStyle.color);

  return (
    <div
      className="chart-style-popover"
      onPointerDown={stopBubble}
      onPointerUp={stopBubble}
    >
      <div className="chart-style-popover__head">
        <strong>Alerta</strong>
        <button type="button" onClick={onClose}>x</button>
      </div>
      <label>
        Color
        <input
          type="color"
          value={color}
          onChange={(e) => onUpdateAlertStyle(alert.id, { color: e.target.value })}
        />
      </label>
      <label>
        Tipo
        <select
          value={style.lineStyle}
          onChange={(e) => onUpdateAlertStyle(alert.id, { lineStyle: e.target.value as ChartLineStyle })}
        >
          <option value="solid">Continua</option>
          <option value="dashed">Discontinua</option>
        </select>
      </label>
    </div>
  );
}
