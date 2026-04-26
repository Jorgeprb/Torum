import { Eye, EyeOff, Save, Trash2 } from "lucide-react";
import { useState } from "react";

import type { ChartDrawingRead } from "../../services/drawings";
import { drawingLabel, styleValue } from "./drawingUtils";

interface DrawingPanelProps {
  drawings: ChartDrawingRead[];
  selectedDrawingId: string | null;
  onSelect: (drawingId: string | null) => void;
  onUpdate: (drawing: ChartDrawingRead, patch: { name?: string | null; style?: Record<string, unknown>; visible?: boolean }) => Promise<void>;
  onDelete: (drawingId: string) => Promise<void>;
}

export function DrawingPanel({ drawings, selectedDrawingId, onSelect, onUpdate, onDelete }: DrawingPanelProps) {
  const [drafts, setDrafts] = useState<Record<string, { name: string; color: string }>>({});

  function draftFor(drawing: ChartDrawingRead) {
    return drafts[drawing.id] ?? { name: drawing.name ?? drawingLabel(drawing), color: styleValue(drawing.style, "color", "#f5c542") };
  }

  return (
    <section className="panel drawing-panel">
      <div className="panel-title">Dibujos</div>
      {drawings.length === 0 ? <div className="muted-copy">Sin dibujos guardados para este simbolo/timeframe.</div> : null}
      <div className="drawing-list">
        {drawings.map((drawing) => {
          const draft = draftFor(drawing);
          return (
            <div className={selectedDrawingId === drawing.id ? "drawing-row drawing-row--selected" : "drawing-row"} key={drawing.id}>
              <button className="drawing-row__main" type="button" onClick={() => onSelect(drawing.id)}>
                <span>{drawing.drawing_type}</span>
                <strong>{drawingLabel(drawing)}</strong>
                <small>{drawing.source}{drawing.locked ? " · locked" : ""}</small>
              </button>
              <input
                aria-label="Nombre"
                value={draft.name}
                onChange={(event) => setDrafts((current) => ({ ...current, [drawing.id]: { ...draft, name: event.target.value } }))}
              />
              <input
                aria-label="Color"
                type="color"
                value={draft.color}
                onChange={(event) => setDrafts((current) => ({ ...current, [drawing.id]: { ...draft, color: event.target.value } }))}
              />
              <div className="drawing-row__actions">
                <button
                  className="icon-tool"
                  title="Guardar"
                  type="button"
                  onClick={() => onUpdate(drawing, { name: draft.name, style: { ...drawing.style, color: draft.color } })}
                >
                  <Save size={16} />
                </button>
                <button
                  className="icon-tool"
                  title={drawing.visible ? "Ocultar" : "Mostrar"}
                  type="button"
                  onClick={() => onUpdate(drawing, { visible: !drawing.visible })}
                >
                  {drawing.visible ? <Eye size={16} /> : <EyeOff size={16} />}
                </button>
                <button className="icon-tool icon-tool--danger" title="Eliminar" type="button" onClick={() => onDelete(drawing.id)}>
                  <Trash2 size={16} />
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
