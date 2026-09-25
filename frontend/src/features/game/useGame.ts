// Game screen state: puzzle/release fixed at load, server progress and history, local thumbnails and the
// one unconfirmed submission. Scores and success always come from the server; nothing is recomputed here.
import { useEffect, useRef, useState } from 'react';
import { createApi } from '../../shared/api/client.ts';
import type { Api, HistoryItem, Progress, Puzzle, Result, SubmissionResponse, Top3Item } from '../../shared/api/client.ts';
import { createGameStorage } from '../../shared/storage/gameStorage.ts';
import type { GameStorage, PendingSubmission } from '../../shared/storage/gameStorage.ts';
import { createDrawingSnapshot } from '../drawing/drawingSnapshot';
import type { DrawingSnapshot } from '../drawing/drawingSnapshot';
import type { Strokes } from '../drawing/drawingState.ts';
import { DEFERRED_MESSAGE, buildRequest, errorMessage, mergeHistory, newerProgress, recoverPending, sendSubmission } from './submissionFlow.ts';
import type { FlowDeps, FlowOutcome } from './submissionFlow.ts';

export type Notice = { tone: 'info' | 'error'; text: string };
export type LastResult = { submissionId: string; result: Result; reuse: SubmissionResponse['reuse'] };
type Predict = (snapshot: DrawingSnapshot) => { ok: true; top3: Top3Item[] } | { ok: false; message: string };

const EMPTY_PROGRESS: Progress = { state: 'playing', attemptCount: 0, bestSubmissionId: null, bestDisplayScore: null, bestDisplayText: null };
const api = createApi();

type Boot = { puzzle: Puzzle; consentRevision: number; progress: Progress; items: HistoryItem[]; cursor: number | null };
let boot: Promise<Boot> | null = null; // shared by StrictMode's double effect so only one session is created

function loadOnce(client: Api): Promise<Boot> {
  boot ??= (async () => {
    const session = await client.ensureSession();
    const puzzle = await client.todayPuzzle();
    const page = await client.progress(puzzle.puzzleId);
    return { puzzle, consentRevision: session.collection.consentRevision, progress: page.progress, items: page.items,
      cursor: page.nextBeforeAttemptNumber };
  })();
  boot.catch(() => { boot = null; });
  return boot;
}

export function useGame() {
  const [phase, setPhase] = useState<'loading' | 'ready' | 'failed'>('loading');
  const [loadError, setLoadError] = useState('');
  const [puzzle, setPuzzle] = useState<Puzzle | null>(null);
  const [progress, setProgress] = useState<Progress>(EMPTY_PROGRESS);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [cursor, setCursor] = useState<number | null>(null);
  const [thumbnails, setThumbnails] = useState<Record<string, string>>({});
  const [restoredStrokes, setRestoredStrokes] = useState<Strokes>([]);
  const [pending, setPending] = useState<PendingSubmission | null>(null);
  const [busy, setBusy] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [last, setLast] = useState<LastResult | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [highlight, setHighlight] = useState<string | null>(null);
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
    setHighlight(result.attemptNumber != null ? submissionId : null);
    if (result.status === 'deferred') setNotice({ tone: 'info', text: DEFERRED_MESSAGE });
    else if (reuse === 'drawing_duplicate') setNotice({ tone: 'info', text: `같은 그림을 이미 제출했어요. ${result.attemptNumber}번째 기록을 확인해보세요.` });
    else setNotice(null); // success is announced by the result panel
  }

  async function reloadProgress(puzzleId: string) {
    try {
      const page = await api.progress(puzzleId);
      setProgress(current => newerProgress(current, page.progress));
      setHistory(current => mergeHistory(current, page.items));
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
        setNotice({ tone: 'error', text: errorMessage(outcome.error) });
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
      const items = mergeHistory([], b.items);
      setHistory(items);
      setCursor(b.cursor);
      if (items[0]) setLast({ submissionId: items[0].submissionId, result: items[0].result, reuse: 'request_retry' });
      setThumbnails(saved.thumbnails);
      setRestoredStrokes(saved.strokes);
      setPhase('ready');
      if (saved.pending) {
        setPending(saved.pending);
        setNotice({ tone: 'info', text: '확인하지 못한 이전 제출을 확인하고 있어요.' });
        void run(saved.pending, b.puzzle.puzzleId, () => recoverPending(deps(), b.puzzle.puzzleId, saved.pending!));
      }
    }).catch(error => {
      if (cancelled) return;
      setLoadError(error?.code === 'PUZZLE_NOT_FOUND' ? '오늘의 문제가 아직 준비되지 않았어요.'
        : error?.message ?? '문제를 불러오지 못했어요.');
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
    } catch (error) {
      inFlight.current = false;
      setBusy(false);
      setNotice({ tone: 'error', text: error instanceof Error ? error.message : '제출 사본을 만들지 못했어요.' });
      return;
    }
    const prediction = predict(snapshot);
    if (!prediction.ok) {
      inFlight.current = false;
      setBusy(false);
      setNotice({ tone: 'error', text: prediction.message });
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

  async function loadMore() {
    if (!puzzle || cursor == null || loadingMore) return;
    setLoadingMore(true);
    try {
      const page = await api.progress(puzzle.puzzleId, cursor);
      setHistory(current => mergeHistory(current, page.items));
      setProgress(current => newerProgress(current, page.progress));
      setCursor(page.nextBeforeAttemptNumber);
    } catch {
      setNotice({ tone: 'error', text: '이전 기록을 불러오지 못했어요. 잠시 후 다시 시도해주세요.' });
    } finally {
      setLoadingMore(false);
    }
  }

  return {
    phase, loadError, puzzle, progress, history, thumbnails, restoredStrokes, pending, busy, last, notice, highlight,
    hasMore: cursor != null, loadingMore,
    submit, retry, loadMore,
    clearLast: () => { setLast(null); setNotice(null); },
    // Edits make result notices stale; errors about an unconfirmed submission stay until it is resolved.
    dismissNotice: () => { if (!pending) setNotice(null); },
    saveStrokes: (strokes: Strokes) => storage.current?.saveStrokes(strokes),
  };
}

export type Game = ReturnType<typeof useGame>;
