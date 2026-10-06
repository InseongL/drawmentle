// onnxruntime-web adapter behind `LogitsSession`. Loaded lazily (dynamic import) only for `browser_onnx` releases,
// so dev releases never download the runtime. Single-threaded WASM: multi-threading would need cross-origin
// isolation headers (COOP/COEP) on the page.
import * as ort from 'onnxruntime-web/wasm';
import wasmUrl from 'onnxruntime-web/ort-wasm-simd-threaded.wasm?url';
import type { ModelInfo } from '../../shared/api/client.ts';
import type { LogitsSession } from './modelRuntime.ts';

ort.env.wasm.wasmPaths = { wasm: wasmUrl };
ort.env.wasm.numThreads = 1;

async function sha256Hex(bytes: Uint8Array<ArrayBuffer>): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  return Array.from(new Uint8Array(digest), n => n.toString(16).padStart(2, '0')).join('');
}

// Fetches the release's model, refuses a file whose hash differs from the release manifest, then creates the session.
export async function loadSession(model: ModelInfo): Promise<LogitsSession> {
  const response = await fetch(model.url);
  if (!response.ok) throw new Error(`model download failed (${response.status})`);
  const bytes = new Uint8Array(await response.arrayBuffer());
  if (await sha256Hex(bytes) !== model.sha256) throw new Error('model file does not match the release');
  const session = await ort.InferenceSession.create(bytes, { executionProviders: ['wasm'] });
  return {
    async run(image: Float32Array) {
      const input = new ort.Tensor('float32', image, model.input.shape);
      const output = await session.run({ [model.input.name]: input });
      return output[model.output.name].data as Float32Array;
    },
  };
}
