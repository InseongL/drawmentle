import { useId } from 'react';
import type { Candidate } from '../../shared/api/client.ts';
import { SIMPLE_P, candidateLabel } from './devPrediction.ts';
import type { DevPrediction } from './devPrediction.ts';

type Props = {
  candidates: readonly Candidate[];
  value: DevPrediction;
  disabled: boolean;
  problem: string | null;
  onChange: (value: DevPrediction) => void;
};

const emptyRows = () => [{ categoryId: '', p: '0.6' }, { categoryId: '', p: '0.25' }, { categoryId: '', p: '0.1' }];

// Shown only for dev releases without a model. It never shows the answer or any score.
export default function DevPredictionPanel({ candidates, value, disabled, problem, onChange }: Props) {
  const listId = useId();
  const total = value.mode === 'advanced' ? value.rows.reduce((sum, row) => sum + (Number(row.p) || 0), 0) : 1;

  return (
    <fieldset className="dev-panel" disabled={disabled}>
      <legend>개발용 인식 결과 <span>모델 미연결</span></legend>
      <p className="dev-note">모델 대신 제출할 Top-3를 정해요. 같은 그림은 처음 결과가 유지되니 후보를 바꿔 보려면 그림도 고쳐주세요.</p>
      <div className="dev-modes" role="radiogroup" aria-label="입력 방식">
        <label><input type="radio" name={`${listId}-mode`} checked={value.mode === 'simple'}
          onChange={() => onChange({ mode: 'simple', categoryId: '' })} /> 1위만 고르기</label>
        <label><input type="radio" name={`${listId}-mode`} checked={value.mode === 'advanced'}
          onChange={() => onChange({ mode: 'advanced', rows: emptyRows() })} /> 세 후보와 p 직접 입력</label>
      </div>
      <datalist id={listId}>
        {candidates.map(c => <option key={c.categoryId} value={candidateLabel(c)} />)}
      </datalist>
      {value.mode === 'simple' ? (
        <label className="dev-row">
          <span>1위 후보</span>
          <input list={listId} value={value.categoryId} placeholder="예: 사과 또는 apple"
            onChange={event => onChange({ mode: 'simple', categoryId: event.target.value })} />
          <small>p {SIMPLE_P.join(' / ')} · 2·3위는 그림마다 자동으로 정해요</small>
        </label>
      ) : (
        value.rows.map((row, i) => (
          <div className="dev-row dev-row-advanced" key={i}>
            <input list={listId} aria-label={`${i + 1}번 후보`} value={row.categoryId} placeholder={`${i + 1}번 후보`}
              onChange={event => onChange({ mode: 'advanced', rows: value.rows.map((r, j) => j === i ? { ...r, categoryId: event.target.value } : r) })} />
            <input type="number" aria-label={`${i + 1}번 후보 p`} min="0" max="1" step="0.01" value={row.p}
              onChange={event => onChange({ mode: 'advanced', rows: value.rows.map((r, j) => j === i ? { ...r, p: event.target.value } : r) })} />
          </div>
        ))
      )}
      {value.mode === 'advanced' && <p className="dev-note">p 합 {total.toFixed(2)} · 제출할 때 p가 큰 순서로 정렬해요</p>}
      {problem && <p className="dev-problem">{problem}</p>}
    </fieldset>
  );
}
