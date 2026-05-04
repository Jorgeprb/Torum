import type { CSSProperties, PointerEvent } from "react";

import type { DrawingDragAction, DrawingShape } from "../../drawings/drawingTypes";

interface DrawingHtmlLayerProps {
  shapes: DrawingShape[];
  selectedDrawingId: string | null;
  onDragStart: (
    event: PointerEvent<HTMLElement>,
    shape: DrawingShape,
    action: DrawingDragAction
  ) => void;
}

function drawingHandleStyle(
  x: number,
  y: number,
  cursor: CSSProperties["cursor"],
  size = 18,
  color?: string
): CSSProperties {
  return {
    backgroundColor: color,
    cursor,
    height: size,
    left: x - size / 2,
    pointerEvents: "auto",
    top: y - size / 2,
    width: size
  };
}

function drawingCenter(shape: DrawingShape): { x: number; y: number } {
  if (shape.kind === "horizontal_line") {
    return { x: (shape.x1 + shape.x2) / 2, y: shape.y };
  }

  if (shape.kind === "vertical_line") {
    return { x: shape.x, y: (shape.y1 + shape.y2) / 2 };
  }

  if (shape.kind === "trend_line") {
    return { x: (shape.x1 + shape.x2) / 2, y: (shape.y1 + shape.y2) / 2 };
  }

  if (shape.kind === "text") {
    return {
      x: shape.x + Math.max(54, shape.text.length * shape.fontSize * 0.58 + 28) / 2,
      y: shape.y - shape.fontSize / 2
    };
  }

  return { x: shape.x + shape.width / 2, y: shape.y + shape.height / 2 };
}

function DrawingHtmlHandles({
  shape,
  onDragStart
}: {
  shape: DrawingShape;
  onDragStart: DrawingHtmlLayerProps["onDragStart"];
}) {
  const center = drawingCenter(shape);

  const centerHandle = (
    <button
      aria-label="Mover dibujo"
      className="drawing-html-handle drawing-html-handle--center"
      style={drawingHandleStyle(center.x, center.y, "move", 18, shape.color)}
      type="button"
      onPointerDown={(event) => onDragStart(event, shape, "move")}
    />
  );

  if (shape.kind === "trend_line") {
    return (
      <>
        {centerHandle}
        <button
          aria-label="Mover punto inicial"
          className="drawing-html-handle"
          style={drawingHandleStyle(shape.x1, shape.y1, "move", 16, shape.color)}
          type="button"
          onPointerDown={(event) => onDragStart(event, shape, "p1")}
        />
        <button
          aria-label="Mover punto final"
          className="drawing-html-handle"
          style={drawingHandleStyle(shape.x2, shape.y2, "move", 16, shape.color)}
          type="button"
          onPointerDown={(event) => onDragStart(event, shape, "p2")}
        />
      </>
    );
  }

  if (shape.kind !== "rectangle" && shape.kind !== "manual_zone") {
    return centerHandle;
  }

  const right = shape.x + shape.width;
  const bottom = shape.y + shape.height;

  return (
    <>
      {centerHandle}
      <button
        aria-label="Escalar arriba izquierda"
        className="drawing-html-handle"
        style={drawingHandleStyle(shape.x, shape.y, "nwse-resize", 14, shape.color)}
        type="button"
        onPointerDown={(event) => onDragStart(event, shape, "top-left")}
      />
      <button
        aria-label="Escalar arriba derecha"
        className="drawing-html-handle"
        style={drawingHandleStyle(right, shape.y, "nesw-resize", 14, shape.color)}
        type="button"
        onPointerDown={(event) => onDragStart(event, shape, "top-right")}
      />
      <button
        aria-label="Escalar abajo izquierda"
        className="drawing-html-handle"
        style={drawingHandleStyle(shape.x, bottom, "nesw-resize", 14, shape.color)}
        type="button"
        onPointerDown={(event) => onDragStart(event, shape, "bottom-left")}
      />
      <button
        aria-label="Escalar abajo derecha"
        className="drawing-html-handle"
        style={drawingHandleStyle(right, bottom, "nwse-resize", 14, shape.color)}
        type="button"
        onPointerDown={(event) => onDragStart(event, shape, "bottom-right")}
      />
    </>
  );
}

export function DrawingHtmlLayer({ shapes, selectedDrawingId, onDragStart }: DrawingHtmlLayerProps) {
  return (
    <div
      aria-hidden={shapes.length === 0 ? "true" : undefined}
      className="drawing-html-hit-layer"
      style={{ pointerEvents: "none" }}
    >
      {shapes.map((shape) => {
        const selected = selectedDrawingId === shape.id;
        return (
          <div key={shape.id} style={{ pointerEvents: "none" }}>
            {selected ? (
              <DrawingHtmlHandles shape={shape} onDragStart={onDragStart} />
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
