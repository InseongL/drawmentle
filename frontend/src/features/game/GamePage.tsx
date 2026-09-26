import { useEffect, useRef, useState } from 'react';
import { useI18n } from '../../shared/i18n/I18nProvider';
import { categoryName } from '../../shared/i18n/messages.ts';
import type { Messages } from '../../shared/i18n/messages.ts';
import DrawingCanvas from '../drawing/DrawingCanvas';
import { undoStroke } from '../drawing/drawingState.ts';
import type { Strokes } from '../drawing/drawingState.ts';
import DevPredictionPanel from '../inference/DevPredictionPanel';
import { buildDevTop3, initialDevPrediction, isDevPredictionReady } from '../inference/devPrediction.ts';
import GameFaq from './GameFaq';
import ResultPanel from './ResultPanel';
import SubmissionHistory from './SubmissionHistory';
import { useGame } from './useGame';
import './game.css';

function formatDate(m: Messages, serviceDate: string): string {
  const [y, mo, d] = serviceDate.split('-').map(Number);
  return m.date(y, mo, d);
}

export default function GamePage() {
  const { lang, m, setLang } = useI18n();
  const game = useGame();
  const [strokes, setStrokes] = useState<Strokes>([]);
  const [drawing, setDrawing] = useState(false);
  const [edited, setEdited] = useState(false);
  const [devInput, setDevInput] = useState(initialDevPrediction);
  const restored = useRef(false);

  useEffect(() => {
    if (game.phase === 'ready' && !restored.current) {
      restored.current = true;
      setStrokes(game.restoredStrokes);
    }
  }, [game.phase, game.restoredStrokes]);

  useEffect(() => {
    if (restored.current) game.saveStrokes(strokes);
  }, [strokes]);

  const { puzzle, progress, last } = game;
  const candidates = puzzle?.release.candidates ?? [];
  const devMode = puzzle?.release.inference.mode === 'dev_manual_top3';
  const devCheck = devMode ? isDevPredictionReady(candidates, devInput) : null;
  const solved = progress.state === 'solved';
  const locked = game.busy || game.phase !== 'ready';

  let blocker: string | null = null;
  if (game.phase !== 'ready') blocker = m.blockers.loading;
  else if (solved) blocker = m.blockers.solved;
  else if (!devMode) blocker = m.blockers.noModel;
  else if (!strokes.length) blocker = m.blockers.empty;
  else if (devCheck && !devCheck.ok) blocker = m.blockers.devInput;
  const canSubmit = !blocker && !locked && !drawing && !game.pending;

  function edit(update: (current: Strokes) => Strokes) {
    setStrokes(update);
    setEdited(true);
    game.dismissNotice();
  }

  async function submit() {
    if (!canSubmit) return;
    setEdited(false);
    await game.submit(strokes, snapshot => buildDevTop3(candidates, devInput, snapshot.drawingHash));
  }

  const lastScored = last && last.result.displayText != null ? last.result : null;
  const answer = progress.answer;
  const answerCandidate = answer && candidates.find(c => c.categoryId === answer.categoryId);
  const answerName = answer ? categoryName(answerCandidate ?? { ...answer, displayNameEn: null }, lang) : '';

  return (
    <main className="game">
      <header className="game-header">
        <div className="brand-row">
          <h1>{m.brand}</h1>
          <span className="brand-sub" lang={m.brandSubLang}>{m.brandSub}</span>
          <button type="button" className="lang-switch" lang={m.switchLang} aria-label={m.switchAria}
            onClick={() => setLang(m.switchLang)}>{m.switchLabel}</button>
        </div>
        <p className="puzzle-meta">
          {puzzle ? m.puzzleMeta(puzzle.puzzleNumber, formatDate(m, puzzle.serviceDate)) : m.puzzleFallback}
        </p>
        <p className="lede">{m.lede}</p>
      </header>

      {game.phase === 'failed' ? (
        <section className="load-error" role="alert">
          <p>{game.loadError?.(m)}</p>
          <button type="button" onClick={() => window.location.reload()}>{m.reload}</button>
        </section>
      ) : (
        <section id="canvas" className="editor" aria-label={m.canvasRegion} tabIndex={-1}>
          <div className="canvas-frame">
            <DrawingCanvas strokes={strokes} disabled={locked} label={m.canvasAria} onDrawingChange={setDrawing}
              onStroke={stroke => edit(current => [...current, stroke])} />
            {!strokes.length && !drawing && <span className="canvas-placeholder" aria-hidden="true">{m.canvasPlaceholder}</span>}
          </div>
          <div className="toolbar" aria-label={m.toolbar}>
            <button type="button" disabled={locked || !strokes.length} onClick={() => edit(undoStroke)}>{m.undo}</button>
            <button type="button" disabled={locked || !strokes.length} onClick={() => {
              edit(() => []);
              game.clearLast();
            }}>{m.clear}</button>
            <button type="button" className="submit-button" disabled={!canSubmit} onClick={submit}>
              {game.busy ? m.judging : m.submit}
            </button>
          </div>

          <div className="status" role="status" aria-live="polite">
            {lastScored && (
              <p className="last-score">
                {m.lastScore} <strong>{lastScored.displayText}</strong>
                {lastScored.attemptNumber != null && <span> · {m.lastAttempt(lastScored.attemptNumber)}</span>}
              </p>
            )}
            {game.notice && <p className={`notice notice-${game.notice.tone}`}>{game.notice.text(m)}</p>}
            {edited && last && !game.busy && <p className="notice">{m.edited}</p>}
            {!game.notice && blocker && <p className="notice">{blocker}</p>}
            {!game.notice && !blocker && !lastScored && <p className="notice">{m.ready}</p>}
            {game.pending && !game.busy && (
              <button type="button" className="retry-button" onClick={game.retry}>{m.retry}</button>
            )}
          </div>

          {devMode && !solved && (
            <DevPredictionPanel candidates={candidates} value={devInput} disabled={locked} onChange={setDevInput}
              problem={strokes.length && devCheck && !devCheck.ok ? devCheck.problem : null} />
          )}
        </section>
      )}

      {solved && answer && (
        <ResultPanel answerName={answerName} attemptCount={progress.attemptCount}
          bestDisplayText={progress.bestDisplayText}
          thumbnail={progress.solvedSubmissionId ? game.thumbnails[progress.solvedSubmissionId] : undefined} />
      )}

      <SubmissionHistory items={game.history} latestId={game.latestId} progress={progress} thumbnails={game.thumbnails} />

      <GameFaq />

      <footer className="credits">
        <p>
          {m.credits.categories}: <a href="https://github.com/googlecreativelab/quickdraw-dataset">Quick, Draw! Dataset</a> (Google,{' '}
          <a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>) · {m.credits.association}: {m.credits.vectors}
          {' '}(Grave et al., 2018, <a href="https://creativecommons.org/licenses/by-sa/3.0/">CC BY-SA 3.0</a>)
        </p>
        {puzzle?.release.status === 'dev-only' && <p>{m.credits.dev(puzzle.release.releaseId)}</p>}
      </footer>
    </main>
  );
}
