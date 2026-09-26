import { useI18n } from '../../shared/i18n/I18nProvider';

type Props = { answerName: string; attemptCount: number; bestDisplayText: string | null; thumbnail: string | undefined };

// Shown only after the server confirmed success; the answer comes from that response.
export default function ResultPanel({ answerName, attemptCount, bestDisplayText, thumbnail }: Props) {
  const { m } = useI18n();
  return (
    <section className="result-panel" aria-labelledby="result-title">
      <h2 id="result-title">{m.result.title}</h2>
      <div className="result-body">
        {thumbnail
          ? <img src={thumbnail} width="112" height="112" alt={m.result.image} />
          : <span className="no-thumbnail">{m.history.noPreview}</span>}
        <dl>
          <div><dt>{m.result.answer}</dt><dd className="answer-word">{answerName}</dd></div>
          <div><dt>{m.result.attempts}</dt><dd>{m.result.attemptCount(attemptCount)}</dd></div>
          <div><dt>{m.result.best}</dt><dd>{bestDisplayText ?? '—'}</dd></div>
        </dl>
      </div>
      <p className="result-note">{m.result.note}</p>
    </section>
  );
}
