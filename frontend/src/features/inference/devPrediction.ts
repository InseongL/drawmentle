// Dev-only stand-in for the browser model: builds a full-catalog-style Top-3 from the dev panel.
// Ordering follows the model runtime rule (p desc, then candidateIndex asc); the server rejects other orders.
import type { Candidate, Top3Item } from '../../shared/api/client.ts';

export const SIMPLE_P = [0.7, 0.2, 0.1] as const;

export type DevPrediction =
  | { mode: 'simple'; categoryId: string }
  | { mode: 'advanced'; rows: { categoryId: string; p: string }[] };

export const initialDevPrediction = (): DevPrediction => ({ mode: 'simple', categoryId: '' });

export function candidateLabel(c: Candidate): string {
  return `${c.displayNameKo} (${c.categoryId})`;
}

// Accepts the datalist label, the category ID or the Korean name.
export function resolveCandidate(candidates: readonly Candidate[], text: string): Candidate | null {
  const value = text.trim();
  if (!value) return null;
  const id = /\(([^()]+)\)$/.exec(value)?.[1] ?? value;
  return candidates.find(c => c.categoryId === id) ?? candidates.find(c => c.displayNameKo === value) ?? null;
}

export function orderTop3(items: Top3Item[], candidates: readonly Candidate[]): Top3Item[] {
  const index = new Map(candidates.map(c => [c.categoryId, c.candidateIndex]));
  return [...items].sort((a, b) => b.p - a.p || index.get(a.categoryId)! - index.get(b.categoryId)!);
}

// Two filler candidates picked from the drawing hash, so the same drawing always gets the same Top-3.
function fillers(candidates: readonly Candidate[], exclude: string, drawingHash: string): Candidate[] {
  const pool = candidates.filter(c => c.categoryId !== exclude);
  const first = parseInt(drawingHash.slice(0, 8), 16) % pool.length;
  let second = parseInt(drawingHash.slice(8, 16), 16) % (pool.length - 1);
  if (second >= first) second += 1;
  return [pool[first], pool[second]];
}

export type DevTop3 = { ok: true; top3: Top3Item[] } | { ok: false; message: string };

export function buildDevTop3(candidates: readonly Candidate[], input: DevPrediction, drawingHash: string): DevTop3 {
  if (input.mode === 'simple') {
    const chosen = resolveCandidate(candidates, input.categoryId);
    if (!chosen) return { ok: false, message: '개발용 인식 결과에서 1위 후보를 골라주세요.' };
    const [second, third] = fillers(candidates, chosen.categoryId, drawingHash);
    return {
      ok: true,
      top3: orderTop3([chosen, second, third].map((c, i) => ({ categoryId: c.categoryId, p: SIMPLE_P[i] })), candidates),
    };
  }
  const rows = input.rows.map(row => ({ candidate: resolveCandidate(candidates, row.categoryId), p: Number(row.p) }));
  if (rows.some(r => !r.candidate)) return { ok: false, message: '후보 세 개를 모두 목록에서 골라주세요.' };
  if (new Set(rows.map(r => r.candidate!.categoryId)).size !== 3) return { ok: false, message: '서로 다른 후보 세 개가 필요해요.' };
  if (rows.some(r => !Number.isFinite(r.p) || r.p < 0 || r.p > 1)) return { ok: false, message: 'p는 0부터 1 사이 숫자예요.' };
  if (rows.reduce((sum, r) => sum + r.p, 0) > 1 + 1e-6) return { ok: false, message: 'p의 합은 1을 넘을 수 없어요.' };
  return { ok: true, top3: orderTop3(rows.map(r => ({ categoryId: r.candidate!.categoryId, p: r.p })), candidates) };
}

export function isDevPredictionReady(candidates: readonly Candidate[], input: DevPrediction): DevTop3 {
  // Validity does not depend on the hash; a fixed placeholder is enough for enabling the submit button.
  return buildDevTop3(candidates, input, '0'.repeat(64));
}
