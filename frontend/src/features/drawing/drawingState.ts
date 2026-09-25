export const COORDINATE_MAX = 1024;
export const BRUSH_WIDTH = 8;
export type Point = readonly [number, number];
export type Stroke = readonly Point[];
export type Strokes = readonly Stroke[];

export type DrawingDocument = Readonly<{
  drawingVersion: 'strokes-v1';
  coordinateMax: 1024;
  brushVersion: 'pen-v1';
  strokes: Strokes;
}>;

export function toDrawingPoint(x: number, y: number, width: number, height: number): Point {
  const clamp = (value: number) => Math.round(Math.max(0, Math.min(COORDINATE_MAX, value)));
  return [clamp(x / width * COORDINATE_MAX), clamp(y / height * COORDINATE_MAX)];
}

export function appendPoint(stroke: Stroke, point: Point): Stroke {
  const last = stroke.at(-1);
  return last && last[0] === point[0] && last[1] === point[1] ? stroke : [...stroke, point];
}

export function undoStroke(strokes: Strokes): Strokes {
  return strokes.slice(0, -1);
}

export function createDrawingDocument(strokes: Strokes): DrawingDocument {
  return Object.freeze({
    drawingVersion: 'strokes-v1',
    coordinateMax: COORDINATE_MAX,
    brushVersion: 'pen-v1',
    strokes: Object.freeze(strokes.map(stroke =>
      Object.freeze(stroke.map(([x, y]) => Object.freeze([x, y] as const))),
    )),
  });
}

export function serializeDrawing(drawing: DrawingDocument): string {
  // Explicit order makes the prototype's hash independent of object insertion order.
  return JSON.stringify({
    drawingVersion: drawing.drawingVersion,
    coordinateMax: drawing.coordinateMax,
    brushVersion: drawing.brushVersion,
    strokes: drawing.strokes,
  });
}
