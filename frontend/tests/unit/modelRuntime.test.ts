import assert from 'node:assert/strict';
import test from 'node:test';
import { candidateProbabilities, predictTop3, top3FromLogits } from '../../src/features/inference/modelRuntime.ts';

// Raw outputs: 0 alarm_clock -> clock, 1 apple, 2 bird (unsupported, kept), 3 clock, 4 mug -> cup, 5 cup
const rawClasses = [
  { classIndex: 0, categoryId: 'alarm_clock', candidateId: 'clock' },
  { classIndex: 1, categoryId: 'apple', candidateId: 'apple' },
  { classIndex: 2, categoryId: 'bird', candidateId: 'bird' },
  { classIndex: 3, categoryId: 'clock', candidateId: 'clock' },
  { classIndex: 4, categoryId: 'mug', candidateId: 'cup' },
  { classIndex: 5, categoryId: 'cup', candidateId: 'cup' },
];
const candidates = [
  { categoryId: 'clock', candidateIndex: 0, displayNameKo: '시계' },
  { categoryId: 'apple', candidateIndex: 1, displayNameKo: '사과' },
  { categoryId: 'bird', candidateIndex: 2, displayNameKo: '새' },
  { categoryId: 'cup', candidateIndex: 4, displayNameKo: '컵' },
];

test('softmax runs over every raw output and merged classes add up', () => {
  const probs = candidateProbabilities([2, 1, 0, 2, 1, 1], rawClasses, 1);
  const total = [...probs.values()].reduce((a, b) => a + b, 0);
  assert.ok(Math.abs(total - 1) < 1e-12);
  const e = [2, 1, 0, 2, 1, 1].map(Math.exp);
  const z = e.reduce((a, b) => a + b, 0);
  assert.ok(Math.abs(probs.get('clock')! - (e[0] + e[3]) / z) < 1e-12);
  assert.ok(Math.abs(probs.get('cup')! - (e[4] + e[5]) / z) < 1e-12);
});

test('temperature flattens or sharpens without changing the order', () => {
  const logits = [0, 3, 0, 0, 1, 0];
  const sharp = candidateProbabilities(logits, rawClasses, 0.5).get('apple')!;
  const flat = candidateProbabilities(logits, rawClasses, 2).get('apple')!;
  assert.ok(sharp > flat);
  assert.throws(() => candidateProbabilities(logits, rawClasses, 0), /temperature/);
  assert.throws(() => candidateProbabilities([1, 2], rawClasses, 1), /expected 6 logits/);
});

test('top-3 keeps unsupported candidates and breaks ties by candidate index', () => {
  const top = top3FromLogits([0, 0, 5, 0, 0, 0], rawClasses, candidates, 1);
  assert.equal(top[0].categoryId, 'bird'); // kept, the server defers it
  // clock (two raw outputs) beats single outputs; apple and cup tie only after merging -> index order
  const tie = top3FromLogits([Math.log(2), Math.log(2), -50, -50, 0, 0], rawClasses, candidates, 1);
  assert.deepEqual(tie.map(t => t.categoryId), ['clock', 'apple', 'cup']);
  assert.ok(Math.abs(tie[1].p - tie[2].p) < 1e-12);
  assert.ok(tie.reduce((s, t) => s + t.p, 0) <= 1 + 1e-9);
});

test('prediction renders the drawing and feeds a 1x1x64x64 image to the session', async () => {
  let seen = 0;
  const session = { run: async (image: Float32Array) => { seen = image.length; return new Float32Array([0, 4, 0, 0, 0, 0]); } };
  const top = await predictTop3(session, [[[0, 0], [100, 100]]], { rawClasses, candidates, temperature: 1 });
  assert.equal(seen, 64 * 64);
  assert.equal(top[0].categoryId, 'apple');
});
