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

interface DrawingStyleEditorProps {
  styleEditorTarget: { kind: "drawing" | "alert"; id: string } | null;
  drawings: ChartDrawingRead[];
  priceAlerts: PriceAlertRead[];
  alertVisualStyles: Record<string, PriceAlertVisualStyle>;
  defaultAlertStyle: PriceAlertVisualStyle;
  onClose: () => void;
  onUpdateDrawingStyle: (drawing: ChartDrawingRead, patch: Record<string, unknown>) => void;
  onUpdateAlertStyle: (alertId: string, patch: Partial<PriceAlertVisualStyle>) => void;
}

function stopBubble(event: React.PointerEvent) {
  event.stopPropagation();
  event.nativeEvent.stopImmediatePropagation?.();
}

export function DrawingStyleEditor({
  styleEditorTarget,
  drawings,
  priceAlerts,
  alertVisualStyles,
  defaultAlertStyle,
  onClose,
  onUpdateDrawingStyle,
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

    const isLine =
      drawing.drawing_type === "horizontal_line" ||
      drawing.drawing_type === "vertical_line" ||
      drawing.drawing_type === "trend_line";
    const isBox =
      drawing.drawing_type === "rectangle" || drawing.drawing_type === "manual_zone";
    const isText = drawing.drawing_type === "text";

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

        {isBox ? (
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
