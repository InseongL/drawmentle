// Game screen state: puzzle/release fixed at load, server progress and history, local thumbnails and the
// one unconfirmed submission. Scores and success always come from the server; nothing is recomputed here.
import { useEffect, useRef, useState } from 'react';
import { ApiError, createApi } from '../../shared/api/client.ts';
import type { Api, HistoryItem, Progress, Puzzle, Result, SubmissionResponse, Top3Item } from '../../shared/api/client.ts';
import { createGameStorage } from '../../shared/storage/gameStorage.ts';
import type { GameStorage, PendingSubmission } from '../../shared/storage/gameStorage.ts';
import { createDrawingSnapshot } from '../drawing/drawingSnapshot';
import type { DrawingSnapshot } from '../drawing/drawingSnapshot';
import type { Strokes } from '../drawing/drawingState.ts';
import type { DevProblem, Messages } from '../../shared/i18n/messages.ts';
import { buildRequest, errorKey, loadFullProgress, mergeHistory, newerProgress, recoverPending, sendSubmission } from './submissionFlow.ts';
import type { FlowDeps, FlowOutcome } from './submissionFlow.ts';

// Text is looked up at render time so switching language also translates notices already on screen.
export type Text = (m: Messages) => string;
export type Notice = { tone: 'info' | 'error'; text: Text };
export type LastResult = { submissionId: string; result: Result; reuse: SubmissionResponse['reuse'] };
type Predict = (snapshot: DrawingSnapshot) => { ok: true; top3: Top3Item[] } | { ok: false; problem: DevProblem };

const EMPTY_PROGRESS: Progress = { state: 'playing', attemptCount: 0, bestSubmissionId: null, bestDisplayScore: null, bestDisplayText: null };
const api = createApi();

type Boot = { puzzle: Puzzle; consentRevision: number; progress: Progress; items: HistoryItem[] };
let boot: Promise<Boot> | null = null; // shared by StrictMode's double effect so only one session is created

function loadOnce(client: Api): Promise<Boot> {
  boot ??= (async () => {
    const session = await client.ensureSession();
    const puzzle = await client.todayPuzzle();
    const { progress, items } = await loadFullProgress(client, puzzle.puzzleId);
    return { puzzle, consentRevision: session.collection.consentRevision, progress, items };
  })();
  boot.catch(() => { boot = null; });
  return boot;
}

