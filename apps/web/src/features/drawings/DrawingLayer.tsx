import { useRef, useState, type CSSProperties, type PointerEvent } from "react";

import type { DrawingCoordinate, DrawingDragAction, DrawingShape } from "./drawingTypes";

interface DrawingLayerProps {
  interactive?: boolean;
  shapes: DrawingShape[];
  pendingPoint: DrawingCoordinate | null;
  selectedDrawingId: string | null;
  onSelect: (drawingId: string | null) => void;
  onDragStart?: (shape: DrawingShape) => void;
  onDragEnd?: (shape: DrawingShape) => void;
}

interface DragState {
  action: DrawingDragAction;
  currentX: number;
  currentY: number;
  shape: DrawingShape;
  startX: number;
  startY: number;
}

function moveShape(shape: DrawingShape, dx: number, dy: number, action: DrawingDragAction): DrawingShape {
  if (shape.kind === "horizontal_line") {
    return { ...shape, y: shape.y + dy };
  }

  if (shape.kind === "vertical_line") {
    return { ...shape, x: shape.x + dx };
  }

  if (shape.kind === "text") {
    return { ...shape, x: shape.x + dx, y: shape.y + dy };
  }

  if (shape.kind === "trend_line") {
    if (action === "p1") {
      return { ...shape, x1: shape.x1 + dx, y1: shape.y1 + dy };
    }

    if (action === "p2") {
      return { ...shape, x2: shape.x2 + dx, y2: shape.y2 + dy };
    }

    return {
      ...shape,
      x1: shape.x1 + dx,
      x2: shape.x2 + dx,
      y1: shape.y1 + dy,
      y2: shape.y2 + dy
    };
  }

  if (shape.kind === "rectangle" || shape.kind === "manual_zone") {
    if (action === "move") {
      return { ...shape, x: shape.x + dx, y: shape.y + dy };
    }

    let left = shape.x;
    let right = shape.x + shape.width;
    let top = shape.y;
    let bottom = shape.y + shape.height;

    if (action.includes("left")) left += dx;
    if (action.includes("right")) right += dx;
    if (action.includes("top")) top += dy;
    if (action.includes("bottom")) bottom += dy;

    return {
      ...shape,
      height: Math.max(2, Math.abs(bottom - top)),
      width: Math.max(2, Math.abs(right - left)),
      x: Math.min(left, right),
      y: Math.min(top, bottom)
    };
  }

  return shape;
}

function lineDash(shape: DrawingShape): string | undefined {
  return shape.lineStyle === "dashed" ? "8 6" : undefined;
}

function glowStyle(shape: DrawingShape, selected: boolean): CSSProperties | undefined {
  const glow = selected ? Math.max(shape.glow, 5) : shape.glow;
  if (!Number.isFinite(glow) || glow <= 0) {
    return undefined;
  }

  return { filter: `drop-shadow(0 0 ${glow}px ${shape.color})` };
}

