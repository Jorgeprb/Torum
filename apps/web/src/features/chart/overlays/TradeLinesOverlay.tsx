import type { PointerEvent } from "react";

import type { TradeLineOverlay, TradeMarkerOverlay } from "../chartTypes";

interface TradeLinesOverlayProps {
  tradeLineOverlays: TradeLineOverlay[];
  tradeMarkerOverlays: TradeMarkerOverlay[];
  onSelectPosition?: (positionId: number) => void;
  onTpDragStart: (event: PointerEvent<HTMLDivElement>, line: TradeLineOverlay) => void;
}

export function TradeLinesOverlay({
  tradeLineOverlays,
  tradeMarkerOverlays,
  onSelectPosition,
  onTpDragStart
}: TradeLinesOverlayProps) {
  return (
    <div className="trade-line-layer">
      {tradeMarkerOverlays.map((marker) => (
        <div
          className={
            marker.kind === "BUY"
              ? "trade-execution-marker trade-execution-marker--buy"
              : "trade-execution-marker trade-execution-marker--close"
          }
          key={marker.id}
          style={{ left: marker.x, top: marker.y }}
        >
          <span className="trade-execution-marker__icon">
            {marker.kind === "BUY" ? "▲" : "●"}
          </span>
          <span className="trade-execution-marker__label">{marker.label}</span>
        </div>
      ))}
      {tradeLineOverlays.map((line) => (
        <div
          className={[
            "trade-line",
            `trade-line--${line.tone}`,
            line.selected ? "trade-line--selected" : "",
            line.muted ? "trade-line--muted" : "",
            line.editable ? "trade-line--editable" : ""
          ]
            .filter(Boolean)
            .join(" ")}
          key={line.id}
          style={{ top: line.y }}
          onPointerDown={(event) => {
            if (line.tone === "tp") {
              onTpDragStart(event, line);
            } else if (line.positionId) {
              event.stopPropagation();
              onSelectPosition?.(line.positionId);
            }
          }}
        >
          <span>
            {line.tone === "entry" && typeof line.profit === "number" ? (
              <>
                {line.side ?? "BUY"} {(line.volume ?? 0).toFixed(2)},{" "}
                <strong
                  className={
                    line.profit >= 0
                      ? "trade-line__money trade-line__money--profit"
                      : "trade-line__money trade-line__money--loss"
                  }
                >
                  {line.profit.toFixed(2)} {line.currency ?? ""}
                </strong>
              </>
            ) : (
              line.label
            )}
          </span>
        </div>
      ))}
    </div>
  );
}