export function useGame() {
  const [phase, setPhase] = useState<'loading' | 'ready' | 'failed'>('loading');
  const [loadError, setLoadError] = useState<Text | null>(null);
  const [puzzle, setPuzzle] = useState<Puzzle | null>(null);
  const [progress, setProgress] = useState<Progress>(EMPTY_PROGRESS);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [thumbnails, setThumbnails] = useState<Record<string, string>>({});
  const [restoredStrokes, setRestoredStrokes] = useState<Strokes>([]);
  const [pending, setPending] = useState<PendingSubmission | null>(null);
  const [busy, setBusy] = useState(false);
  const [last, setLast] = useState<LastResult | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [latestId, setLatestId] = useState<string | null>(null); // pinned row: the latest counted submission
  const consentRevision = useRef(0);
  const storage = useRef<GameStorage | null>(null);
  const inFlight = useRef(false);

  const deps = (): FlowDeps => ({
    api,
    savePending: p => storage.current?.savePending(p),
    saveThumbnail: (id, thumbnail) => storage.current?.saveThumbnail(id, thumbnail),
  });

  function apply(response: SubmissionResponse, thumbnail: string) {
    const { result, submissionId, reuse } = response;
    setProgress(current => newerProgress(current, response.progress));
    consentRevision.current = Math.max(consentRevision.current, response.collection.consentRevision);
    setHistory(current => mergeHistory(current, [{ submissionId, result }]));
    setThumbnails(current => current[submissionId] ? current : { ...current, [submissionId]: thumbnail });
    setLast({ submissionId, result, reuse });
    if (result.attemptNumber != null) setLatestId(submissionId);
    if (result.status === 'deferred') setNotice({ tone: 'info', text: m => m.notices.deferred });
    else if (reuse === 'drawing_duplicate') setNotice({ tone: 'info', text: m => m.notices.duplicate(result.attemptNumber!) });
    else setNotice(null); // success is announced by the result panel
  }

  async function reloadProgress(puzzleId: string) {
    try {
      const full = await loadFullProgress(api, puzzleId);
      setProgress(current => newerProgress(current, full.progress));
      setHistory(current => mergeHistory(current, full.items));
    } catch {
      // keep the current view; the next action reloads again
    }
  }

  async function run(p: PendingSubmission, puzzleId: string, action: () => Promise<FlowOutcome>) {
    inFlight.current = true;
    setBusy(true);
    try {
      const outcome = await action();
      if (outcome.kind === 'result') {
        setPending(null);
        apply(outcome.response, p.thumbnail);
      } else {
        setPending(outcome.keepPending ? p : null);
        const key = errorKey(outcome.error);
        setNotice({ tone: 'error', text: m => m.errors[key] });
        if (outcome.error.code === 'GAME_ALREADY_SOLVED') void reloadProgress(puzzleId);
      }
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    loadOnce(api).then(b => {
      if (cancelled) return;
      const store = createGameStorage(b.puzzle.puzzleId);
      storage.current = store;
      const saved = store.load();
      consentRevision.current = b.consentRevision;
      setPuzzle(b.puzzle);
      setProgress(b.progress);
      setHistory(b.items);
      if (b.items[0]) {
        setLast({ submissionId: b.items[0].submissionId, result: b.items[0].result, reuse: 'request_retry' });
        setLatestId(b.items[0].submissionId);
      }
      setThumbnails(saved.thumbnails);
      setRestoredStrokes(saved.strokes);
      setPhase('ready');
      if (saved.pending) {
        setPending(saved.pending);
        setNotice({ tone: 'info', text: m => m.notices.checkingPending });
        void run(saved.pending, b.puzzle.puzzleId, () => recoverPending(deps(), b.puzzle.puzzleId, saved.pending!));
      }
    }).catch(error => {
      if (cancelled) return;
      if (error instanceof ApiError && error.code === 'PUZZLE_NOT_FOUND') setLoadError(() => (m: Messages) => m.notices.puzzleNotReady);
      else {
        const key = error instanceof ApiError ? errorKey(error) : 'UNKNOWN';
        setLoadError(() => (m: Messages) => m.errors[key]);
      }
      setPhase('failed');
    });
    return () => { cancelled = true; };
  }, []);

  async function submit(strokes: Strokes, predict: Predict) {
    if (inFlight.current || !puzzle || pending || !strokes.length) return;
    inFlight.current = true;
    setBusy(true);
    let snapshot: DrawingSnapshot;
    try {
      snapshot = await createDrawingSnapshot(strokes);
    } catch {
      inFlight.current = false;
      setBusy(false);
      setNotice({ tone: 'error', text: m => m.notices.snapshotFailed });
      return;
    }
    const prediction = predict(snapshot);
    if (!prediction.ok) {
      inFlight.current = false;
      setBusy(false);
      const { problem } = prediction;
      setNotice({ tone: 'error', text: m => m.dev.problems[problem] });
      return;
    }
    const body = buildRequest(puzzle, snapshot.drawing, snapshot.drawingHash, prediction.top3, crypto.randomUUID(),
      consentRevision.current);
    const p: PendingSubmission = { body, thumbnail: snapshot.thumbnail, createdAt: new Date().toISOString() };
    setPending(p);
    await run(p, puzzle.puzzleId, () => sendSubmission(deps(), puzzle.puzzleId, p));
  }

  function retry() {
    if (inFlight.current || !puzzle || !pending) return;
    const p = pending;
    void run(p, puzzle.puzzleId, () => sendSubmission(deps(), puzzle.puzzleId, p));
  }

  return {
    phase, loadError, puzzle, progress, history, latestId, thumbnails, restoredStrokes, pending, busy, last, notice,
    submit, retry,
    clearLast: () => { setLast(null); setNotice(null); },
    // Edits make result notices stale; errors about an unconfirmed submission stay until it is resolved.
    dismissNotice: () => { if (!pending) setNotice(null); },
    saveStrokes: (strokes: Strokes) => storage.current?.saveStrokes(strokes),
  };
}

export type Game = ReturnType<typeof useGame>;
