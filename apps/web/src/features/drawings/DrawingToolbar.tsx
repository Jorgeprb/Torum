import { Eye, EyeOff, Minus, MousePointer, SeparatorVertical, Square, Trash2, TrendingUp, Type } from "lucide-react";

import type { DrawingTool } from "../../services/drawings";
import { toolName } from "./drawingUtils";

interface DrawingToolbarProps {
  activeTool: DrawingTool;
  drawingsVisible: boolean;
  selectedDrawingId: string | null;
  onToolChange: (tool: DrawingTool) => void;
  onToggleDrawings: () => void;
  onDeleteSelected: () => void;
}

const tools: Array<{ tool: DrawingTool; icon: JSX.Element }> = [
  { tool: "select", icon: <MousePointer size={16} /> },
  { tool: "horizontal_line", icon: <Minus size={16} /> },
  { tool: "vertical_line", icon: <SeparatorVertical size={16} /> },
  { tool: "trend_line", icon: <TrendingUp size={16} /> },
  { tool: "rectangle", icon: <Square size={16} /> },
  { tool: "text", icon: <Type size={16} /> },
  { tool: "manual_zone", icon: <Square size={16} /> }
];

export function DrawingToolbar({
  activeTool,
  drawingsVisible,
  selectedDrawingId,
  onToolChange,
  onToggleDrawings,
  onDeleteSelected
}: DrawingToolbarProps) {
  return (
    <div className="drawing-toolbar" aria-label="Herramientas de dibujo">
      {tools.map(({ tool, icon }) => (
        <button
          className={activeTool === tool ? "icon-tool icon-tool--active" : "icon-tool"}
          key={tool}
          title={toolName(tool)}
          type="button"
          onClick={() => onToolChange(tool)}
        >
          {icon}
          {tool === "manual_zone" ? <span>Z</span> : null}
        </button>
      ))}
      <button className="icon-tool" title={drawingsVisible ? "Ocultar dibujos" : "Mostrar dibujos"} type="button" onClick={onToggleDrawings}>
        {drawingsVisible ? <Eye size={16} /> : <EyeOff size={16} />}
      </button>
      <button className="icon-tool icon-tool--danger" disabled={!selectedDrawingId} title="Eliminar seleccionado" type="button" onClick={onDeleteSelected}>
        <Trash2 size={16} />
      </button>
    </div>
  );
}
