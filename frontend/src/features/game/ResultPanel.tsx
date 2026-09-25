import type { Answer } from '../../shared/api/client.ts';

type Props = { answer: Answer; attemptCount: number; bestDisplayText: string | null; thumbnail: string | undefined };

// Shown only after the server confirmed success; the answer comes from that response.
export default function ResultPanel({ answer, attemptCount, bestDisplayText, thumbnail }: Props) {
  return (
    <section className="result-panel" aria-labelledby="result-title">
      <h2 id="result-title">정답이에요!</h2>
      <div className="result-body">
        {thumbnail
          ? <img src={thumbnail} width="112" height="112" alt="정답으로 판정된 그림" />
          : <span className="no-thumbnail">미리보기 없음</span>}
        <dl>
          <div><dt>오늘의 정답</dt><dd className="answer-word">{answer.displayNameKo}</dd></div>
          <div><dt>총 시도</dt><dd>{attemptCount}회</dd></div>
          <div><dt>최고 유사도</dt><dd>{bestDisplayText ?? '—'}</dd></div>
        </dl>
      </div>
      <p className="result-note">내일 한국 시간 자정에 새 문제가 열려요.</p>
    </section>
  );
}
