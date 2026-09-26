// One submission: fixed snapshot -> request (stored as pending before sending) -> result or retryable error.
// An unconfirmed submission keeps its ID and body until the server confirms it; no new ID is issued meanwhile.
import { ApiError } from '../../shared/api/client.ts';
import type { Api, HistoryItem, Progress, Puzzle, SubmissionRequest, SubmissionResponse, Top3Item } from '../../shared/api/client.ts';
import type { PendingSubmission } from '../../shared/storage/gameStorage.ts';
import { MESSAGES } from '../../shared/i18n/messages.ts';
import type { ErrorKey } from '../../shared/i18n/messages.ts';

export type FlowDeps = {
  api: Pick<Api, 'submit' | 'byRequest' | 'ensureSession'>;
  savePending: (pending: PendingSubmission | null) => void;
  saveThumbnail: (submissionId: string, thumbnail: string) => void;
};

export type FlowOutcome =
  | { kind: 'result'; response: SubmissionResponse }
  | { kind: 'error'; error: ApiError; keepPending: boolean };

export function buildRequest(puzzle: Puzzle, drawing: { drawingVersion: string; brushVersion: string },
  drawingHash: string, top3: Top3Item[], submissionId: string, consentRevision: number): SubmissionRequest {
  const r = puzzle.release;
  return {
    submissionId,
    releaseId: r.releaseId,
    modelVersion: r.modelVersion,
    preprocessingVersion: r.preprocessingVersion,
    catalogVersion: r.catalogVersion,
    outputCalibrationVersion: r.outputCalibrationVersion,
    drawingVersion: drawing.drawingVersion,
    brushVersion: drawing.brushVersion,
    drawingHash,
    top3,
    collectionConsentRevision: consentRevision,
  };
}

function settle(deps: FlowDeps, pending: PendingSubmission, response: SubmissionResponse): FlowOutcome {
  deps.saveThumbnail(response.submissionId, pending.thumbnail);
  deps.savePending(null);
  return { kind: 'result', response };
}

function failure(deps: FlowDeps, error: unknown): FlowOutcome {
  if (!(error instanceof ApiError)) throw error;
  // Unknown outcome (network) or temporary server state: keep the same ID and body for a retry.
  const keepPending = error.network || error.retryable;
  if (!keepPending) deps.savePending(null);
  return { kind: 'error', error, keepPending };
}

export async function sendSubmission(deps: FlowDeps, puzzleId: string, pending: PendingSubmission): Promise<FlowOutcome> {
  deps.savePending(pending);
  try {
    return settle(deps, pending, await deps.api.submit(puzzleId, pending.body));
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      // Nothing was stored for an unauthenticated request; a fresh session can take the same body.
      try {
        await deps.api.ensureSession();
        return settle(deps, pending, await deps.api.submit(puzzleId, pending.body));
      } catch (retryError) {
        return failure(deps, retryError);
      }
    }
    return failure(deps, error);
  }
}

// After a reload or a lost response: look the request up first, resend the same body only if the server has none.
export async function recoverPending(deps: FlowDeps, puzzleId: string, pending: PendingSubmission): Promise<FlowOutcome> {
  try {
    return settle(deps, pending, await deps.api.byRequest(puzzleId, pending.body.submissionId));
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return sendSubmission(deps, puzzleId, pending);
    return failure(deps, error);
  }
}

// Counted attempts only, newest first, one row per canonical submission ID.
export function mergeHistory(history: readonly HistoryItem[], items: readonly HistoryItem[]): HistoryItem[] {
  const byId = new Map(history.map(item => [item.submissionId, item]));
  for (const item of items) if (item.result.attemptNumber != null) byId.set(item.submissionId, item);
  return [...byId.values()].sort((a, b) => b.result.attemptNumber! - a.result.attemptNumber!);
}

// Similarity ordering needs every attempt, so the whole history is loaded up front (50 per request).
export async function loadFullProgress(api: Pick<Api, 'progress'>, puzzleId: string): Promise<{ progress: Progress; items: HistoryItem[] }> {
  const first = await api.progress(puzzleId, null, 50);
  let { progress } = first;
  let items = first.items;
  let cursor = first.nextBeforeAttemptNumber;
  while (cursor != null) {
    const page = await api.progress(puzzleId, cursor, 50);
    progress = newerProgress(progress, page.progress);
    items = items.concat(page.items);
    cursor = page.nextBeforeAttemptNumber;
  }
  return { progress, items: mergeHistory([], items) };
}

// Display order (like 꼬맨틀): the latest submission pinned on top, then every attempt by similarity.
// Ties keep the more recent attempt first. `latest` is null when there is nothing to pin separately.
export function arrangeHistory(items: readonly HistoryItem[], latestId: string | null): { latest: HistoryItem | null; ranked: HistoryItem[] } {
  const ranked = [...items].sort((a, b) =>
    (b.result.displayScore ?? -Infinity) - (a.result.displayScore ?? -Infinity) || b.result.attemptNumber! - a.result.attemptNumber!);
  const latest = items.find(item => item.submissionId === latestId) ?? items[0] ?? null;
  return { latest: ranked.length > 1 ? latest : null, ranked };
}

// Responses can arrive out of order: never step back to fewer attempts or from solved to playing.
export function newerProgress(current: Progress, incoming: Progress): Progress {
  if (current.state === 'solved' && incoming.state !== 'solved') return current;
  if (incoming.state === current.state && incoming.attemptCount < current.attemptCount) return current;
  return incoming;
}

// Screen text comes from the i18n dictionary by error code, never from the server's (Korean) message.
export function errorKey(error: ApiError): ErrorKey {
  if (Object.hasOwn(MESSAGES.ko.errors, error.code)) return error.code as ErrorKey;
  return error.status === 0 || error.status >= 500 ? 'SERVER_UNREACHABLE' : 'UNKNOWN';
}
