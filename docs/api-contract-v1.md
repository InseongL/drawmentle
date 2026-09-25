# 게임 API 계약 v1 — 구현 기준안

기준: 기획서 v3.2, 서비스 아키텍처, 프론트 화면 계획. 이 문서는 구현 기준을 구체화한 설계이며 실행 중인 API 명세가 아니다. 임계값·점수 범위·수집 비율·보관 기간·실제 지원 목록은 확정하지 않는다.

실제 구현 후에는 각 모듈의 FastAPI/Pydantic 타입에서 `contracts/api/openapi.json`을 생성하고 프론트 타입도 여기에서 생성한다. OpenAPI 파일을 별도로 수동 작성하지 않는다. [FastAPI 공식 OpenAPI 안내](https://fastapi.tiangolo.com/how-to/extending-openapi/)

## 1. 공통 규칙

- HTTP JSON은 camelCase, 서버 내부/DB는 snake_case를 사용한다. JSON의 알 수 없는 필드는 거부한다.
- 인증은 익명 세션 쿠키다. 요청 본문으로 세션 소유자를 지정하지 않는다. 운영은 동일 출처 경로와 HTTPS를 기본으로 하며 쿠키는 HttpOnly·Secure·SameSite 정책을 설정한다. 변경 요청은 허용 Origin을 확인한다.
- 시각은 UTC ISO 8601, 문제의 `serviceDate`는 한국 시간 기준 `YYYY-MM-DD`다. 서버가 오늘 날짜를 결정한다.
- `puzzleId`, `releaseId`는 불투명한 문자열 ID, 클라이언트가 발급하는 `submissionId`는 UUID다. 예시 ID는 테스트용이다.
- 오류는 `{"error":{"code":"...","message":"...","retryable":false},"requestId":"..."}` 형식으로 통일한다. 원본 그림·비밀 키·내부 manifest를 오류에 넣지 않는다.
- 초기 판정은 브라우저 결과 기반 MVP 기준안이다. 서버 재추론을 도입하면 성공 확정 전 단계를 별도 버전으로 변경한다.

## 2. 엔드포인트

| 메서드·경로 | 성공 응답 | 주요 내용 |
|---|---|---|
| `POST /api/sessions` | 201 신규 / 200 기존 | 세션 쿠키와 만료 시각·현재 수집 선택 반환. 유효한 세션을 매번 교체하지 않음 |
| `GET /api/puzzles/today` | 200 | 오늘의 공개 문제·릴리스·공개 수집 안내 버전 |
| `GET /api/puzzles/{puzzleId}` | 200 | 공개된 문제 정보. 미래 문제·정답은 공개하지 않음 |
| `GET /api/puzzles/{puzzleId}/progress` | 200 | 현재 진행 요약, 확정 시도 기록, 페이지 커서 |
| `POST /api/puzzles/{puzzleId}/submissions` | 201 신규 / 200 재사용 | 제출·판정. 아래 계약 적용 |
| `GET /api/puzzles/{puzzleId}/submissions/by-request/{submissionId}` | 200 | 응답 유실 후 요청 ID로 확정 결과 조회. 미커밋·미접수면 404 |
| `PUT /api/collection-consent` | 200 | 수집 선택 변경. 점수·시도 수와 독립 |
| `POST /api/submissions/{submissionId}/drawing-upload` | 200 | 대표 제출 ID로 업로드 권한 발급 또는 현재 수집 상태 반환 |
| `POST /api/submissions/{submissionId}/drawing-complete` | 200 | 파일 확인 후 수집 상태 반환. 게임 성공 상태는 변경하지 않음 |

조회에서 다른 세션의 자료와 없는 자료는 모두 404다. `by-request`의 404는 최초 요청이 아직 처리 중일 수도 있으므로 프론트가 새 ID를 만들지 않고 동일 ID·본문으로 재시도한다.

## 3. 공개 문제와 릴리스

문제 응답은 `puzzleId`, `serviceDate`, `release`, `collectionPolicy`를 포함한다. `release`에는 ID·모델 URL/해시·버전·입출력 명세·원본 카테고리 출력 순서·후보 합산 매핑과 해시·매핑 후 후보 순서·전처리 및 출력 보정 위치를 담는다. 정답, 내부 성공 임계값, 속성 벡터·점수표는 제외한다.

한 문제의 release ID는 변경하지 않는다. 공개된 과거 문제는 보존 정책 범위에서 이어 할 수 있다. 자정에 접속 중인 문제를 자동 교체하지 않는다. 실제 공개 manifest의 상세 스키마는 `contracts/model`의 해당 규격을 따른다.

## 4. 제출 요청

```json
{
  "submissionId": "00000000-0000-4000-8000-000000000001",
  "releaseId": "fixture-release-v1",
  "modelVersion": "fixture-model-v1",
  "preprocessingVersion": "fixture-preprocess-v1",
  "catalogVersion": "fixture-catalog-v1",
  "outputCalibrationVersion": "none-v1",
  "drawingVersion": "strokes-v1",
  "brushVersion": "pen-v1",
  "drawingHash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "top3": [
    {"categoryId": "apple", "p": 0.55},
    {"categoryId": "pear", "p": 0.25},
    {"categoryId": "banana", "p": 0.10}
  ],
  "collectionConsentRevision": 0
}
```

이 예시의 ID·해시·점수는 합성 자료다. 실제 운영 임계값이나 모델 결과가 아니다.

| 필드 | 검증 |
|---|---|
| `submissionId` | 제출 사본마다 한 UUID. 결과를 모르거나 재시도 중이면 기존 ID 유지 |
| `releaseId`와 4개 모델 관련 버전 | 문제에 고정된 공개 릴리스와 정확히 일치 |
| `drawingVersion`, `brushVersion` | 릴리스가 허용한 그림·펜 규격 |
| `drawingHash` | 정해진 획 직렬화의 SHA-256, 소문자 16진수 64자. 서버 그림 검증의 대체물이 아님 |
| `top3` | 정확히 3개, 서로 다른 매핑 후 후보 ID(미지원 후보 포함). boolean이 아닌 유한한 숫자 p, 각각 0~1 |
| Top-3 순서 | p 내림차순. 같은 p이면 후보에 속한 원본 class_index의 최솟값인 candidate_index 오름차순. 서버가 조용히 재정렬하지 않음 |
| Top-3 합 | `sum(p) <= 1 + 1e-6`. 이 허용 오차는 부동소수점 입력 검사 규칙이며 성공 임계값이 아님. 합 0은 정상 `deferred` 처리 |
| `collectionConsentRevision` | 세션에서 확인한 수집 선택 리비전, 초기 0. 게임 계산에 사용하지 않음 |

정답 카테고리, q, 유사도 점수, 성공 여부는 클라이언트가 보내지 않는다. Top-3는 [카테고리 정리](catalog-curation-v1.md)의 매핑을 적용한 후보 기준이다. 전체 345개 원본에 보정·softmax를 적용한 뒤 대표 ID별로 확률을 합산하고, 미지원 `bird`도 자기 ID와 확률을 유지한다. 마스킹·재정규화하지 않는다. 매핑 후 후보 목록에 없는 ID(통합된 원본 ID 포함)는 422, 유효하지만 점수 미지원인 후보는 `deferred/unsupported_candidate`다. Top-3 합 0 또는 미지원 후보이면 나머지만 골라 q를 만들지 않는다. 보류·성공 임계값은 매핑 후 p 기준으로 검증한다.

## 5. 제출 응답

```json
{
  "requestSubmissionId": "00000000-0000-4000-8000-000000000001",
  "submissionId": "10000000-0000-4000-8000-000000000001",
  "puzzleId": "fixture-puzzle-v1",
  "releaseId": "fixture-release-v1",
  "reuse": "new",
  "result": {
    "status": "recognized",
    "reason": null,
    "attemptNumber": 1,
    "displayScore": 38.72,
    "displayText": "38.72",
    "solved": false,
    "judgedAt": "2026-09-22T10:00:00Z"
  },
  "progress": {
    "state": "playing",
    "attemptCount": 1,
    "bestSubmissionId": "10000000-0000-4000-8000-000000000001",
    "bestDisplayScore": 38.72,
    "bestDisplayText": "38.72"
  },
  "collection": {"state": "not_consented", "consentRevision": 0}
}
```

`requestSubmissionId`는 클라이언트가 보낸 이번 요청 ID, 응답의 `submissionId`는 서버가 별도로 발급한 판정 결과의 대표 UUID다. 서로 다른 세션에서 같은 요청 UUID를 사용해도 대표 ID가 충돌하지 않는다. `reuse`는 `new`, `request_retry`, `drawing_duplicate` 중 하나다. 프론트는 대표 ID로 기록을 합쳐 중복 행을 만들지 않는다. 요청 조회 API의 응답은 `request_retry`와 같은 형태다.

| result.status | 점수·표시 문자열 | 시도 번호 | solved | answer |
|---|---|---|---|---|
| `recognized` | 숫자 + 서버 형식 문자열 | 양의 정수 | false | 필드 자체 없음 |
| `deferred` | 둘 다 null | null | false | 필드 자체 없음 |
| `solved` | 숫자 + 서버 형식 문자열 | 양의 정수 | true | `{"categoryId":"...","displayNameKo":"..."}` |

`reason`은 deferred에서 `low_confidence`, `unsupported_candidate`, `insufficient_attributes` 등 버전이 있는 코드, 그 외에는 null이다. 서버가 제공하지 못하는 점수를 0으로 만들지 않는다. `displayText`는 표시 자릿수를 확정하기 전에도 프론트가 독자적으로 반올림하지 않도록 제공한다. 예시 38.72가 0~100 범위를 확정하지 않는다.

`result`는 해당 제출의 확정 결과이며 재사용해도 변하지 않는다. `progress`, `collection`은 **응답을 구성할 때 조회한 현재 상태**다. 최초 응답 전체를 그대로 캐시해 돌려주지 않는다. 네트워크에서 응답 도착 순서가 바뀔 수 있으므로 프론트는 같은 게임의 attemptCount가 작은 진행 응답, consentRevision이 작은 수집 선택 응답으로 최신 화면을 되돌리지 않는다. 최고 기록은 서버 내부 비교값으로 결정하며 동점이면 최신 유효 시도를 선택한다.

성공 후에는 새 그림 제출을 `409 GAME_ALREADY_SOLVED`로 거부하는 초기 화면 계획을 채택한다. 이미 처리한 요청이나 같은 그림의 기존 결과 조회는 계속 허용한다. 성공 여부를 점수 크기로 추정하지 않는다.

## 6. 중복 처리 계약

서버의 판정 요청 지문에는 문제 ID, release/모델/전처리/카테고리/출력 보정 버전, 그림/펜 버전, 그림 해시, 순서 있는 Top-3 ID/p를 포함한다. `submissionId`·수집 리비전·쿠키·전송 시각은 제외한다.

지문은 검증된 서버 타입을 정해진 순서로 직렬화해 SHA-256으로 만든다. 공백·JSON key 순서·`0.1`과 `0.10` 표기 차이는 같은 요청으로 취급한다. p는 IEEE 754 binary64의 big-endian 표현으로 고정하고 -0은 +0으로 정규화한다. 문자열은 UTF-8 길이와 바이트를 함께 기록해 필드 경계를 구분한다. NaN/무한대는 지문 생성 전에 거부한다. 정확한 필드 순서와 지문 버전은 구현 시 공통 사례로 고정하며, 클라이언트가 이 지문을 계산해 보낼 필요는 없다.

| 상황 | 동작 |
|---|---|
| 같은 요청 ID + 같은 판정 지문 | 원래 대표 결과 반환. 재계산·횟수 증가 없음 |
| 같은 요청 ID + 다른 판정 지문 | 409 `IDEMPOTENCY_CONFLICT` |
| 다른 요청 ID + 같은 그림 키 | 기존 결과를 반환하고 새 요청 ID도 그 결과에 매핑 |
| 위 별칭 ID를 다시 다른 본문으로 사용 | 409. 별칭에도 최초 지문을 저장해야 함 |
| 다른 요청 ID + 새 그림, 게임 진행 중 | 새 판정 결과와 요청 매핑 저장 |
| 동시 요청 | DB에서 직렬화하고 고유 제약으로 한 결과만 확정 |

그림 키는 `(gameSessionId, drawingVersion, brushVersion, drawingHash)`다. game session에 문제·release가 고정된다. 같은 그림 키에 다른 p를 보내도 새 요청 ID라면 기존 결과를 재사용한다. 클라이언트가 주장한 해시를 사용하는 MVP 정책이며 치팅 방지 검증은 아니다.

## 7. 진행 복원

`GET .../progress?limit=10&beforeAttemptNumber=N`으로 최신 확정 시도를 조회한다. limit은 기본 10, 최대 50. `beforeAttemptNumber`는 미포함 경계다. 순서는 시도 번호 내림차순이며 새 제출이 추가돼도 과거 페이지가 밀리지 않는다.

응답은 `progress`, `items: [{submissionId, result}]`, `nextBeforeAttemptNumber`로 구성한다. 성공한 게임은 progress에만 `answer`와 `solvedSubmissionId`를 추가한다. 게임 행이 아직 없으면 playing·0회·최고값 null·빈 items·커서 null을 반환한다. deferred는 일반 기록 목록에서 제외하며 요청 ID 조회로 복구할 수 있다. 로컬 썸네일이 없으면 점수 기록은 유지하고 미리보기 없음으로 표시한다. 최고값이나 시도 수를 현재 페이지 길이로 계산하지 않는다.

## 8. 수집 동의와 업로드

수집 선택은 **별도 API + 리비전 참조**로 관리한다. 오래된 제출이 동의를 바꾸지 못하게 한다.

`PUT /api/collection-consent` 요청은 `expectedRevision`, `enabled`, `policyVersion`이다. 세션을 처음 만들 때 리비전 0·미동의로 시작한다. enabled=true일 때 현재 안내 버전과 일치해야 한다. 실제 변경 때 리비전을 1 증가시키고 이력을 남긴다. 같은 변경의 응답을 잃어 재전송했는데 현재 값이 이미 동일하면 현재 상태를 반환한다. 현재 값이 다르고 리비전도 다르면 409 `CONSENT_REVISION_CONFLICT`다.

제출은 수집 리비전을 참조할 뿐 동의를 변경하지 않는다. 오래된 리비전으로 온 제출도 게임 판정은 처리하지만 자동 업로드 대상으로 승인하지 않는다. 최신 상태를 확인한 별도 업로드 요청에서 다시 자격을 확인할 수 있다. 수집 정책 변경도 진행 중 문제의 판정 결과를 바꾸지 않는다.

수집 표본 선정은 대표 제출마다 **동의와 별개인 후보 선정 결과**를 한 번만 기록한다. 이 메타데이터가 그림 보관 동의는 아니다. 동일 그림 재시도에서 다시 추첨하지 않는다. 수집 비율과 정책 버전은 운영 설정으로 정한다.

응답의 collection.state는 `not_consented`, `not_selected`, `eligible`, `pending_upload`, `uploaded`, `verified`, `upload_failed`, `delete_pending`, `deleted` 중 하나다. `eligible`은 동의·선정을 충족하지만 아직 표본 행/권한이 없는 상태이며 별도 업로드 요청에서 다시 승인받아야 한다. 삭제 상태가 있으면 자격 상태보다 우선해 반환한다. 그림판의 최신 그림이 아닌 해당 대표 제출의 고정 사본을 업로드한다.

업로드 요청은 대표 ID와 현재 `consentRevision`으로 호출한다. 서버는 소유권·최신 동의·후보 선정·삭제 상태를 확인한다. 미동의/미선정이면 URL 없이 해당 상태를 반환한다. 승인하면 서버가 정한 객체 key, 만료 시각, 허용 크기·형식에 연결된 업로드 권한을 반환한다. 클라이언트가 임의 저장 경로를 지정하지 않는다.

완료 요청은 `sampleId`, `uploadId`, `consentRevision`을 보낸다. 서버가 현재 동의, 업로드 시도, 객체 존재, 형식·크기, 정규화된 원본의 그림 해시를 다시 확인해야 `verified`다. 파일을 확인하기 전에는 `verified`로 표시하지 않는다. 그림 해시는 직렬화된 원본 해시이며 네트워크 파일의 바이트 체크섬과 구분한다.

동의 철회 시 업로드 권한 신규 발급을 막고 기존 수집 자료를 학습 대상에서 즉시 제외한다. 파일은 `delete_pending → deleted`로 정리한다. 이미 발급된 URL로 늦게 올라온 파일도 완료 처리·재처리에서 거부하고 정리한다. 삭제 요청된 표본은 재동의만으로 자동 복원하지 않는다. 정확한 보관 기한·삭제 운영 방식은 수집 공개 전 확정한다.

## 9. 오류 코드와 프론트 대응

| HTTP | 코드 예시 | 대응 |
|---|---|---|
| 401 | `SESSION_REQUIRED`, `SESSION_EXPIRED` | 세션 재확인. 새 세션이 이전 기록을 승계한다고 가정하지 않음 |
| 404 | `PUZZLE_NOT_FOUND`, `SUBMISSION_NOT_FOUND` | 공개 여부·소유권 확인. 요청 조회 404는 같은 ID로 재시도 가능 |
| 409 | `VERSION_MISMATCH` | 해당 문제의 고정 manifest 재조회, 그림 유지 |
| 409 | `IDEMPOTENCY_CONFLICT` | 자동 재시도 중단. 같은 ID의 사본을 임의 변경하지 않음 |
| 409 | `GAME_ALREADY_SOLVED` | 최신 진행 상태 복원 |
| 409 | `CONSENT_REVISION_CONFLICT` | 최신 수집 선택 상태 확인 후 사용자 선택 반영 |
| 410 | `PUZZLE_CLOSED`, `SAMPLE_DELETED` | 해당 리소스의 새 처리 종료. 보존된 기존 결과 조회 여부는 정책 적용 |
| 413/422 | `INVALID_DRAWING`, `INVALID_TOP3`, `INVALID_REQUEST` | 입력 수정. 같은 잘못된 본문 반복 전송 금지 |
| 429 | `RATE_LIMITED` | Retry-After에 따라 같은 제출 ID로 재시도 |
| 503 | `RELEASE_UNAVAILABLE`, `TEMPORARY_FAILURE` | 그림 유지, 같은 ID 재시도. 시도 횟수 임의 증가 금지 |

같은 DB 트랜잭션 안의 결과가 확정됐는지 모르는 통신 장애에서는 새 제출 ID를 발급하지 않는다. 실패를 deferred나 0점으로 저장하지 않는다. API 구현 전 필요한 한계값·오류 문구는 이 계약을 유지하며 조정할 수 있다.

DB 제약과 동시성 순서는 [DB 스키마](database-schema-v1.md), 합성 요청·응답은 [fixture](../contracts/fixtures/submission-cases.json)를 참조한다.

## 10. 구현 상태 (2026-09-25)

`backend/app/modules`의 세션·문제·제출 API가 이 계약대로 동작하고, 생성된 스키마는 [`contracts/api/openapi.json`](../contracts/api/openapi.json)(`python -m app.cli export-openapi`)이다. 구현하며 정한 세부 사항:

- 판정 지문 `judgement-fp-v1`: 버전 문자열, 문제 ID, release·모델·전처리·카테고리·출력 보정·그림·펜 버전, 그림 해시 순서로 각 문자열을 `4바이트 big-endian 길이 + UTF-8`로 기록한 뒤 Top-3 개수와 각 `(ID, p binary64 big-endian)`을 이어 SHA-256을 만든다.
- 문제 응답에 표시용 `puzzleNumber`(해당 날짜까지의 문제 수)를 넣는다. 공개 manifest의 `candidates`(대표 ID·candidate_index·한국어 이름)와 `rawClasses`(원본 345개 → 대표 ID)에 각각 해시가 있다.
- 성공한 게임의 `progress`에는 제출 응답과 진행 조회 모두 `answer`·`solvedSubmissionId`를 넣는다. 성공 전에는 두 필드가 없다.
- 추가 오류: 허용되지 않은 Origin의 변경 요청 `403 ORIGIN_NOT_ALLOWED`(운영에서는 Origin 누락도 거부), 예상하지 못한 오류 `500 INTERNAL_ERROR`, 고유 제약 충돌 `503 TEMPORARY_FAILURE`(같은 요청 ID로 재시도).
- 수집 API(8절)는 아직 없다. 모든 응답의 `collection`은 `not_consented`와 세션의 현재 리비전이며 제출에는 `collection-disabled-v0`·`not_selected`를 기록한다.
- 개발용 릴리스(`status: dev-only`, `inference.mode: dev_manual_top3`)는 모델이 없고 화면의 개발 패널이 Top-3를 정한다. 운영 릴리스는 같은 요청 형식에 브라우저 모델 결과를 넣는다.
