// HTTP calls for sessions, puzzles, submissions and progress (docs/api-contract-v1.md).
// Types mirror contracts/api/openapi.json (python -m app.cli export-openapi); keep both in sync.

export type Candidate = { categoryId: string; candidateIndex: number; displayNameKo: string; displayNameEn?: string | null };

export type RawClass = { classIndex: number; categoryId: string; candidateId: string };

// Present for `browser_onnx` releases: where the model file is and how to read its output.
export type ModelInfo = {
  url: string;
  sha256: string;
  bytes: number;
  input: { name: string; shape: number[] };
  output: { name: string; shape: number[] };
  temperature: number;
};

export type PublicRelease = {
  releaseId: string;
  status: 'dev-only' | 'production';
  modelVersion: string;
  preprocessingVersion: string;
  catalogVersion: string;
  outputCalibrationVersion: string;
  drawingVersions: string[];
  brushVersions: string[];
  inference: { mode: 'dev_manual_top3' | 'browser_onnx'; note?: string | null };
  model: ModelInfo | null;
  rawClasses: RawClass[];
  candidates: Candidate[];
};

export type Puzzle = {
  puzzleId: string;
  serviceDate: string;
  puzzleNumber: number;
  release: PublicRelease;
  collectionPolicy: { version: string; enabled: boolean };
};

export type Answer = { categoryId: string; displayNameKo: string };

export type Result = {
  status: 'recognized' | 'deferred' | 'solved';
  reason: string | null;
  attemptNumber: number | null;
  displayScore: number | null;
  displayText: string | null;
  solved: boolean;
  judgedAt: string;
  answer?: Answer;
};

export type Progress = {
  state: 'playing' | 'solved';
  attemptCount: number;
  bestSubmissionId: string | null;
  bestDisplayScore: number | null;
  bestDisplayText: string | null;
  solvedSubmissionId?: string;
  answer?: Answer;
};

export type CollectionState = 'not_consented' | 'not_selected' | 'eligible' | 'pending_upload' | 'uploaded'
  | 'verified' | 'upload_failed' | 'delete_pending' | 'deleted';
// Session-level views use `eligible` for "consented"; per-submission views report that drawing's state.
export type Collection = { state: CollectionState; consentRevision: number };
export type Top3Item = { categoryId: string; p: number };

export type SubmissionRequest = {
  submissionId: string;
  releaseId: string;
  modelVersion: string;
  preprocessingVersion: string;
  catalogVersion: string;
  outputCalibrationVersion: string;
  drawingVersion: string;
  brushVersion: string;
  drawingHash: string;
  top3: Top3Item[];
  collectionConsentRevision: number;
};

export type SubmissionResponse = {
  requestSubmissionId: string;
  submissionId: string;
  puzzleId: string;
  releaseId: string;
  reuse: 'new' | 'request_retry' | 'drawing_duplicate';
  result: Result;
  progress: Progress;
  collection: Collection;
};

export type HistoryItem = { submissionId: string; result: Result };
export type ProgressPage = { puzzleId: string; progress: Progress; items: HistoryItem[]; nextBeforeAttemptNumber: number | null };
export type SessionInfo = { expiresAt: string; collection: Collection };

// Training contribution (docs/api-contract-v1.md §8). The server picks the upload path; uploads never change a game.
export type ConsentRequest = { expectedRevision: number; enabled: boolean; policyVersion?: string };
export type ConsentResponse = { enabled: boolean; policyVersion: string | null; collection: Collection };
export type UploadGrant = {
  sampleId: string;
  uploadId: string;
  method: 'PUT';
  url: string;
  contentType: 'application/json';
  maxBytes: number;
  expiresAt: string;
};
export type UploadResponse = { collection: Collection; grant: UploadGrant | null };
export type CompleteRequest = { sampleId: string; uploadId: string; consentRevision: number };

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly retryable: boolean;
  // true when the request may have reached the server but no response arrived (outcome unknown)
  readonly network: boolean;

  constructor(status: number, code: string, message: string, retryable: boolean, network = false) {
    super(message);
    this.status = status;
    this.code = code;
    this.retryable = retryable;
    this.network = network;
  }
}

type Fetch = (input: string, init?: RequestInit) => Promise<Response>;

export function createApi(fetcher: Fetch = (input, init) => fetch(input, init)) {
  // `raw` sends a prepared JSON text as is (the drawing file must keep its exact bytes for the hash check).
  async function request<T>(method: string, path: string, body?: unknown, raw?: string): Promise<T> {
    let response: Response;
    const payload = raw ?? (body === undefined ? undefined : JSON.stringify(body));
    try {
      response = await fetcher(path, {
        method,
        credentials: 'same-origin',
        headers: payload === undefined ? undefined : { 'Content-Type': 'application/json' },
        body: payload,
      });
    } catch {
      throw new ApiError(0, 'NETWORK_ERROR', '연결이 불안정해요. 그림은 그대로 두고 다시 시도해주세요.', true, true);
    }
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      const error = data?.error;
      const fallback = response.status >= 500 ? '서버에 연결하지 못했어요. 그림은 그대로 두고 잠시 후 다시 시도해주세요.'
        : '요청을 처리하지 못했어요. 잠시 후 다시 시도해주세요.';
      throw new ApiError(response.status, error?.code ?? `HTTP_${response.status}`, error?.message ?? fallback,
        error?.retryable ?? response.status >= 500, false);
    }
    return data as T;
  }

  const puzzlePath = (puzzleId: string) => `/api/puzzles/${encodeURIComponent(puzzleId)}`;
  return {
    ensureSession: () => request<SessionInfo>('POST', '/api/sessions'),
    todayPuzzle: () => request<Puzzle>('GET', '/api/puzzles/today'),
    progress: (puzzleId: string, beforeAttemptNumber?: number | null, limit = 10) => {
      const query = new URLSearchParams({ limit: String(limit) });
      if (beforeAttemptNumber != null) query.set('beforeAttemptNumber', String(beforeAttemptNumber));
      return request<ProgressPage>('GET', `${puzzlePath(puzzleId)}/progress?${query}`);
    },
    submit: (puzzleId: string, body: SubmissionRequest) =>
      request<SubmissionResponse>('POST', `${puzzlePath(puzzleId)}/submissions`, body),
    byRequest: (puzzleId: string, submissionId: string) =>
      request<SubmissionResponse>('GET', `${puzzlePath(puzzleId)}/submissions/by-request/${encodeURIComponent(submissionId)}`),
    setConsent: (body: ConsentRequest) => request<ConsentResponse>('PUT', '/api/collection-consent', body),
    requestUpload: (submissionId: string, consentRevision: number) =>
      request<UploadResponse>('POST', `/api/submissions/${encodeURIComponent(submissionId)}/drawing-upload`, { consentRevision }),
    putUpload: (grant: UploadGrant, drawing: string) => request<null>(grant.method, grant.url, undefined, drawing),
    completeUpload: (submissionId: string, body: CompleteRequest) =>
      request<{ collection: Collection }>('POST', `/api/submissions/${encodeURIComponent(submissionId)}/drawing-complete`, body),
  };
}

export type Api = ReturnType<typeof createApi>;
