import { useEffect, useRef, useState } from 'react';
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

function formatDate(serviceDate: string): string {
  const [y, m, d] = serviceDate.split('-').map(Number);
  return `${y}년 ${m}월 ${d}일`;
}

export default function GamePage() {
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
  if (game.phase !== 'ready') blocker = '문제를 불러오는 중이에요.';
  else if (solved) blocker = '오늘의 문제를 맞혔어요.';
  else if (!devMode) blocker = '그림 인식 모델을 준비하고 있어요.';
  else if (!strokes.length) blocker = '그림을 그린 다음 제출해보세요.';
  else if (devCheck && !devCheck.ok) blocker = '아래 개발용 인식 결과를 정하면 제출할 수 있어요.';
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

  return (
    <main className="game">
      <header className="game-header">
        <div className="brand-row">
          <h1>드로맨틀</h1>
          <a href="#faq">이용 방법</a>
        </div>
        <p className="puzzle-meta">
          {puzzle ? `오늘의 문제 #${puzzle.puzzleNumber} · ${formatDate(puzzle.serviceDate)}` : '오늘의 문제'}
        </p>
        <p className="lede">오늘의 정답을 그림으로 찾아보세요.</p>
      </header>

      {game.phase === 'failed' ? (
        <section className="load-error" role="alert">
          <p>{game.loadError}</p>
          <button type="button" onClick={() => window.location.reload()}>다시 불러오기</button>
        </section>
      ) : (
        <section id="canvas" className="editor" aria-label="그림판" tabIndex={-1}>
          <div className="canvas-frame">
            <DrawingCanvas strokes={strokes} disabled={locked} onDrawingChange={setDrawing}
              onStroke={stroke => edit(current => [...current, stroke])} />
            {!strokes.length && !drawing && <span className="canvas-placeholder" aria-hidden="true">여기에 그려보세요</span>}
          </div>
          <div className="toolbar" aria-label="그림판 도구">
            <button type="button" disabled={locked || !strokes.length} onClick={() => edit(undoStroke)}>되돌리기</button>
            <button type="button" disabled={locked || !strokes.length} onClick={() => {
              edit(() => []);
              game.clearLast();
            }}>지우기</button>
            <button type="button" className="submit-button" disabled={!canSubmit} onClick={submit}>
              {game.busy ? '판정 중…' : '제출하기'}
            </button>
          </div>

          <div className="status" role="status" aria-live="polite">
            {lastScored && (
              <p className="last-score">
                마지막 제출 유사도 <strong>{lastScored.displayText}</strong>
                {lastScored.attemptNumber != null && <span> · {lastScored.attemptNumber}번째 시도</span>}
              </p>
            )}
            {game.notice && <p className={`notice notice-${game.notice.tone}`}>{game.notice.text}</p>}
            {edited && last && !game.busy && <p className="notice">그림이 수정됐어요. 제출하면 다시 확인할 수 있어요.</p>}
            {!game.notice && blocker && <p className="notice">{blocker}</p>}
            {!game.notice && !blocker && !lastScored && <p className="notice">다 그렸으면 제출해보세요.</p>}
            {game.pending && !game.busy && (
              <button type="button" className="retry-button" onClick={game.retry}>이전 제출 다시 시도</button>
            )}
          </div>

          {devMode && !solved && (
            <DevPredictionPanel candidates={candidates} value={devInput} disabled={locked} onChange={setDevInput}
              problem={strokes.length && devCheck && !devCheck.ok ? devCheck.message : null} />
          )}
        </section>
      )}

      {solved && progress.answer && (
        <ResultPanel answer={progress.answer} attemptCount={progress.attemptCount}
          bestDisplayText={progress.bestDisplayText}
          thumbnail={progress.solvedSubmissionId ? game.thumbnails[progress.solvedSubmissionId] : undefined} />
      )}

      <SubmissionHistory items={game.history} progress={progress} thumbnails={game.thumbnails}
        highlight={game.highlight} hasMore={game.hasMore} loadingMore={game.loadingMore} onLoadMore={game.loadMore} />

      <GameFaq />

      <footer className="credits">
        <p>
          그림 카테고리: <a href="https://github.com/googlecreativelab/quickdraw-dataset">Quick, Draw! Dataset</a> (Google,{' '}
          <a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>) · 연상 점수: fastText 영어 단어 벡터
          (Grave et al., 2018, <a href="https://creativecommons.org/licenses/by-sa/3.0/">CC BY-SA 3.0</a>)
        </p>
        {puzzle?.release.status === 'dev-only' && <p>개발용 릴리스 {puzzle.release.releaseId} · 운영 판정 기준이 아니에요.</p>}
      </footer>
    </main>
  );
}
