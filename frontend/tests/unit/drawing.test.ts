import assert from 'node:assert/strict';
import test from 'node:test';
import { appendPoint, createDrawingDocument, serializeDrawing, toDrawingPoint, undoStroke } from '../../src/features/drawing/drawingState.ts';

test('the same relative input has the same coordinates at desktop and mobile sizes', () => {
  assert.deepEqual(toDrawingPoint(100, 200, 400, 400), toDrawingPoint(80, 160, 320, 320));
  assert.deepEqual(toDrawingPoint(-10, 500, 400, 400), [0, 1024]);
});

test('undo and later edits cannot mutate an already submitted snapshot', () => {
  const live: [number, number][][] = [[[10, 20]], [[30, 40], [50, 60]]];
  const submitted = createDrawingDocument(live);
  const original = serializeDrawing(submitted);
  const undone = undoStroke(live);
  assert.equal(undone.length, 1);
  live[0][0][0] = 999;
  live.push([[70, 80]]);
  assert.equal(serializeDrawing(submitted), original);
  assert.deepEqual(submitted.strokes[0], [[10, 20]]);
  assert.ok(Object.isFrozen(submitted.strokes[0][0]));
});

test('single-dot strokes survive and repeated identical points do not alter the hash input', () => {
  const dot = [[512, 512]] as const;
  assert.strictEqual(appendPoint(dot, [512, 512]), dot);
  const drawing = createDrawingDocument([dot]);
  assert.equal(drawing.strokes[0].length, 1);
  assert.equal(serializeDrawing(drawing), serializeDrawing(createDrawingDocument([appendPoint(dot, [512, 512])])));
  assert.deepEqual(undoStroke([]), []);
});
