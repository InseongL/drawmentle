import { useEffect, useLayoutEffect, useRef } from 'react';
import type { PointerEvent as ReactPointerEvent } from 'react';
import { appendPoint, toDrawingPoint } from './drawingState.ts';
import type { Stroke, Strokes } from './drawingState.ts';
import { renderDrawing } from './drawingSnapshot';

type Props = {
  strokes: Strokes;
  disabled: boolean;
  onStroke: (stroke: Stroke) => void;
  onDrawingChange: (drawing: boolean) => void;
};

export default function DrawingCanvas({ strokes, disabled, onStroke, onDrawingChange }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const active = useRef<{ pointerId: number; stroke: Stroke } | null>(null);
  const saved = useRef(strokes);
  const frame = useRef(0);

  function paint() {
    if (canvasRef.current) {
      renderDrawing(canvasRef.current, active.current
        ? [...saved.current, active.current.stroke] : saved.current);
    }
  }

  function schedulePaint() {
    cancelAnimationFrame(frame.current);
    frame.current = requestAnimationFrame(paint);
  }

  useLayoutEffect(() => {
    saved.current = strokes;
    paint();
  }, [strokes]);

  useEffect(() => {
    const canvas = canvasRef.current!;
    function resize() {
      const rect = canvas.getBoundingClientRect();
      canvas.width = Math.max(1, Math.round(rect.width * window.devicePixelRatio));
      canvas.height = Math.max(1, Math.round(rect.height * window.devicePixelRatio));
      paint();
    }
    const observer = new ResizeObserver(resize);
    observer.observe(canvas);
    window.addEventListener('resize', resize);
    resize();
    return () => {
      observer.disconnect();
      window.removeEventListener('resize', resize);
      cancelAnimationFrame(frame.current);
    };
  }, []);

  function point(event: { clientX: number; clientY: number }) {
    const rect = canvasRef.current!.getBoundingClientRect();
    return toDrawingPoint(event.clientX - rect.left, event.clientY - rect.top, rect.width, rect.height);
  }

  function start(event: ReactPointerEvent<HTMLCanvasElement>) {
    if (disabled || active.current || !event.isPrimary || event.button !== 0) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    active.current = { pointerId: event.pointerId, stroke: [point(event)] };
    onDrawingChange(true);
    schedulePaint();
  }

  function move(event: ReactPointerEvent<HTMLCanvasElement>) {
    if (!active.current || active.current.pointerId !== event.pointerId) return;
    const events = event.nativeEvent.getCoalescedEvents?.() ?? [];
    for (const input of events.length ? events : [event.nativeEvent]) {
      active.current.stroke = appendPoint(active.current.stroke, point(input));
    }
    schedulePaint();
  }

  function finish(event: ReactPointerEvent<HTMLCanvasElement>, cancelled = false) {
    if (!active.current || active.current.pointerId !== event.pointerId) return;
    const stroke = appendPoint(active.current.stroke, point(event));
    active.current = null;
    if (!cancelled) onStroke(stroke);
    onDrawingChange(false);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    schedulePaint();
  }

  return (
    <canvas
      ref={canvasRef}
      className="drawing-canvas"
      aria-label="그림판. 마우스, 손가락 또는 펜으로 그려보세요."
      aria-disabled={disabled}
      onPointerDown={start}
      onPointerMove={move}
      onPointerUp={event => finish(event)}
      onPointerCancel={event => finish(event, true)}
      onLostPointerCapture={event => finish(event, true)}
    >그림판을 사용하려면 Canvas를 지원하는 브라우저가 필요해요.</canvas>
  );
}
