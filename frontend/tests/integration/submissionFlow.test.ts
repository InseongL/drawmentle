import assert from 'node:assert/strict';
import test from 'node:test';
import { ApiError } from '../../src/shared/api/client.ts';
import type { HistoryItem, ProgressPage, Puzzle, SessionInfo, SubmissionRequest, SubmissionResponse } from '../../src/shared/api/client.ts';
import { arrangeHistory, buildRequest, loadFullProgress, mergeHistory, newerProgress, recoverPending, sendSubmission } from '../../src/features/game/submissionFlow.ts';
import type { FlowDeps } from '../../src/features/game/submissionFlow.ts';
import type { PendingSubmission } from '../../src/shared/storage/gameStorage.ts';

const puzzle: Puzzle = {
  puzzleId: 'pz-1', serviceDate: '2026-09-25', puzzleNumber: 1,
  release: {
    releaseId: 'r1', status: 'dev-only', modelVersion: 'm1', preprocessingVersion: 'pp1', catalogVersion: 'c1',
    outputCalibrationVersion: 'none-v1', drawingVersions: ['strokes-v1'], brushVersions: ['pen-v1'],
    inference: { mode: 'dev_manual_top3' }, candidates: [],
  },
  collectionPolicy: { version: 'collection-disabled-v0', enabled: false },
};

const top3 = [{ categoryId: 'apple', p: 0.55 }, { categoryId: 'pear', p: 0.25 }, { categoryId: 'banana', p: 0.1 }];
const body = buildRequest(puzzle, { drawingVersion: 'strokes-v1', brushVersion: 'pen-v1' }, 'a'.repeat(64), top3, 'req-1', 0);
const pending: PendingSubmission = { body, thumbnail: 'thumb', createdAt: '2026-09-25T00:00:00Z' };
const session: SessionInfo = { expiresAt: '', collection: { state: 'not_consented', consentRevision: 0 } };

function response(submissionId: string, attemptNumber: number | null, reuse: SubmissionResponse['reuse'] = 'new'): SubmissionResponse {
  const counted = attemptNumber != null;
  return {
    requestSubmissionId: body.submissionId, submissionId, puzzleId: 'pz-1', releaseId: 'r1', reuse,
    result: {
      status: counted ? 'recognized' : 'deferred', reason: counted ? null : 'low_confidence', attemptNumber,
      displayScore: counted ? 38.72 : null, displayText: counted ? '38.72' : null, solved: false,
      judgedAt: '2026-09-25T00:00:00Z',
    },
    progress: { state: 'playing', attemptCount: attemptNumber ?? 0, bestSubmissionId: null, bestDisplayScore: null, bestDisplayText: null },
    collection: { state: 'not_consented', consentRevision: 0 },
  };
}

type Handlers = {
  submit?: (b: SubmissionRequest) => Promise<SubmissionResponse>;
  byRequest?: () => Promise<SubmissionResponse>;
  ensureSession?: () => Promise<SessionInfo>;
};

function harness(handlers: Handlers) {
  const sent: SubmissionRequest[] = [];
  const stored: (PendingSubmission | null)[] = [];
  const thumbnails: Record<string, string> = {};
  const deps: FlowDeps = {
    api: {
      submit: async (_puzzleId, b) => {
        sent.push(b);
        return (handlers.submit ?? (async () => response('canon-1', 1)))(b);
      },
      byRequest: async () => (handlers.byRequest ?? (async () => {
        throw new ApiError(404, 'SUBMISSION_NOT_FOUND', '', true);
      }))(),
      ensureSession: async () => (handlers.ensureSession ?? (async () => session))(),
    },
    savePending: p => { stored.push(p); },
    saveThumbnail: (id, t) => { thumbnails[id] = t; },
  };
  return { deps, sent, stored, thumbnails };
}

test('the request carries the release versions and the original p unchanged', () => {
  assert.equal(body.releaseId, 'r1');
  assert.equal(body.modelVersion, 'm1');
  assert.deepEqual(body.top3, top3);
  assert.equal(body.collectionConsentRevision, 0);
});

test('pending is stored before sending and replaced by the canonical thumbnail on success', async () => {
  const h = harness({});
  const outcome = await sendSubmission(h.deps, 'pz-1', pending);
  assert.equal(outcome.kind, 'result');
  assert.deepEqual(h.stored, [pending, null]);
  assert.equal(h.thumbnails['canon-1'], 'thumb');
});