export function DrawingLayer({ interactive = true, shapes, pendingPoint, selectedDrawingId, onSelect, onDragStart, onDragEnd }: DrawingLayerProps) {
  const suppressNextClearRef = useRef(false);
  const [dragState, setDragState] = useState<DragState | null>(null);

  function start(event: PointerEvent<SVGElement>, shape: DrawingShape, action: DrawingDragAction = "move") {
    if (!interactive) {
      return;
    }

    if (shape.drawing.locked) {
      return;
    }

    event.preventDefault();
    event.stopPropagation();
    event.nativeEvent.stopImmediatePropagation?.();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    suppressNextClearRef.current = true;
    const startX = event.clientX;
    const startY = event.clientY;

    onSelect(shape.id);
    onDragStart?.(shape);
    setDragState({ action, currentX: startX, currentY: startY, shape, startX, startY });

    function finish(pointerEvent: globalThis.PointerEvent | null) {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", cancel);

      const currentX = pointerEvent?.clientX ?? startX;
      const currentY = pointerEvent?.clientY ?? startY;
      const finalShape = moveShape(shape, currentX - startX, currentY - startY, action);

      setDragState(null);
      onSelect(shape.id);
      onDragEnd?.(finalShape);

      window.setTimeout(() => {
        suppressNextClearRef.current = false;
      }, 0);
    }

    function move(pointerEvent: globalThis.PointerEvent) {
      pointerEvent.preventDefault();
      setDragState({ action, currentX: pointerEvent.clientX, currentY: pointerEvent.clientY, shape, startX, startY });
    }

    function up(pointerEvent: globalThis.PointerEvent) {
      pointerEvent.preventDefault();
      finish(pointerEvent);
    }

    function cancel() {
      finish(null);
    }

    window.addEventListener("pointermove", move, { passive: false });
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", cancel);
  }

  function clearSelection() {
    if (suppressNextClearRef.current) {
      return;
    }

    onSelect(null);
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
        r={10}
        onClick={(event) => event.stopPropagation()}
        onPointerDown={(event) => start(event, shape, item.action)}
      />
    ));
  }

  const renderedShapes = shapes.map((shape) =>
    dragState?.shape.id === shape.id
      ? moveShape(dragState.shape, dragState.currentX - dragState.startX, dragState.currentY - dragState.startY, dragState.action)
      : shape
  );

  return (
    <svg className={interactive ? "drawing-layer" : "drawing-layer drawing-layer--passive"} onClick={interactive ? clearSelection : undefined}>
      {renderedShapes.map((shape) => {
        const selected = selectedDrawingId === shape.id;
        const className = selected ? "drawing-shape drawing-shape--selected" : "drawing-shape";
        if (shape.kind === "horizontal_line") {
          return (
            <g key={shape.id} onClick={(event) => event.stopPropagation()} onPointerDown={(event) => start(event, shape, "move")}>
              <line className="drawing-hit-area" x1={shape.x1} x2={shape.x2} y1={shape.y} y2={shape.y} stroke="rgba(0,0,0,0)" strokeWidth={Math.max(26, shape.lineWidth + 18)} />
              <line className={className} style={glowStyle(shape, selected)} strokeDasharray={lineDash(shape)} x1={shape.x1} x2={shape.x2} y1={shape.y} y2={shape.y} stroke={shape.color} strokeWidth={shape.lineWidth} />
              {shape.label ? <text className="drawing-label" x={shape.x2 - 120} y={shape.y - 6}>{shape.label}</text> : null}
              {handles(shape)}
            </g>
          );
        }
        if (shape.kind === "vertical_line") {
          return (
            <g key={shape.id} onClick={(event) => event.stopPropagation()} onPointerDown={(event) => start(event, shape, "move")}>
              <line className="drawing-hit-area" x1={shape.x} x2={shape.x} y1={shape.y1} y2={shape.y2} stroke="rgba(0,0,0,0)" strokeWidth={Math.max(26, shape.lineWidth + 18)} />
              <line className={className} style={glowStyle(shape, selected)} strokeDasharray={lineDash(shape)} x1={shape.x} x2={shape.x} y1={shape.y1} y2={shape.y2} stroke={shape.color} strokeWidth={shape.lineWidth} />
              {shape.label ? <text className="drawing-label" x={shape.x + 6} y={18}>{shape.label}</text> : null}
              {handles(shape)}
            </g>
          );
        }
        if (shape.kind === "trend_line") {
          return (
            <g key={shape.id} onClick={(event) => event.stopPropagation()} onPointerDown={(event) => start(event, shape, "move")}>
              <line className="drawing-hit-area" x1={shape.x1} x2={shape.x2} y1={shape.y1} y2={shape.y2} stroke="rgba(0,0,0,0)" strokeWidth={Math.max(26, shape.lineWidth + 18)} />
              <line className={className} style={glowStyle(shape, selected)} strokeDasharray={lineDash(shape)} x1={shape.x1} x2={shape.x2} y1={shape.y1} y2={shape.y2} stroke={shape.color} strokeWidth={shape.lineWidth} />
              {shape.label ? <text className="drawing-label" x={shape.x2 + 6} y={shape.y2 - 6}>{shape.label}</text> : null}
              {handles(shape)}
            </g>
          );
        }
        if (shape.kind === "rectangle" || shape.kind === "manual_zone") {
          return (
            <g key={shape.id} onClick={(event) => event.stopPropagation()} onPointerDown={(event) => start(event, shape, "move")}>
              <rect
                className="drawing-hit-area"
                fill="transparent"
                height={shape.height}
                stroke="rgba(0,0,0,0)"
                strokeWidth={24}
                width={shape.width}
                x={shape.x}
                y={shape.y}
              />
              <rect
                className={className}
                fill={shape.backgroundColor}
                height={shape.height}
                style={glowStyle(shape, selected)}
                strokeDasharray={lineDash(shape)}
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
            <text className="drawing-hit-area" fill="transparent" fontSize={shape.fontSize} stroke="rgba(0,0,0,0)" strokeWidth={24} x={shape.x} y={shape.y}>
              {shape.text}
            </text>
            <text className={className} fill={shape.textColor} fontSize={shape.fontSize} style={glowStyle(shape, selected)} x={shape.x} y={shape.y}>
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
