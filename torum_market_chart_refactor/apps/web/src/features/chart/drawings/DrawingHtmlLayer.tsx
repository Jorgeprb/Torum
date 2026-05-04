import type { CSSProperties, PointerEvent } from "react";
import type { DrawingDragAction, DrawingShape } from "../../drawings/drawingTypes";

interface DrawingHtmlLayerProps {
  drawingShapes: DrawingShape[];
  selectedDrawingId: string | null;
  onStartDrag: (event: PointerEvent<HTMLButtonElement>, shape: DrawingShape, action: DrawingDragAction) => void;
}

function drawingHandleStyle(
  x: number,
  y: number,
  cursor: CSSProperties["cursor"],
  size = 18,
  color?: string,
): CSSProperties {
  return {
    backgroundColor: color,
    cursor,
    height: size,
    left: x - size / 2,
    pointerEvents: "auto",
    top: y - size / 2,
    width: size,
  };
}

function renderDrawingHtmlHandles(
  shape: DrawingShape,
  onStartDrag: DrawingHtmlLayerProps["onStartDrag"],
) {
  if (shape.kind === "horizontal_line") {
    return (
      <button
        aria-label="Mover línea horizontal"
        className="drawing-html-handle drawing-html-handle--line"
        style={drawingHandleStyle(shape.x, shape.y, "ns-resize", 22)}
        type="button"
        onPointerDown={(event) => onStartDrag(event, shape, "move")}
      />
    );
  }

  if (shape.kind === "vertical_line") {
    return (
      <button
        aria-label="Mover línea vertical"
        className="drawing-html-handle drawing-html-handle--line"
        style={drawingHandleStyle(shape.x, shape.y, "ew-resize", 22)}
        type="button"
        onPointerDown={(event) => onStartDrag(event, shape, "move")}
      />
    );
  }

  if (shape.kind === "trend_line") {
    return (
      <>
        <button
          aria-label="Mover línea"
          className="drawing-html-handle drawing-html-handle--line"
          style={drawingHandleStyle((shape.x1 + shape.x2) / 2, (shape.y1 + shape.y2) / 2, "move", 22)}
          type="button"
          onPointerDown={(event) => onStartDrag(event, shape, "move")}
        />
        <button
          aria-label="Editar inicio de línea"
          className="drawing-html-handle"
          style={drawingHandleStyle(shape.x1, shape.y1, "grab")}
          type="button"
          onPointerDown={(event) => onStartDrag(event, shape, "point1")}
        />
        <button
          aria-label="Editar final de línea"
          className="drawing-html-handle"
          style={drawingHandleStyle(shape.x2, shape.y2, "grab")}
          type="button"
          onPointerDown={(event) => onStartDrag(event, shape, "point2")}
        />
      </>
    );
  }

  if (shape.kind === "rectangle" || shape.kind === "manual_zone") {
    const left = shape.x;
    const top = shape.y;
    const right = shape.x + shape.width;
    const bottom = shape.y + shape.height;
    const centerX = left + shape.width / 2;
    const centerY = top + shape.height / 2;

    return (
      <>
        <button
          aria-label="Mover dibujo"
          className="drawing-html-handle drawing-html-handle--move"
          style={drawingHandleStyle(centerX, centerY, "move", 24)}
          type="button"
          onPointerDown={(event) => onStartDrag(event, shape, "move")}
        />
        <button aria-label="Esquina superior izquierda" className="drawing-html-handle" style={drawingHandleStyle(left, top, "nwse-resize")} type="button" onPointerDown={(event) => onStartDrag(event, shape, "top_left")} />
        <button aria-label="Esquina superior derecha" className="drawing-html-handle" style={drawingHandleStyle(right, top, "nesw-resize")} type="button" onPointerDown={(event) => onStartDrag(event, shape, "top_right")} />
        <button aria-label="Esquina inferior izquierda" className="drawing-html-handle" style={drawingHandleStyle(left, bottom, "nesw-resize")} type="button" onPointerDown={(event) => onStartDrag(event, shape, "bottom_left")} />
        <button aria-label="Esquina inferior derecha" className="drawing-html-handle" style={drawingHandleStyle(right, bottom, "nwse-resize")} type="button" onPointerDown={(event) => onStartDrag(event, shape, "bottom_right")} />
      </>
    );
  }

  if (shape.kind === "text") {
    return (
      <button
        aria-label="Mover texto"
        className="drawing-html-handle drawing-html-handle--move"
        style={drawingHandleStyle(shape.x, shape.y, "move", 24)}
        type="button"
        onPointerDown={(event) => onStartDrag(event, shape, "move")}
      />
    );
  }

  return null;
}

export function DrawingHtmlLayer({ drawingShapes, selectedDrawingId, onStartDrag }: DrawingHtmlLayerProps) {
  return (
    <div
      className="drawing-html-hit-layer"
      aria-hidden={drawingShapes.length === 0 ? "true" : undefined}
      style={{ pointerEvents: "none" }}
    >
      {drawingShapes.map((shape) => {
        const selected = selectedDrawingId === shape.id;

        return (
          <div key={shape.id} style={{ pointerEvents: "none" }}>
            {selected ? renderDrawingHtmlHandles(shape, onStartDrag) : null}
          </div>
        );
      })}
    </div>
  );
}
