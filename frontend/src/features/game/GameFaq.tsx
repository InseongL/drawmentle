import { useI18n } from '../../shared/i18n/I18nProvider';

export default function GameFaq({ collectionEnabled }: { collectionEnabled: boolean }) {
  const { m } = useI18n();
  const items = [...m.faq, collectionEnabled ? m.faqCollection.on : m.faqCollection.off];
  return (
    <section id="faq" className="faq" aria-labelledby="faq-title">
      <h2 id="faq-title">{m.faqTitle}</h2>
      {items.map(([q, a]) => (
        <div className="faq-item" key={q}>
          <h3>Q. {q}</h3>
          <p>{a}</p>
        </div>
      ))}
    </section>
  );
}
