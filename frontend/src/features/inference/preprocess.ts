// Stroke -> model input, `qd-strokes-64-v1`. Mirrors model/datasets/preprocess.py operation by operation so the
// browser and the training data produce identical bytes (checked against contracts/fixtures/drawing-cases.json).
// 1. Scale the drawing so its longest bounding-box side spans `span` px (aspect ratio kept), centred at size / 2.
// 2. Sample a supersample x supersample grid inside every output pixel.
// 3. A sample is ink when its distance to any stroke segment (or single-point stroke) is <= radius.
// 4. Pixel = floor(255 * inkSamples / supersample^2 + 0.5). Row-major [y][x], background 0.

export type RenderSpec = Readonly<{ version: string; size: number; span: number; radius: number; supersample: number }>;
export type StrokePoints = readonly (readonly [number, number])[];

export const QD_STROKES_64_V1: RenderSpec = { version: 'qd-strokes-64-v1', size: 64, span: 48, radius: 2, supersample: 4 };

function normalise(strokes: readonly StrokePoints[], spec: RenderSpec): number[][][] {
  const kept = strokes.filter(s => s.length > 0);
  if (!kept.length) throw new Error('empty drawing');
  let lx = Infinity, ly = Infinity, hx = -Infinity, hy = -Infinity;
  for (const s of kept) {
    for (const [x, y] of s) {
      lx = Math.min(lx, x); ly = Math.min(ly, y); hx = Math.max(hx, x); hy = Math.max(hy, y);
    }
  }
  const scale = spec.span / Math.max(Math.max(hx - lx, hy - ly), 1);
  const cx = (lx + hx) / 2, cy = (ly + hy) / 2;
  return kept.map(s => s.map(([x, y]) => [(x - cx) * scale + spec.size / 2, (y - cy) * scale + spec.size / 2]));
}

export function renderStrokes(strokes: readonly StrokePoints[], spec: RenderSpec = QD_STROKES_64_V1): Uint8Array {
  const ss = spec.supersample, n = spec.size * ss, r = spec.radius, r2 = r * r;
  const coords = new Float64Array(n);
  for (let i = 0; i < n; i++) coords[i] = (i + 0.5) / ss;
  const ink = new Uint8Array(n * n);
  const segments: [number, number, number, number][] = [];
  for (const s of normalise(strokes, spec)) {
    if (s.length === 1) segments.push([s[0][0], s[0][1], s[0][0], s[0][1]]);
    else for (let i = 0; i + 1 < s.length; i++) segments.push([s[i][0], s[i][1], s[i + 1][0], s[i + 1][1]]);
  }
  for (const [x0, y0, x1, y1] of segments) {
    const c0 = Math.max(Math.floor((Math.min(x0, x1) - r) * ss), 0);
    const c1 = Math.min(Math.ceil((Math.max(x0, x1) + r) * ss) + 1, n);
    const r0 = Math.max(Math.floor((Math.min(y0, y1) - r) * ss), 0);
    const r1 = Math.min(Math.ceil((Math.max(y0, y1) + r) * ss) + 1, n);
    if (c0 >= c1 || r0 >= r1) continue;
    const dx = x1 - x0, dy = y1 - y0;
    const length2 = dx * dx + dy * dy;
    for (let row = r0; row < r1; row++) {
      const py = coords[row] - y0;
      for (let col = c0; col < c1; col++) {
        const px = coords[col] - x0;
        let ex = px, ey = py;
        if (length2 > 0) {
          const t = Math.min(Math.max((px * dx + py * dy) / length2, 0), 1);
          ex = px - t * dx;
          ey = py - t * dy;
        }
        if (ex * ex + ey * ey <= r2) ink[row * n + col] = 1;
      }
    }
  }
  const out = new Uint8Array(spec.size * spec.size);
  for (let y = 0; y < spec.size; y++) {
    for (let x = 0; x < spec.size; x++) {
      let count = 0;
      for (let sy = 0; sy < ss; sy++) {
        const base = (y * ss + sy) * n + x * ss;
        for (let sx = 0; sx < ss; sx++) count += ink[base + sx];
      }
      out[y * spec.size + x] = Math.floor((count * 255) / (ss * ss) + 0.5);
    }
  }
  return out;
}

// uint8 pixels -> float32 [1, 1, size, size] in 0..1 (no mean/std), the model's "image" input.
export function toModelInput(pixels: Uint8Array): Float32Array {
  const input = new Float32Array(pixels.length);
  for (let i = 0; i < pixels.length; i++) input[i] = pixels[i] / 255;
  return input;
}

// Quick Draw stores strokes as [xs, ys]; the drawing board stores [[x, y], ...].
export function fromQuickDraw(strokes: readonly (readonly [readonly number[], readonly number[]])[]): StrokePoints[] {
  return strokes.map(([xs, ys]) => xs.map((x, i) => [x, ys[i]] as const));
}
