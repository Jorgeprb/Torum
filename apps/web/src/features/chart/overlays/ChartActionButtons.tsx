import type { PointerEvent } from "react";
import { Bot, LocateFixed, SlidersHorizontal, Trash2 } from "lucide-react";

interface ChartActionButtonsProps {
  selectedObject: { kind: "drawing" | "alert"; id: string } | null;
  canToggleTorumZone: boolean;
  isTorumZoneActive: boolean;
  canStyleSelectedObject: boolean;
  canDeleteSelectedObject: boolean;
  styleEditorOpen: boolean;
  onCenterChart: () => void;
  onToggleTorumZone: (event: PointerEvent<HTMLButtonElement>) => void;
  onStyleButton: (event: PointerEvent<HTMLButtonElement>) => void;
  onDeleteButton: (event: PointerEvent<HTMLButtonElement>) => void;
}

function stopBubble(event: PointerEvent<HTMLButtonElement>) {
  event.stopPropagation();
  event.nativeEvent.stopImmediatePropagation?.();
}

export function ChartActionButtons({
  selectedObject,
  canToggleTorumZone,
  isTorumZoneActive,
  canStyleSelectedObject,
  canDeleteSelectedObject,
  onCenterChart,
  onToggleTorumZone,
  onStyleButton,
  onDeleteButton
}: ChartActionButtonsProps) {
  return (
    <>
      {canToggleTorumZone ? (
        <button
          aria-label={isTorumZoneActive ? "Desactivar zona Torum V1" : "Activar zona Torum V1"}
          className={
            isTorumZoneActive
              ? "chart-hard-reset-button chart-object-torum-zone-button chart-object-torum-zone-button--active"
              : "chart-hard-reset-button chart-object-torum-zone-button"
          }
          type="button"
          onClick={onToggleTorumZone}
          onPointerDown={stopBubble}
          onPointerUp={stopBubble}
        >
          <Bot size={16} />
        </button>
      ) : null}

      {selectedObject && canStyleSelectedObject ? (
        <button
          aria-label="Editar estilo"
          className="chart-hard-reset-button chart-object-style-button"
          type="button"
          onClick={onStyleButton}
          onPointerDown={stopBubble}
          onPointerUp={stopBubble}
        >
          <SlidersHorizontal size={16} />
        </button>
      ) : null}

      {selectedObject && canDeleteSelectedObject ? (
        <button
          aria-label="Eliminar elemento"
          className="chart-hard-reset-button chart-object-delete-button"
          type="button"
          onClick={onDeleteButton}
          onPointerDown={stopBubble}
          onPointerUp={stopBubble}
        >
          <Trash2 size={16} />
        </button>
      ) : null}

      <button
        aria-label="Centrar grafico"
        className="chart-hard-reset-button"
        type="button"
        onClick={onCenterChart}
        onPointerDown={(event) => event.stopPropagation()}
      >
        <LocateFixed size={16} />
      </button>
    </>
  );
}
