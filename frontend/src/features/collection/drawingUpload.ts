// Sending a consented, selected drawing for training (docs/api-contract-v1.md §8): grant -> PUT file -> complete.
// The file is the fixed snapshot of that submission (its exact bytes hash to the submitted drawingHash), never the
// current canvas. Failures are silent and never touch the game; the drawing stays queued for one retry later.
import type { Api, Collection, CollectionState } from '../../shared/api/client.ts';

// States where an upload can still help. Everything else is final for this drawing (sent, not selected, withdrawn).
const OPEN: ReadonlySet<CollectionState> = new Set(['eligible', 'pending_upload', 'uploaded', 'upload_failed']);

export function wantsUpload(state: CollectionState): boolean {
  return OPEN.has(state);
}

export type UploadApi = Pick<Api, 'requestUpload' | 'putUpload' | 'completeUpload'>;

export async function uploadDrawing(api: UploadApi, submissionId: string, drawing: string,
  consentRevision: number): Promise<Collection> {
  const { collection, grant } = await api.requestUpload(submissionId, consentRevision);
  if (!grant) return collection; // not consented, not selected, already sent or deleted
  if (new TextEncoder().encode(drawing).byteLength > grant.maxBytes) return collection;
  await api.putUpload(grant, drawing);
  const done = await api.completeUpload(submissionId, { sampleId: grant.sampleId, uploadId: grant.uploadId, consentRevision });
  return done.collection;
}
