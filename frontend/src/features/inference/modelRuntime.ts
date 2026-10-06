// Model output -> Top-3 for a submission (docs/model-architecture-v1.md §6.1, catalog-curation-v1.md).
// softmax(logits / T) over ALL raw outputs once, then sum raw probabilities into each candidate (merged service ID).
// No masking or renormalisation: unsupported candidates such as `bird` keep their probability and may appear in
// the Top-3, where the server defers them. Ties go to the smaller candidateIndex, as the server requires.
// The ONNX execution itself is behind `LogitsSession` so the engine (onnxruntime-web) stays a replaceable adapter.
import type { Candidate, RawClass, Top3Item } from '../../shared/api/client.ts';
import { renderStrokes, toModelInput } from './preprocess.ts';
import type { RenderSpec, StrokePoints } from './preprocess.ts';

export type LogitsSession = { run(image: Float32Array): Promise<Float32Array> };

export function candidateProbabilities(logits: ArrayLike<number>, rawClasses: readonly RawClass[], temperature: number): Map<string, number> {
  if (logits.length !== rawClasses.length) throw new Error(`expected ${rawClasses.length} logits, got ${logits.length}`);
  if (!(temperature > 0)) throw new Error('temperature must be positive');
  let max = -Infinity;
  for (let i = 0; i < logits.length; i++) max = Math.max(max, logits[i] / temperature);
  const exp = new Float64Array(logits.length);
  let total = 0;
  for (let i = 0; i < logits.length; i++) {
    exp[i] = Math.exp(logits[i] / temperature - max);
    total += exp[i];
  }
  const probs = new Map<string, number>();
  for (const raw of rawClasses) {
    probs.set(raw.candidateId, (probs.get(raw.candidateId) ?? 0) + exp[raw.classIndex] / total);
  }
  return probs;
}

export function top3FromLogits(logits: ArrayLike<number>, rawClasses: readonly RawClass[],
  candidates: readonly Candidate[], temperature: number): Top3Item[] {
  const probs = candidateProbabilities(logits, rawClasses, temperature);
  const index = new Map(candidates.map(c => [c.categoryId, c.candidateIndex]));
  return [...probs.entries()]
    .sort(([a, pa], [b, pb]) => pb - pa || index.get(a)! - index.get(b)!)
    .slice(0, 3)
    .map(([categoryId, p]) => ({ categoryId, p }));
}

export async function predictTop3(session: LogitsSession, strokes: readonly StrokePoints[], release: {
  rawClasses: readonly RawClass[]; candidates: readonly Candidate[]; temperature: number; spec?: RenderSpec;
}): Promise<Top3Item[]> {
  const logits = await session.run(toModelInput(renderStrokes(strokes, release.spec)));
  return top3FromLogits(logits, release.rawClasses, release.candidates, release.temperature);
}
