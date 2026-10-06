import assert from 'node:assert/strict';
import test from 'node:test';
import type { Collection, CompleteRequest, UploadGrant, UploadResponse } from '../../src/shared/api/client.ts';
import { uploadDrawing, wantsUpload } from '../../src/features/collection/drawingUpload.ts';
import type { UploadApi } from '../../src/features/collection/drawingUpload.ts';
import { createGameStorage } from '../../src/shared/storage/gameStorage.ts';

const grant: UploadGrant = {
  sampleId: 's-1', uploadId: 'u-1', method: 'PUT', url: '/api/collection-uploads/u-1', contentType: 'application/json',
  maxBytes: 65536, expiresAt: '2026-10-06T00:10:00Z',
};
const drawing = '{"drawingVersion":"strokes-v1","coordinateMax":1024,"brushVersion":"pen-v1","strokes":[[[1,2]]]}';

function fakeApi(upload: UploadResponse, done: Collection = { state: 'verified', consentRevision: 1 }) {
  const calls: string[] = [];
  const api: UploadApi = {
    requestUpload: async (id, revision) => { calls.push(`grant ${id} ${revision}`); return upload; },
    putUpload: async (g, body) => { calls.push(`put ${g.url} ${body === drawing}`); return null; },
    completeUpload: async (id, body: CompleteRequest) => {
      calls.push(`complete ${id} ${body.sampleId} ${body.uploadId} ${body.consentRevision}`);
      return { collection: done };
    },
  };
  return { api, calls };
}

test('a granted upload sends the exact fixed drawing, then completes with the same IDs', async () => {
  const { api, calls } = fakeApi({ collection: { state: 'pending_upload', consentRevision: 1 }, grant });
  const result = await uploadDrawing(api, 'sub-1', drawing, 1);
  assert.equal(result.state, 'verified');
  assert.deepEqual(calls, ['grant sub-1 1', 'put /api/collection-uploads/u-1 true', 'complete sub-1 s-1 u-1 1']);
});

test('no grant (not consented, not selected, deleted) sends nothing', async () => {
  const { api, calls } = fakeApi({ collection: { state: 'not_selected', consentRevision: 1 }, grant: null });
  assert.equal((await uploadDrawing(api, 'sub-1', drawing, 1)).state, 'not_selected');
  assert.deepEqual(calls, ['grant sub-1 1']);
});

test('a file over the granted size is never sent', async () => {
  const { api, calls } = fakeApi({ collection: { state: 'pending_upload', consentRevision: 1 }, grant: { ...grant, maxBytes: 10 } });
  await uploadDrawing(api, 'sub-1', drawing, 1);
  assert.deepEqual(calls, ['grant sub-1 1']);
});

test('only open states queue an upload', () => {
  for (const state of ['eligible', 'pending_upload', 'uploaded', 'upload_failed'] as const) assert.ok(wantsUpload(state));
  for (const state of ['not_consented', 'not_selected', 'verified', 'delete_pending', 'deleted'] as const) assert.ok(!wantsUpload(state));
});

test('queued uploads survive a reload and are cleared on withdrawal', () => {
  const memory = new Map<string, string>();
  const kv = { getItem: (k: string) => memory.get(k) ?? null, setItem: (k: string, v: string) => { memory.set(k, v); } };
  const store = createGameStorage('pz-1', kv);
  store.queueUpload('sub-1', drawing);
  store.queueUpload('sub-2', drawing);
  store.dropUpload('sub-1');
  assert.deepEqual(createGameStorage('pz-1', kv).load().uploads, { 'sub-2': drawing });
  store.clearUploads();
  assert.deepEqual(createGameStorage('pz-1', kv).load().uploads, {});
});
