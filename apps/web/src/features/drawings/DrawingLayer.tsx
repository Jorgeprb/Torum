import type { DrawingCoordinate, DrawingShape } from "./drawingTypes";

interface DrawingLayerProps {
  shapes: DrawingShape[];
  pendingPoint: DrawingCoordinate | null;
  selectedDrawingId: string | null;
  onSelect: (drawingId: string | null) => void;
}

export function DrawingLayer({ shapes, pendingPoint, selectedDrawingId, onSelect }: DrawingLayerProps) {
  return (
    <svg className="drawing-layer" onClick={() => onSelect(null)}>
      {shapes.map((shape) => {
        const selected = selectedDrawingId === shape.id;
        const className = selected ? "drawing-shape drawing-shape--selected" : "drawing-shape";
        if (shape.kind === "horizontal_line") {
          return (
            <g key={shape.id} onClick={(event) => { event.stopPropagation(); onSelect(shape.id); }}>
              <line className={className} x1={shape.x1} x2={shape.x2} y1={shape.y} y2={shape.y} stroke={shape.color} strokeWidth={shape.lineWidth} />
              {shape.label ? <text className="drawing-label" x={shape.x2 - 120} y={shape.y - 6}>{shape.label}</text> : null}
            </g>
          );
        }
        if (shape.kind === "vertical_line") {
          return (
            <g key={shape.id} onClick={(event) => { event.stopPropagation(); onSelect(shape.id); }}>
              <line className={className} x1={shape.x} x2={shape.x} y1={shape.y1} y2={shape.y2} stroke={shape.color} strokeWidth={shape.lineWidth} />
              {shape.label ? <text className="drawing-label" x={shape.x + 6} y={18}>{shape.label}</text> : null}
            </g>
          );
        }
        if (shape.kind === "trend_line") {
          return (
            <g key={shape.id} onClick={(event) => { event.stopPropagation(); onSelect(shape.id); }}>
              <line className={className} x1={shape.x1} x2={shape.x2} y1={shape.y1} y2={shape.y2} stroke={shape.color} strokeWidth={shape.lineWidth} />
              {shape.label ? <text className="drawing-label" x={shape.x2 + 6} y={shape.y2 - 6}>{shape.label}</text> : null}
            </g>
          );
        }
        if (shape.kind === "rectangle" || shape.kind === "manual_zone") {
          return (
            <g key={shape.id} onClick={(event) => { event.stopPropagation(); onSelect(shape.id); }}>
              <rect
                className={className}
                fill={shape.backgroundColor}
                height={shape.height}
                stroke={shape.color}
                strokeWidth={shape.lineWidth}
                width={shape.width}
                x={shape.x}
                y={shape.y}
              />
              {shape.label ? <text className="drawing-label" x={shape.x + 8} y={shape.y + 18}>{shape.label}</text> : null}
            </g>
          );
        }
        return (
          <g key={shape.id} onClick={(event) => { event.stopPropagation(); onSelect(shape.id); }}>
            <text className={className} fill={shape.textColor} x={shape.x} y={shape.y}>
              {shape.text}
            </text>
          </g>
        );
      })}
      {pendingPoint ? <circle className="drawing-pending-point" cx={pendingPoint.x} cy={pendingPoint.y} r={4} /> : null}
    </svg>
  );
}
