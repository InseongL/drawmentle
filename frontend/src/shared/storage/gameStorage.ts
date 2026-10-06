// Per-puzzle browser storage: current strokes, fixed thumbnails by canonical submission ID, the one
// submission whose outcome is not yet confirmed, and (only while the player consents to training contribution)
// fixed drawings waiting to be uploaded. Server results stay authoritative; this only restores UI.
import type { SubmissionRequest } from '../api/client.ts';
import type { Strokes } from '../../features/drawing/drawingState.ts';

// `drawing` (serialised strokes-v1) is kept only when the player consented at submit time.
export type PendingSubmission = { body: SubmissionRequest; thumbnail: string; createdAt: string; drawing?: string };

export type StoredGame = {
  strokes: Strokes;
  thumbnails: Record<string, string>;
  pending: PendingSubmission | null;
  uploads: Record<string, string>; // canonical submission ID -> serialised drawing still to upload
};

type KeyValue = Pick<Storage, 'getItem' | 'setItem'>;

const empty = (): StoredGame => ({ strokes: [], thumbnails: {}, pending: null, uploads: {} });
const keyFor = (puzzleId: string) => `drawmentle:game:v1:${puzzleId}`;

function defaultStorage(): KeyValue | null {
  try {
    return window.localStorage;
  } catch {
    return null; // private mode or blocked storage: play still works without restore
  }
}

export function createGameStorage(puzzleId: string, storage: KeyValue | null = defaultStorage()) {
  let cache: StoredGame | null = null;

  function load(): StoredGame {
    if (cache) return cache;
    try {
      const raw = storage?.getItem(keyFor(puzzleId));
      const parsed = raw ? JSON.parse(raw) : null;
      cache = {
        strokes: Array.isArray(parsed?.strokes) ? parsed.strokes : [],
        thumbnails: parsed?.thumbnails && typeof parsed.thumbnails === 'object' ? parsed.thumbnails : {},
        pending: parsed?.pending?.body?.submissionId ? parsed.pending : null,
        uploads: parsed?.uploads && typeof parsed.uploads === 'object' ? parsed.uploads : {},
      };
    } catch {
      cache = empty();
    }
    return cache;
  }

  // Returns false when the browser refused to store (quota, blocked); callers keep working in memory.
  function update(change: Partial<StoredGame>): boolean {
    cache = { ...load(), ...change };
    try {
      storage?.setItem(keyFor(puzzleId), JSON.stringify(cache));
      return storage != null;
    } catch {
      return false;
    }
  }

  return {
    load,
    saveStrokes: (strokes: Strokes) => update({ strokes }),
    savePending: (pending: PendingSubmission | null) => update({ pending }),
    saveThumbnail: (submissionId: string, thumbnail: string) =>
      update({ thumbnails: { ...load().thumbnails, [submissionId]: thumbnail } }),
    queueUpload: (submissionId: string, drawing: string) =>
      update({ uploads: { ...load().uploads, [submissionId]: drawing } }),
    dropUpload: (submissionId: string) => {
      const { [submissionId]: _, ...rest } = load().uploads;
      return update({ uploads: rest });
    },
    clearUploads: () => update({ uploads: {} }),
  };
}

export type GameStorage = ReturnType<typeof createGameStorage>;
