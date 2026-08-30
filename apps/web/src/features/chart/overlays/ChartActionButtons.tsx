import type { PointerEvent } from "react";
import { Bot, LocateFixed, SlidersHorizontal, Trash2 } from "lucide-react";

interface ChartActionButtonsProps {
  selectedObject: { kind: "drawing" | "alert"; id: string } | null;
  canToggleTorumZone: boolean;
  isTorumZoneActive: boolean;
  canCycleTorumMultiplier: boolean;
  torumMultiplier: 1 | 2 | 3;
  canStyleSelectedObject: boolean;
  canDeleteSelectedObject: boolean;
  pullbackDebugVisible: boolean;
  styleEditorOpen: boolean;
  onCenterChart: () => void;
  onPullbackDebugToggle: () => void;
  onToggleTorumZone: (event: PointerEvent<HTMLButtonElement>) => void;
  onCycleTorumMultiplier: (event: PointerEvent<HTMLButtonElement>) => void;
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
  canCycleTorumMultiplier,
  torumMultiplier,
  canStyleSelectedObject,
  canDeleteSelectedObject,
  pullbackDebugVisible,
  onCenterChart,
  onPullbackDebugToggle,
  onToggleTorumZone,
  onCycleTorumMultiplier,
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

      {canCycleTorumMultiplier ? (
        <button
          aria-label={`Multiplicador Torum x${torumMultiplier}. Pulsar para cambiar a x${torumMultiplier === 3 ? 1 : torumMultiplier + 1}`}
          className={
            torumMultiplier > 1
              ? "chart-hard-reset-button chart-object-torum-double-button chart-object-torum-double-button--active"
              : "chart-hard-reset-button chart-object-torum-double-button"
          }
          title={`Multiplicador operativo x${torumMultiplier}. Pulsa para cambiar.`}
          type="button"
          onPointerDown={(event) => {
            // On touch devices the chart owns a long-press/pointer gesture. A
            // synthetic click can therefore be swallowed after pointerdown.
            // Cycle on the real pointer event so every deliberate tap reaches
            // the Torum control before lightweight-charts starts a gesture.
            stopBubble(event);
            onCycleTorumMultiplier(event);
          }}
          onPointerUp={stopBubble}
        >
          x{torumMultiplier}
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
        aria-label={pullbackDebugVisible ? "Ocultar pullbacks" : "Mostrar pullbacks"}
        aria-pressed={pullbackDebugVisible}
        className={pullbackDebugVisible ? "chart-hard-reset-button chart-pullback-toggle-button chart-pullback-toggle-button--active" : "chart-hard-reset-button chart-pullback-toggle-button"}
        type="button"
        onClick={onPullbackDebugToggle}
        onPointerDown={stopBubble}
        onPointerUp={stopBubble}
      >
        PB
      </button>

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
