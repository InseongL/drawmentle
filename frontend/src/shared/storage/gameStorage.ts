// Per-puzzle browser storage: current strokes, fixed thumbnails by canonical submission ID, and the one
// submission whose outcome is not yet confirmed. Server results stay authoritative; this only restores UI.
import type { SubmissionRequest } from '../api/client.ts';
import type { Strokes } from '../../features/drawing/drawingState.ts';

export type PendingSubmission = { body: SubmissionRequest; thumbnail: string; createdAt: string };

export type StoredGame = {
  strokes: Strokes;
  thumbnails: Record<string, string>;
  pending: PendingSubmission | null;
};

type KeyValue = Pick<Storage, 'getItem' | 'setItem'>;

const empty = (): StoredGame => ({ strokes: [], thumbnails: {}, pending: null });
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
  };
}

export type GameStorage = ReturnType<typeof createGameStorage>;
