// Opt-in for training contribution: unchecked by default, separate from the submit button, shown only while the
// server's collection policy is on. Play works the same either way.
import { useI18n } from '../../shared/i18n/I18nProvider';

type Props = { enabled: boolean; busy: boolean; onChange: (enabled: boolean) => void };

export default function CollectionConsent({ enabled, busy, onChange }: Props) {
  const { m } = useI18n();
  return (
    <div className="collection-consent">
      <label>
        <input type="checkbox" checked={enabled} disabled={busy} onChange={e => onChange(e.target.checked)} />
        {' '}{m.collection.label}
      </label>
      <p className="collection-note">{m.collection.note} <a href="#faq">{m.collection.more}</a></p>
    </div>
  );
}
