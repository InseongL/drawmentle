import { BRUSH_WIDTH, COORDINATE_MAX, createDrawingDocument, serializeDrawing } from './drawingState.ts';
import type { Strokes } from './drawingState.ts';

export function renderDrawing(canvas: HTMLCanvasElement, strokes: Strokes): void {
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('이 브라우저에서 그림판을 열 수 없어요.');
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.setTransform(canvas.width / COORDINATE_MAX, 0, 0, canvas.height / COORDINATE_MAX, 0, 0);
  ctx.strokeStyle = '#111111';
  ctx.fillStyle = '#111111';
  ctx.lineWidth = BRUSH_WIDTH;
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  for (const stroke of strokes) {
    if (!stroke.length) continue;
    ctx.beginPath();
    if (stroke.length === 1) {
      ctx.arc(stroke[0][0], stroke[0][1], BRUSH_WIDTH / 2, 0, Math.PI * 2);
      ctx.fill();
    } else {
      ctx.moveTo(stroke[0][0], stroke[0][1]);
      for (const [x, y] of stroke.slice(1)) ctx.lineTo(x, y);
      ctx.stroke();
    }
  }
}

export async function createDrawingSnapshot(strokes: Strokes) {
  const drawing = createDrawingDocument(strokes);
  const bytes = new TextEncoder().encode(serializeDrawing(drawing));
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  const drawingHash = Array.from(new Uint8Array(digest), n => n.toString(16).padStart(2, '0')).join('');
  const thumbnail = document.createElement('canvas');
  thumbnail.width = thumbnail.height = 192;
  renderDrawing(thumbnail, drawing.strokes);
  return {
    drawing,
    drawingHash,
    thumbnail: thumbnail.toDataURL('image/png'),
    strokeCount: drawing.strokes.length,
    pointCount: drawing.strokes.reduce((sum, stroke) => sum + stroke.length, 0),
    byteLength: bytes.byteLength,
  };
}

export type DrawingSnapshot = Awaited<ReturnType<typeof createDrawingSnapshot>>;
