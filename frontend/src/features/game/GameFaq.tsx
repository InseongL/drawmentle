import { useI18n } from '../../shared/i18n/I18nProvider';

export default function GameFaq() {
  const { m } = useI18n();
  return (
    <section id="faq" className="faq" aria-labelledby="faq-title">
      <h2 id="faq-title">{m.faqTitle}</h2>
      {m.faq.map(([q, a]) => (
        <div className="faq-item" key={q}>
          <h3>Q. {q}</h3>
          <p>{a}</p>
        </div>
      ))}
    </section>
  );
}
