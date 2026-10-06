import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { QD_STROKES_64_V1, fromQuickDraw, renderStrokes, toModelInput } from '../../src/features/inference/preprocess.ts';

type Case = { name: string; strokes: [number[], number[]][]; sha256: string; inkPixels: number; sum: number };
const fixture = JSON.parse(readFileSync(new URL('../../../contracts/fixtures/drawing-cases.json', import.meta.url), 'utf8'));

test('the fixture describes the same preprocessing version as the browser', () => {
  assert.deepEqual(fixture.preprocessing, { ...QD_STROKES_64_V1 });
});

test('the browser renderer reproduces the Python training input byte for byte', () => {
  for (const c of fixture.cases as Case[]) {
    const pixels = renderStrokes(fromQuickDraw(c.strokes));
    const digest = createHash('sha256').update(pixels).digest('hex');
    const ink = pixels.reduce((n, v) => n + (v > 0 ? 1 : 0), 0);
    const sum = pixels.reduce((n, v) => n + v, 0);
    assert.deepEqual({ name: c.name, digest, ink, sum }, { name: c.name, digest: c.sha256, ink: c.inkPixels, sum: c.sum });
  }
});

test('model input is 0..1 floats and empty drawings are refused', () => {
  const pixels = renderStrokes([[[5, 5]]]);
  const input = toModelInput(pixels);
  assert.equal(input.length, 64 * 64);
  assert.equal(Math.max(...input), 1);
  assert.equal(Math.min(...input), 0);
  assert.throws(() => renderStrokes([]), /empty drawing/);
  assert.throws(() => renderStrokes([[]]), /empty drawing/);
});