test('an unknown outcome keeps the same ID and body for the retry', async () => {
  let calls = 0;
  const h = harness({
    submit: async () => {
      calls += 1;
      if (calls === 1) throw new ApiError(0, 'NETWORK_ERROR', 'offline', true, true);
      return response('canon-1', 1, 'request_retry');
    },
  });
  const first = await sendSubmission(h.deps, 'pz-1', pending);
  assert.ok(first.kind === 'error' && first.keepPending);
  assert.equal(h.stored.at(-1), pending);
  const second = await sendSubmission(h.deps, 'pz-1', pending);
  assert.equal(second.kind, 'result');
  assert.deepEqual(h.sent.map(b => b.submissionId), ['req-1', 'req-1']);
  assert.deepEqual(h.sent[0], h.sent[1]);
});

test('a rejected body is dropped instead of retried', async () => {
  const h = harness({ submit: async () => { throw new ApiError(422, 'INVALID_TOP3', 'bad', false); } });
  const outcome = await sendSubmission(h.deps, 'pz-1', pending);
  assert.ok(outcome.kind === 'error' && !outcome.keepPending);
  assert.equal(h.stored.at(-1), null);
});

test('recovery looks the request up first and resends the same body only when the server has none', async () => {
  const found = harness({ byRequest: async () => response('canon-1', 1, 'request_retry') });
  assert.equal((await recoverPending(found.deps, 'pz-1', pending)).kind, 'result');
  assert.equal(found.sent.length, 0);
  const missing = harness({});
  assert.equal((await recoverPending(missing.deps, 'pz-1', pending)).kind, 'result');
  assert.deepEqual(missing.sent, [body]);
});

test('an expired session gets a new one and the same body is sent once more', async () => {
  let calls = 0;
  let sessions = 0;
  const h = harness({
    submit: async () => {
      calls += 1;
      if (calls === 1) throw new ApiError(401, 'SESSION_EXPIRED', '', false);
      return response('canon-2', 1);
    },
    ensureSession: async () => { sessions += 1; return session; },
  });
  assert.equal((await sendSubmission(h.deps, 'pz-1', pending)).kind, 'result');
  assert.equal(sessions, 1);
  assert.deepEqual(h.sent[0], h.sent[1]);
});

test('history keeps one row per canonical ID, skips deferred results and ignores stale progress', () => {
  const a = { submissionId: 'a', result: response('a', 1).result };
  const b = { submissionId: 'b', result: response('b', 2).result };
  const deferred = { submissionId: 'd', result: response('d', null).result };
  assert.deepEqual(mergeHistory([a], [b, a, deferred]).map(i => i.submissionId), ['b', 'a']);
  const two = response('b', 2).progress;
  const one = response('a', 1).progress;
  assert.equal(newerProgress(two, one), two);
  const solved = { ...one, state: 'solved' as const };
  assert.equal(newerProgress(solved, two), solved);
  assert.equal(newerProgress(one, two), two);
});

function scored(id: string, attemptNumber: number, displayScore: number): HistoryItem {
  const result = response(id, attemptNumber).result;
  return { submissionId: id, result: { ...result, displayScore, displayText: displayScore.toFixed(2) } };
}

test('history pins the latest submission and ranks every attempt by similarity, ties newest first', () => {
  const items = mergeHistory([], [scored('a', 1, 30), scored('b', 2, 55), scored('c', 3, 30), scored('d', 4, 12)]);
  const { latest, ranked } = arrangeHistory(items, 'd');
  assert.equal(latest?.submissionId, 'd');
  assert.deepEqual(ranked.map(i => i.submissionId), ['b', 'c', 'a', 'd']);
  // a re-submitted old drawing becomes the pinned row; unknown or missing IDs fall back to the newest attempt
  assert.equal(arrangeHistory(items, 'a').latest?.submissionId, 'a');
  assert.equal(arrangeHistory(items, null).latest?.submissionId, 'd');
  // a single attempt is not shown twice
  assert.equal(arrangeHistory([scored('a', 1, 30)], 'a').latest, null);
});

test('the full history is loaded page by page until the cursor ends', async () => {
  const all = Array.from({ length: 120 }, (_, i) => scored(`s${i + 1}`, i + 1, i));
  const calls: (number | null | undefined)[] = [];
  const api = {
    progress: async (_: string, before?: number | null, limit = 10): Promise<ProgressPage> => {
      calls.push(before);
      const older = all.filter(i => before == null || i.result.attemptNumber! < before).reverse().slice(0, limit);
      const next = older.length === limit && older.at(-1)!.result.attemptNumber! > 1 ? older.at(-1)!.result.attemptNumber! : null;
      return { puzzleId: 'pz-1', progress: response('x', 120).progress, items: older, nextBeforeAttemptNumber: next };
    },
  };
  const { items } = await loadFullProgress(api, 'pz-1');
  assert.equal(items.length, 120);
  assert.deepEqual(calls, [null, 71, 21]);
  assert.equal(items[0].submissionId, 's120');
});
