import assert from 'node:assert/strict';
import test from 'node:test';
import { buildDevTop3, orderTop3, resolveCandidate } from '../../src/features/inference/devPrediction.ts';
import { createGameStorage } from '../../src/shared/storage/gameStorage.ts';

const candidates = [
  { categoryId: 'apple', candidateIndex: 8, displayNameKo: '사과' },
  { categoryId: 'bus', candidateIndex: 40, displayNameKo: '버스' },
  { categoryId: 'cat', candidateIndex: 60, displayNameKo: '고양이' },
  { categoryId: 'dog', candidateIndex: 90, displayNameKo: '개' },
];
const hashA = 'a'.repeat(64);

test('candidates resolve from the datalist label, the ID or the Korean name', () => {
  assert.equal(resolveCandidate(candidates, '사과 (apple)')?.categoryId, 'apple');
  assert.equal(resolveCandidate(candidates, 'bus')?.categoryId, 'bus');
  assert.equal(resolveCandidate(candidates, '고양이')?.categoryId, 'cat');
  assert.equal(resolveCandidate(candidates, 'bird'), null);
});

test('simple mode keeps the chosen top-1 and derives the same fillers for the same drawing', () => {
  const first = buildDevTop3(candidates, { mode: 'simple', categoryId: 'cat' }, hashA);
  const again = buildDevTop3(candidates, { mode: 'simple', categoryId: 'cat' }, hashA);
  assert.ok(first.ok && again.ok);
  assert.deepEqual(first.top3, again.top3);
  assert.deepEqual(first.top3.map(t => t.p), [0.7, 0.2, 0.1]);
  assert.equal(first.top3[0].categoryId, 'cat');
  assert.equal(new Set(first.top3.map(t => t.categoryId)).size, 3);
});

test('advanced mode sorts by p, breaks ties by candidate index and rejects invalid input', () => {
  const rows = (entries: [string, string][]) => ({
    mode: 'advanced' as const,
    rows: entries.map(([categoryId, p]) => ({ categoryId, p })),
  });
  const tie = buildDevTop3(candidates, rows([['dog', '0.3'], ['bus', '0.3'], ['apple', '0.4']]), hashA);
  assert.ok(tie.ok);
  assert.deepEqual(tie.top3.map(t => t.categoryId), ['apple', 'bus', 'dog']);
  assert.equal(buildDevTop3(candidates, rows([['dog', '0.5'], ['dog', '0.3'], ['apple', '0.1']]), hashA).ok, false);
  assert.equal(buildDevTop3(candidates, rows([['dog', '0.6'], ['bus', '0.3'], ['apple', '0.2']]), hashA).ok, false);
  assert.equal(buildDevTop3(candidates, rows([['dog', '0.6'], ['bird', '0.3'], ['apple', '0.1']]), hashA).ok, false);
  const zeros = orderTop3([{ categoryId: 'cat', p: 0 }, { categoryId: 'apple', p: 0 }], candidates);
  assert.deepEqual(zeros.map(t => t.categoryId), ['apple', 'cat']);
});

test('game storage survives reloads and keeps working when the browser refuses to store', () => {
  const backing = new Map<string, string>();
  const memory = {
    getItem: (key: string) => backing.get(key) ?? null,
    setItem: (key: string, value: string) => { backing.set(key, value); },
  };
  const store = createGameStorage('pz-1', memory);
  assert.equal(store.saveStrokes([[[1, 2]]]), true);
  store.saveThumbnail('s1', 'data:image/png;base64,AA');
  const reloaded = createGameStorage('pz-1', memory).load();
  assert.deepEqual(reloaded.strokes, [[[1, 2]]]);
  assert.equal(reloaded.thumbnails.s1, 'data:image/png;base64,AA');
  assert.deepEqual(createGameStorage('pz-2', memory).load().strokes, []);

  const full = { getItem: () => null, setItem: () => { throw new Error('QuotaExceededError'); } };
  const refusing = createGameStorage('pz-1', full);
  assert.equal(refusing.saveStrokes([[[3, 4]]]), false);
  assert.deepEqual(refusing.load().strokes, [[[3, 4]]]); // still usable in memory
});
