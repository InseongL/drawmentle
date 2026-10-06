// Loads the release's model once per release for `browser_onnx` releases; other releases never load the runtime.
import { useEffect, useState } from 'react';
import type { PublicRelease } from '../../shared/api/client.ts';
import type { LogitsSession } from './modelRuntime.ts';

export type ModelSessionState =
  | { status: 'off' }
  | { status: 'loading' }
  | { status: 'ready'; session: LogitsSession }
  | { status: 'failed' };

export function useModelSession(release: PublicRelease | undefined) {
  const [state, setState] = useState<ModelSessionState>({ status: 'off' });
  const [attempt, setAttempt] = useState(0);
  const model = release?.inference.mode === 'browser_onnx' ? release.model : null;

  useEffect(() => {
    if (!model) return;
    let cancelled = false;
    setState({ status: 'loading' });
    import('./onnxSession.ts')
      .then(({ loadSession }) => loadSession(model))
      .then(session => { if (!cancelled) setState({ status: 'ready', session }); },
        () => { if (!cancelled) setState({ status: 'failed' }); });
    return () => { cancelled = true; };
  }, [model?.sha256, attempt]);

  return { ...state, retry: () => setAttempt(n => n + 1) };
}
