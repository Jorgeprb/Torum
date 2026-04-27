import type { PointerEvent } from "react";

import type { DrawingCoordinate, DrawingDragAction, DrawingShape } from "./drawingTypes";

interface DrawingLayerProps {
  shapes: DrawingShape[];
  pendingPoint: DrawingCoordinate | null;
  selectedDrawingId: string | null;
  onSelect: (drawingId: string | null) => void;
  onDragStart?: (event: PointerEvent<SVGElement>, shape: DrawingShape, action: DrawingDragAction) => void;
}

export function DrawingLayer({ shapes, pendingPoint, selectedDrawingId, onSelect, onDragStart }: DrawingLayerProps) {
  function start(event: PointerEvent<SVGElement>, shape: DrawingShape, action: DrawingDragAction = "move") {
    event.preventDefault();
    event.stopPropagation();
    onSelect(shape.id);
    onDragStart?.(event, shape, action);
  }

  function handles(shape: DrawingShape) {
    if (selectedDrawingId !== shape.id) {
      return null;
    }
    const handleItems: Array<{ x: number; y: number; action: DrawingDragAction }> = [];
    if (shape.kind === "horizontal_line") {
      handleItems.push({ x: Math.max(12, shape.x2 - 34), y: shape.y, action: "move" });
    } else if (shape.kind === "vertical_line") {
      handleItems.push({ x: shape.x, y: 22, action: "move" });
    } else if (shape.kind === "trend_line") {
      handleItems.push({ x: shape.x1, y: shape.y1, action: "p1" }, { x: shape.x2, y: shape.y2, action: "p2" });
    } else if (shape.kind === "rectangle" || shape.kind === "manual_zone") {
      const right = shape.x + shape.width;
      const bottom = shape.y + shape.height;
      handleItems.push(
        { x: shape.x, y: shape.y, action: "top-left" },
        { x: right, y: shape.y, action: "top-right" },
        { x: shape.x, y: bottom, action: "bottom-left" },
        { x: right, y: bottom, action: "bottom-right" }
      );
    } else if (shape.kind === "text") {
      handleItems.push({ x: shape.x, y: shape.y, action: "move" });
    }
    return handleItems.map((item) => (
      <circle
        className="drawing-handle"
        cx={item.x}
        cy={item.y}
        key={`${shape.id}-${item.action}`}
        r={5}
        onPointerDown={(event) => start(event, shape, item.action)}
      />
    ));
  }

  return (
    <svg className="drawing-layer" onClick={() => onSelect(null)}>
      {shapes.map((shape) => {
        const selected = selectedDrawingId === shape.id;
        const className = selected ? "drawing-shape drawing-shape--selected" : "drawing-shape";
        if (shape.kind === "horizontal_line") {
          return (
            <g key={shape.id} onClick={(event) => event.stopPropagation()} onPointerDown={(event) => start(event, shape, "move")}>
              <line className={className} x1={shape.x1} x2={shape.x2} y1={shape.y} y2={shape.y} stroke={shape.color} strokeWidth={shape.lineWidth} />
              {shape.label ? <text className="drawing-label" x={shape.x2 - 120} y={shape.y - 6}>{shape.label}</text> : null}
              {handles(shape)}
            </g>
          );
        }
        if (shape.kind === "vertical_line") {
          return (
            <g key={shape.id} onClick={(event) => event.stopPropagation()} onPointerDown={(event) => start(event, shape, "move")}>
              <line className={className} x1={shape.x} x2={shape.x} y1={shape.y1} y2={shape.y2} stroke={shape.color} strokeWidth={shape.lineWidth} />
              {shape.label ? <text className="drawing-label" x={shape.x + 6} y={18}>{shape.label}</text> : null}
              {handles(shape)}
            </g>
          );
        }
        if (shape.kind === "trend_line") {
          return (
            <g key={shape.id} onClick={(event) => event.stopPropagation()} onPointerDown={(event) => start(event, shape, "move")}>
              <line className={className} x1={shape.x1} x2={shape.x2} y1={shape.y1} y2={shape.y2} stroke={shape.color} strokeWidth={shape.lineWidth} />
              {shape.label ? <text className="drawing-label" x={shape.x2 + 6} y={shape.y2 - 6}>{shape.label}</text> : null}
              {handles(shape)}
            </g>
          );
        }
        if (shape.kind === "rectangle" || shape.kind === "manual_zone") {
          return (
            <g key={shape.id} onClick={(event) => event.stopPropagation()} onPointerDown={(event) => start(event, shape, "move")}>
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
              {handles(shape)}
            </g>
          );
        }
        return (
          <g key={shape.id} onClick={(event) => event.stopPropagation()} onPointerDown={(event) => start(event, shape, "move")}>
            <text className={className} fill={shape.textColor} x={shape.x} y={shape.y}>
              {shape.text}
            </text>
            {handles(shape)}
          </g>
        );
      })}
      {pendingPoint ? <circle className="drawing-pending-point" cx={pendingPoint.x} cy={pendingPoint.y} r={4} /> : null}
    </svg>
  );
}
