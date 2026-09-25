// One submission: fixed snapshot -> request (stored as pending before sending) -> result or retryable error.
// An unconfirmed submission keeps its ID and body until the server confirms it; no new ID is issued meanwhile.
import { ApiError } from '../../shared/api/client.ts';
import type { Api, HistoryItem, Progress, Puzzle, SubmissionRequest, SubmissionResponse, Top3Item } from '../../shared/api/client.ts';
import type { PendingSubmission } from '../../shared/storage/gameStorage.ts';

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

// Responses can arrive out of order: never step back to fewer attempts or from solved to playing.
export function newerProgress(current: Progress, incoming: Progress): Progress {
  if (current.state === 'solved' && incoming.state !== 'solved') return current;
  if (incoming.state === current.state && incoming.attemptCount < current.attemptCount) return current;
  return incoming;
}

export const DEFERRED_MESSAGE = '아직 어떤 그림인지 알아보기 어려워요. 특징을 조금 더 그려주세요.';

export function errorMessage(error: ApiError): string {
  switch (error.code) {
    case 'GAME_ALREADY_SOLVED': return '이미 정답을 맞힌 문제예요.';
    case 'VERSION_MISMATCH': return '문제 정보가 바뀌었어요. 그림은 그대로 두고 새로고침해주세요.';
    case 'IDEMPOTENCY_CONFLICT': return '제출 정보가 맞지 않아 이번 제출을 멈췄어요. 다시 제출해주세요.';
    case 'PUZZLE_CLOSED': return '이 문제는 더 이상 제출할 수 없어요.';
    default: return error.message;
  }
}
