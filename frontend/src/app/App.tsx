import { useRef, useState } from 'react';
import DrawingCanvas from '../features/drawing/DrawingCanvas';
import { undoStroke } from '../features/drawing/drawingState';
import type { Strokes } from '../features/drawing/drawingState';
import { createDrawingSnapshot } from '../features/drawing/drawingSnapshot';
import type { DrawingSnapshot } from '../features/drawing/drawingSnapshot';

type Submission = DrawingSnapshot & { id: string; number: number; submittedAt: string };

function requestDraft(entry: Submission) {
  return {
    submissionId: entry.id,
    releaseId: null,
    modelVersion: null,
    preprocessingVersion: null,
    catalogVersion: null,
    outputCalibrationVersion: null,
    drawingVersion: entry.drawing.drawingVersion,
    brushVersion: entry.drawing.brushVersion,
    drawingHash: entry.drawingHash,
    top3: null,
    collectionConsentRevision: 0,
  };
}

export default function App() {
  const [strokes, setStrokes] = useState<Strokes>([]);
  const [drawing, setDrawing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [history, setHistory] = useState<Submission[]>([]);
  const [notice, setNotice] = useState('그림을 그린 다음 제출해보세요.');
  const [highlighted, setHighlighted] = useState<string | null>(null);
  const inFlight = useRef(false);
  const canvasRegion = useRef<HTMLDivElement>(null);
  const locked = drawing || submitting;

  async function submit() {
    if (inFlight.current || drawing || !strokes.length) return;
    inFlight.current = true;
    setSubmitting(true);
    try {
      const snapshot = await createDrawingSnapshot(strokes);
      const duplicate = history.find(entry => entry.drawingHash === snapshot.drawingHash);
      if (duplicate) {
        setHighlighted(duplicate.id);
        setNotice(`같은 그림이 제출 #${duplicate.number}에 있어요. 기록을 추가하지 않았어요.`);
        return;
      }
      const entry = { ...snapshot, id: crypto.randomUUID(), number: history.length + 1, submittedAt: new Date().toISOString() };
      setHistory(previous => [entry, ...previous]);
      setHighlighted(entry.id);
      setNotice(`제출 #${entry.number}을 아래에 추가했어요. 이어서 수정하거나 새로 그려보세요.`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '제출 사본을 만들지 못했어요. 다시 시도해주세요.');
    } finally {
      inFlight.current = false;
      setSubmitting(false);
    }
  }

  return (
    <main>
      <header className="page-header">
        <span className="eyebrow">DRAWING PROTOTYPE</span>
        <h1>그림판 데모</h1>
        <p>그려보고, 되돌리고, 제출해보세요.</p>
      </header>

      <section aria-label="그리기" className="editor">
        <div className="canvas-heading"><span>검은 펜 · 흰 종이</span><span>{strokes.length}획</span></div>
        <div ref={canvasRegion} className="canvas-frame" tabIndex={-1}>
          <DrawingCanvas strokes={strokes} disabled={submitting} onDrawingChange={setDrawing}
            onStroke={stroke => {
              setStrokes(previous => [...previous, stroke]);
              setNotice('그림이 수정됐어요. 제출하면 새 사본을 만들어요.');
            }} />
          {!strokes.length && !drawing && <span className="canvas-placeholder" aria-hidden="true">여기에 자유롭게 그려보세요</span>}
        </div>
        <div className="toolbar" aria-label="그림판 도구">
          <button type="button" className="pen-button" aria-pressed="true" disabled={locked}
            onClick={() => { canvasRegion.current?.focus(); setNotice('검은 펜으로 그림판에 그려보세요.'); }}>그리기</button>
          <button type="button" disabled={locked || !strokes.length} onClick={() => {
            setStrokes(undoStroke); setNotice('마지막 획을 되돌렸어요.');
          }}>Undo</button>
          <button type="button" disabled={locked || !strokes.length} onClick={() => {
            setStrokes([]); setNotice('그림판을 비웠어요. 제출 기록은 그대로예요.');
          }}>Reset</button>
          <button type="button" className="submit-button" disabled={locked || !strokes.length} onClick={submit}>
            {submitting ? '저장 중…' : '제출'}
          </button>
        </div>
        <p className="status" role="status">{notice}</p>
      </section>

      <section className="history" aria-labelledby="history-title">
        <div className="section-heading"><h2 id="history-title">제출 기록</h2><span>{history.length}개</span></div>
        <p className="helper">썸네일과 데이터만 이 페이지에 보관해요. AI 판정·서버 전송은 아직 연결하지 않았어요.</p>
        {!history.length && <div className="empty-history">제출한 그림이 여기에 쌓여요.</div>}
        <ol className="history-list">
          {history.map(entry => (
            <li key={entry.id} className={`submission ${highlighted === entry.id ? 'highlighted' : ''}`}>
              <div className="submission-summary">
                <img src={entry.thumbnail} width="104" height="104" alt={`제출 ${entry.number} 그림`} />
                <div className="submission-info">
                  <h3>제출 #{entry.number}</h3>
                  <p>{entry.strokeCount}획 · {entry.pointCount}개 좌표 · {entry.byteLength.toLocaleString()} bytes</p>
                  <span className="pending-label">AI 미연결</span>
                  <time dateTime={entry.submittedAt}>{new Date(entry.submittedAt).toLocaleTimeString('ko-KR')}</time>
                </div>
              </div>
              <details open={highlighted === entry.id}>
                <summary>판정 요청 데이터 초안</summary>
                <p className="data-note">해시와 제출 ID는 실제 값이에요. null 항목은 모델·릴리스 연결 후 채우며, 지금은 전송 가능한 API 요청이 아니에요.</p>
                <pre aria-label={`제출 ${entry.number} 요청 데이터`}>{JSON.stringify(requestDraft(entry), null, 2)}</pre>
              </details>
              <details>
                <summary>획 원본 보기</summary>
                <p className="data-note">0~1024 논리 좌표예요. 추론·썸네일·해시의 기준이 될 원본이며, 일반 판정 요청과는 별도로 관리해요.</p>
                <pre>{JSON.stringify(entry.drawing, null, 2)}</pre>
              </details>
            </li>
          ))}
        </ol>
      </section>
      <footer>현재는 임시 데모예요. 새로고침하면 그림과 제출 기록이 초기화돼요.</footer>
    </main>
  );
}
