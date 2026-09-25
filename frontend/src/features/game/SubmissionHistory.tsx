import type { HistoryItem, Progress } from '../../shared/api/client.ts';

type Props = {
  items: readonly HistoryItem[];
  progress: Progress;
  thumbnails: Record<string, string>;
  highlight: string | null;
  hasMore: boolean;
  loadingMore: boolean;
  onLoadMore: () => void;
};

// Newest first, server attempt numbers and display strings only. Best/answer are labelled in text, not colour alone.
export default function SubmissionHistory({ items, progress, thumbnails, highlight, hasMore, loadingMore, onLoadMore }: Props) {
  return (
    <section className="history" aria-labelledby="history-title">
      <div className="section-heading">
        <h2 id="history-title">제출 기록</h2>
        <span>시도 {progress.attemptCount}회 · 최고 유사도 {progress.bestDisplayText ?? '—'}</span>
      </div>
      {!items.length ? <p className="empty-history">아직 제출한 그림이 없어요.</p> : (
        <table className="history-table">
          <thead><tr><th scope="col">번호</th><th scope="col">제출한 그림</th><th scope="col">유사도</th></tr></thead>
          <tbody>
            {items.map(({ submissionId, result }) => {
              const thumbnail = thumbnails[submissionId];
              return (
                <tr key={submissionId} className={highlight === submissionId ? 'highlighted' : undefined}>
                  <td className="attempt">{result.attemptNumber}</td>
                  <td>{thumbnail
                    ? <img src={thumbnail} width="64" height="64" alt={`${result.attemptNumber}번째 제출 그림`} />
                    : <span className="no-thumbnail">미리보기 없음</span>}</td>
                  <td className="score-cell">
                    <span className="score">{result.displayText}</span>
                    {progress.bestSubmissionId === submissionId && <span className="tag">최고</span>}
                    {result.status === 'solved' && <span className="tag tag-answer">정답</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {hasMore && (
        <button type="button" className="more-button" disabled={loadingMore} onClick={onLoadMore}>
          {loadingMore ? '불러오는 중…' : '이전 기록 더 보기'}
        </button>
      )}
      <a className="back-link" href="#canvas">그림판으로 돌아가기</a>
    </section>
  );
}
