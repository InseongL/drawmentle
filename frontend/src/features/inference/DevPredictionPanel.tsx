import { useId } from 'react';
import type { Candidate } from '../../shared/api/client.ts';
import { useI18n } from '../../shared/i18n/I18nProvider';
import type { DevProblem } from '../../shared/i18n/messages.ts';
import { SIMPLE_P, candidateLabel } from './devPrediction.ts';
import type { DevPrediction } from './devPrediction.ts';

type Props = {
  candidates: readonly Candidate[];
  value: DevPrediction;
  disabled: boolean;
  problem: DevProblem | null;
  onChange: (value: DevPrediction) => void;
};

const emptyRows = () => [{ categoryId: '', p: '0.6' }, { categoryId: '', p: '0.25' }, { categoryId: '', p: '0.1' }];

// Shown only for dev releases without a model. It never shows the answer or any score.
export default function DevPredictionPanel({ candidates, value, disabled, problem, onChange }: Props) {
  const { lang, m } = useI18n();
  const listId = useId();
  const total = value.mode === 'advanced' ? value.rows.reduce((sum, row) => sum + (Number(row.p) || 0), 0) : 1;

  return (
    <fieldset className="dev-panel" disabled={disabled}>
      <legend>{m.dev.legend} <span>{m.dev.badge}</span></legend>
      <p className="dev-note">{m.dev.note}</p>
      <div className="dev-modes" role="radiogroup" aria-label={m.dev.modes}>
        <label><input type="radio" name={`${listId}-mode`} checked={value.mode === 'simple'}
          onChange={() => onChange({ mode: 'simple', categoryId: '' })} /> {m.dev.simple}</label>
        <label><input type="radio" name={`${listId}-mode`} checked={value.mode === 'advanced'}
          onChange={() => onChange({ mode: 'advanced', rows: emptyRows() })} /> {m.dev.advanced}</label>
      </div>
      <datalist id={listId}>
        {candidates.map(c => <option key={c.categoryId} value={candidateLabel(c, lang)} />)}
      </datalist>
      {value.mode === 'simple' ? (
        <label className="dev-row">
          <span>{m.dev.top1}</span>
          <input list={listId} value={value.categoryId} placeholder={m.dev.top1Placeholder}
            onChange={event => onChange({ mode: 'simple', categoryId: event.target.value })} />
          <small>{m.dev.simpleHint(SIMPLE_P.join(' / '))}</small>
        </label>
      ) : (
        value.rows.map((row, i) => (
          <div className="dev-row dev-row-advanced" key={i}>
            <input list={listId} aria-label={m.dev.candidate(i + 1)} value={row.categoryId} placeholder={m.dev.candidate(i + 1)}
              onChange={event => onChange({ mode: 'advanced', rows: value.rows.map((r, j) => j === i ? { ...r, categoryId: event.target.value } : r) })} />
            <input type="number" aria-label={m.dev.candidateP(i + 1)} min="0" max="1" step="0.01" value={row.p}
              onChange={event => onChange({ mode: 'advanced', rows: value.rows.map((r, j) => j === i ? { ...r, p: event.target.value } : r) })} />
          </div>
        ))
      )}
      {value.mode === 'advanced' && <p className="dev-note">{m.dev.sum(total.toFixed(2))}</p>}
      {problem && <p className="dev-problem">{m.dev.problems[problem]}</p>}
    </fieldset>
  );
}
