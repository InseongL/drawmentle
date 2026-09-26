import { useState } from 'react';
import type { HistoryItem, Progress } from '../../shared/api/client.ts';
import { useI18n } from '../../shared/i18n/I18nProvider';
import { arrangeHistory } from './submissionFlow.ts';

const PAGE = 10;

type Props = {
  items: readonly HistoryItem[];
  latestId: string | null;
  progress: Progress;
  thumbnails: Record<string, string>;
};

// Latest submission pinned on top, then all attempts by similarity (꼬맨틀 style). Numbers are server attempt
// numbers; best/answer are labelled in text, not colour alone.
export default function SubmissionHistory({ items, latestId, progress, thumbnails }: Props) {
  const { m } = useI18n();
  const [visible, setVisible] = useState(PAGE);
  const { latest, ranked } = arrangeHistory(items, latestId);

  function row({ submissionId, result }: HistoryItem, pinned: boolean) {
    const thumbnail = thumbnails[submissionId];
    return (
      <tr key={`${pinned ? 'latest' : 'ranked'}-${submissionId}`} className={submissionId === latestId ? 'highlighted' : undefined}>
        <td className="attempt">{result.attemptNumber}</td>
        <td>{thumbnail
          ? <img src={thumbnail} width="64" height="64" alt={m.history.image(result.attemptNumber!)} />
          : <span className="no-thumbnail">{m.history.noPreview}</span>}</td>
        <td className="score-cell">
          <span className="score">{result.displayText}</span>
          {progress.bestSubmissionId === submissionId && <span className="tag">{m.history.best}</span>}
          {result.status === 'solved' && <span className="tag tag-answer">{m.history.answer}</span>}
        </td>
      </tr>
    );
  }

  return (
    <section className="history" aria-labelledby="history-title">
      <div className="section-heading">
        <h2 id="history-title">{m.history.title}</h2>
        <span>{m.history.summary(progress.attemptCount, progress.bestDisplayText ?? '—')}</span>
      </div>
      {!ranked.length ? <p className="empty-history">{m.history.empty}</p> : (
        <table className="history-table">
          <caption className="visually-hidden">{m.history.caption}</caption>
          <thead><tr><th scope="col">{m.history.number}</th><th scope="col">{m.history.drawing}</th><th scope="col">{m.history.similarity}</th></tr></thead>
          {latest && <tbody className="latest-group">{row(latest, true)}</tbody>}
          <tbody>{ranked.slice(0, visible).map(item => row(item, false))}</tbody>
        </table>
      )}
      {ranked.length > visible && (
        <button type="button" className="more-button" onClick={() => setVisible(v => v + PAGE)}>
          {m.history.more(ranked.length - visible)}
        </button>
      )}
      <a className="back-link" href="#canvas">{m.history.back}</a>
    </section>
  );
}
