import type { PointerEvent } from "react";
import { Bell } from "lucide-react";

import type { PriceAlertRead } from "../../../services/alerts";
import type { PriceAlertOverlay, PriceAlertVisualStyle } from "../chartTypes";
import { cssLineStyle } from "../chartStyle";

interface PriceAlertsOverlayProps {
  priceAlertOverlays: PriceAlertOverlay[];
  alertVisualStyles: Record<string, PriceAlertVisualStyle>;
  selectedAlertId: string | null;
  onCancelPriceAlert?: (alertId: string) => void;
  onDragStart: (event: PointerEvent<HTMLDivElement>, alert: PriceAlertRead) => void;
  onPointerUp: (event: PointerEvent<HTMLDivElement>) => void;
  onAlertCancel: (alertId: string) => void;
}

export function PriceAlertsOverlay({
  priceAlertOverlays,
  alertVisualStyles,
  selectedAlertId,
  onCancelPriceAlert,
  onDragStart,
  onPointerUp,
  onAlertCancel
}: PriceAlertsOverlayProps) {
  return (
    <div className="price-alert-layer">
      {priceAlertOverlays.map((overlay) => {
        const alertStyle = alertVisualStyles[overlay.alert.id] ?? { color: "#f5c542", lineStyle: "dashed" as const };
        const isSelected = selectedAlertId === overlay.alert.id;

        return (
          <div
            className={isSelected ? "price-alert-line price-alert-line--selected" : "price-alert-line"}
            key={overlay.alert.id}
            style={{
              borderTopColor: alertStyle.color,
              borderTopStyle: cssLineStyle(alertStyle.lineStyle),
              top: overlay.y
            }}
            onPointerDown={(event) => onDragStart(event, overlay.alert)}
            onPointerUp={(event) => {
              event.stopPropagation();
              event.nativeEvent.stopImmediatePropagation?.();
            }}
          >
            <span style={{ borderColor: alertStyle.color, color: alertStyle.color }}>
              <Bell aria-hidden="true" size={13} strokeWidth={3} />
              {onCancelPriceAlert ? (
                <button
                  aria-label="Cancelar alerta"
                  className="inline-delete"
                  type="button"
                  onPointerDown={(event) => {
                    event.stopPropagation();
                    event.nativeEvent.stopImmediatePropagation?.();
                  }}
                  onClick={(event) => {
                    event.stopPropagation();
                    onAlertCancel(overlay.alert.id);
                  }}
                >
                  x
                </button>
              ) : null}
            </span>
          </div>
        );
      })}
    </div>
  );
}
