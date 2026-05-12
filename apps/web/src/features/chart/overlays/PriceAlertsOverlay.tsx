import type { PointerEvent } from "react";
import { Bell } from "lucide-react";

import type { PriceAlertRead } from "../../../services/alerts";
import type { PriceAlertOverlay, PriceAlertVisualStyle } from "../chartTypes";
import { cssLineStyle } from "../chartStyle";

interface PriceAlertsOverlayProps {
  priceAlertOverlays: PriceAlertOverlay[];
  alertVisualStyles: Record<string, PriceAlertVisualStyle>;
  selectedAlertId: string | null;
  onDragStart: (event: PointerEvent<HTMLDivElement>, alert: PriceAlertRead) => void;
}

export function PriceAlertsOverlay({
  priceAlertOverlays,
  alertVisualStyles,
  selectedAlertId,
  onDragStart
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
            </span>
          </div>
        );
      })}
    </div>
  );
}
