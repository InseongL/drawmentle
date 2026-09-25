# DB 스키마와 트랜잭션 v1 — 구현 기준안

기준: [API 계약](api-contract-v1.md), [서비스 아키텍처](service-architecture-v1.md), [핵심 파일 계획](core-file-plan-v1.md). PostgreSQL을 사용하는 설계안이며 실제 테이블·마이그레이션을 생성한 상태는 아니다.

게임 기록, 학습용 그림, 검수 라벨의 수명과 책임을 분리한다. 첫 화면 연결에는 게임 테이블부터 구현하고, 수집 테이블은 수집 기능을 연결할 때 추가한다. MLOps 실행기·작업 큐·모델 관리 서버는 초기 필수 구성에 포함하지 않는다.

## 1. 공통 규칙

- DB 필드는 snake_case. 내부 ID는 서버가 발급하는 UUID, 외부 릴리스·문제 ID는 text, 시각은 timestamptz, 서비스 날짜는 date다.
- 아래에서 `?`는 NULL 허용을 뜻한다. 이외 필수 필드는 NOT NULL로 구현한다. `created_at`·`updated_at`은 필요한 테이블에 둔다.
- p·q·내부 비교값은 double precision, 확정 화면 점수는 표시 규격에 맞는 numeric과 문자열을 함께 보관한다. NaN·무한대는 API와 저장 경계에서 거부한다. 점수 범위는 아직 고정하지 않는다.
- 관계 ID는 FK, 중복 방지는 UNIQUE, 행 자체의 상태 조건은 CHECK로 구현한다. 다른 행·artifact를 검사하는 조건은 service의 트랜잭션 또는 릴리스 발행 검사로 보장한다.
- 게임 세션은 **익명 세션 × 문제** 한 개다. 모델이나 점수 릴리스가 바뀌어도 이미 공개된 문제의 릴리스는 바꾸지 않는다.
- 원본 획·이미지·ONNX·대형 점수표는 DB 본문에 넣지 않는다. DB는 비공개 객체 위치·해시·버전·상태를 관리한다.

## 2. 게임 테이블

### release_bundles — 변경 불가 배포 단위

| 필드 | 타입·역할 |
|---|---|
| release_id | text PK |
| model_version, preprocessing_version, catalog_version, output_calibration_version | text, 공개 모델 계약의 버전 |
| scoring_version, recognition_version | text, 내부 점수·보류·성공 규칙 버전 |
| public_manifest, public_manifest_sha256 | jsonb, text. 공개 전용 필드만 포함 |
| private_manifest_key, private_manifest_sha256 | text. 비공개 자료 위치와 내용 해시 |
| published_at | timestamptz. 검사를 통과한 발행 기록 |

이 테이블에는 준비 중인 불완전한 릴리스를 넣지 않는다. 발행 도구가 모델 출력 순서·지원 목록·점수표·해시의 호환성을 검사한 후 등록한다. 발행된 행과 참조 파일은 수정하지 않고 새 ID를 발급한다. 애플리케이션 DB 계정에는 발행 행의 변경 권한을 주지 않는 방식으로 구현한다.

### puzzles — 데일리 정답

| 필드 | 타입·역할 |
|---|---|
| puzzle_id | text PK, 날짜·정답을 인코딩하지 않는 ID |
| service_date | date UNIQUE, 한국 시간의 출제 날짜 |
| release_id | text FK → release_bundles |
| answer_category_id | text, 서버 비공개 정답 |
| answer_display_name_ko | text, 출제 당시 표시명 사본 |
| opens_at, closes_at? | timestamptz. 과거 문제를 허용하면 마감 없음 |
| state | text, scheduled / published / closed |

`UNIQUE(puzzle_id, release_id)`를 추가해 하위 game session의 릴리스 일치를 복합 FK로 검사한다. 정답이 해당 릴리스의 데일리 정답 목록에 포함되는지는 발행 단계에서 검사한다. 공개 후 정답·릴리스·표시명은 수정하지 않고, 운영상 문제가 있으면 문제를 닫는다.

### anonymous_sessions — 익명 사용자 문맥

| 필드 | 타입·역할 |
|---|---|
| session_id | uuid PK |
| token_hash | text UNIQUE. 충분히 무작위인 쿠키 토큰의 해시만 저장 |
| expires_at, created_at | timestamptz |
| consent_revision | bigint, 초기 0, 0 이상 |
| collection_enabled | boolean, 초기 false |
| collection_policy_version? | text, enabled=true일 때 필수 |

쿠키 원문을 DB나 로그에 남기지 않는다. 인증 만료와 그림 삭제 기한은 별개다. 만료를 이유로 그림을 무기한 보관하거나 모든 관련 행을 무조건 연쇄 삭제하지 않는다. 실제 수명 정책은 공개 전에 확정한다.

### game_sessions — 진행 요약

| 필드 | 타입·역할 |
|---|---|
| game_session_id | uuid PK |
| session_id | uuid FK → anonymous_sessions |
| puzzle_id, release_id | text, 복합 FK → puzzles(puzzle_id, release_id) |
| state | text, playing / solved |
| attempt_count | integer, 초기 0, 0 이상 |
| best_submission_id? | uuid, 최고 내부 비교값의 제출 |
| solved_submission_id?, solved_at? | uuid, timestamptz, 성공 시 설정 |

`UNIQUE(session_id, puzzle_id)`와 `UNIQUE(game_session_id, release_id)`를 둔다. 최고·성공 참조는 `(submission_id, game_session_id)` 복합 FK로 **동일 게임의 제출**만 가리킨다. 신규 game session은 참조를 NULL로 생성하고 제출 저장 뒤 갱신하므로 순환 참조 때문에 초기 행 생성이 막히지 않는다. playing이면 성공 참조·시각은 NULL, solved이면 둘 다 필수다.

### submissions — 한 그림의 확정 판정

| 필드 | 타입·역할 |
|---|---|
| submission_id | uuid PK, 서버 대표 ID. 클라이언트 요청 ID와 다름 |
| game_session_id, release_id | uuid, text, 복합 FK → game_sessions |
| drawing_version, brush_version, drawing_hash | text, 정해진 원본 직렬화와 해시 |
| top3 | jsonb, 순서 있는 원래 categoryId/p 3개 사본 |
| top3_sum | double precision |
| status, reason? | text, recognized / deferred / solved 및 보류 사유 |
| attempt_number? | integer. 보류는 NULL, 유효 판정만 양수 |
| comparison_score?, display_score?, display_text? | double precision, numeric, text |
| judged_at | timestamptz, 판정 확정 시각 |
| collection_policy_version | text, 최초 표본 선정 규칙 |
| collection_selection | text, not_selected / success_sample / failure_sample |

필수 제약:

- `UNIQUE(game_session_id, drawing_version, brush_version, drawing_hash)`: 같은 그림은 보류 결과까지 재사용한다.
- `UNIQUE(game_session_id, attempt_number)`: 유효 시도 번호 중복 방지. 기본 PostgreSQL UNIQUE에서 NULL은 서로 다른 값으로 취급하므로 여러 보류 행을 허용한다.
- `UNIQUE(submission_id, game_session_id)`: 다른 테이블의 동일 게임 참조에 사용한다.
- 게임당 성공 행 하나만 허용하는 부분 UNIQUE 인덱스: `game_session_id WHERE status = 'solved'`.
- deferred이면 시도 번호·세 점수 필드는 NULL이고 사유는 필수. recognized/solved이면 시도 번호는 양수, 세 점수 필드는 필수, 사유는 NULL이다.
- 해시는 소문자 16진수 64자, Top-3는 배열 길이 3. ID·정렬·수치·릴리스 관계의 상세 검증은 API/판정 경계에서 수행한다.

대표 결과와 표본 선정은 저장 후 변경하지 않는다. 추후 검수 라벨을 바꿔도 당시 판정을 덮어쓰지 않는다. 최고값 비교에는 반올림 전 comparison_score를 사용하며 같은 값이면 더 큰 attempt_number를 선택한다. [PostgreSQL UNIQUE·FK 공식 설명](https://www.postgresql.org/docs/current/ddl-constraints.html)

### submission_requests — 요청 ID와 대표 결과 연결

| 필드 | 타입·역할 |
|---|---|
| game_session_id, request_id | uuid, 복합 PK. request_id는 클라이언트 제출 UUID |
| submission_id | uuid, 대표 결과 |
| judgement_fingerprint | text, 검증된 판정 요청의 SHA-256 |
| created_at | timestamptz |

`(submission_id, game_session_id)`는 submissions의 복합 FK다. 다른 요청 ID로 같은 그림을 보내면 새 판정 대신 이 테이블에 별칭 행만 추가한다. 별칭도 최초 요청 지문을 갖기 때문에 이후 같은 별칭 ID의 본문 변경을 거부할 수 있다. 최초 요청도 이 테이블에 반드시 기록한다.

### submission_score_details — 비공개 계산 근거

`submission_id`를 PK/FK로 하는 1:1 테이블에 `details_version`, `details jsonb`를 둔다. q, 후보별 관계 점수, 속성별 기여도·보정·가중치·내부 순위와 적용 규칙을 담는다. 보류에서는 계산하지 못한 값은 NULL 또는 미계산 사유로 남기고 허위 0점을 만들지 않는다. 정답과 내부 순위가 섞일 수 있으므로 공개 응답 모델로 직접 직렬화하지 않는다.

## 3. 수집 테이블 — 수집 기능 연결 시 추가

### collection_consents

`(session_id uuid FK, revision bigint)` 복합 PK, `enabled boolean`, `policy_version text?`, `changed_at timestamptz`를 둔다. 최초 리비전 0·미동의는 첫 수집 선택 변경 전에 collections service가 세션 잠금 안에서 보충한다. 실제 변경 리비전부터는 익명 세션의 현재 선택과 이력을 동일 트랜잭션에서 갱신하고 기존 이력을 수정하지 않는다. 수집 기능을 나중에 붙일 경우 기존 세션의 0번 이력을 마이그레이션으로 미리 채울 수도 있다.

현재 세션의 수집 필드는 빠른 조회용이다. 이력의 최신 리비전과 일치해야 하며 `sessions`의 인증 기능은 동의를 변경하지 않는다. 변경 유스케이스는 `collections`가 맡는다.

### drawing_samples

| 필드 | 타입·역할 |
|---|---|
| sample_id | uuid PK |
| submission_id | uuid UNIQUE FK → submissions, 그림당 수집 표본 하나 |
| session_id, consent_revision | uuid, bigint, 복합 FK → collection_consents |
| state | pending_upload / uploaded / verified / upload_failed / delete_pending / deleted |
| active_upload_id? | uuid, 같은 sample의 업로드 시도만 참조 |
| verified_object_key?, verified_object_version?, file_sha256? | text, 서버가 확인한 변경 불가 원본 객체 |
| byte_size?, stroke_count?, point_count? | bigint/integer, 확인한 원본 정보 |
| verified_at?, deletion_requested_at?, deleted_at? | timestamptz |
| last_error_code? | text, 재처리용 제한된 코드 |

소유 세션이 submission의 세션과 일치하는지는 업로드 승인 트랜잭션에서 확인한다. `session_id`를 본문에서 받지 않는다. `not_consented`·`not_selected`는 원본 행 생성 전 API에서 계산하는 자격 상태이며 위 저장 상태와 구분한다. 초기에는 동의·선정을 모두 충족할 때만 sample 행을 만든다.

verified이면 확인 시각·원본 객체 참조·파일 해시·크기는 필수다. 파일 확인은 검수 라벨 확인과 다르다. delete_pending/deleted는 학습 대상에서 즉시 제외하며 재동의로 되돌리지 않는다.

### drawing_uploads

`upload_id uuid PK`, `sample_id uuid FK`, `object_key text UNIQUE`, `consent_revision bigint`, `expires_at timestamptz`, `state text`, `last_error_code?`를 둔다. 상태는 issued / received / verified / rejected / expired이며 `UNIQUE(upload_id, sample_id)`로 sample의 active_upload 참조를 제한한다.

권한 갱신 시 새 upload ID와 **새 임시 객체 경로**를 만든다. 유효한 동일 시도의 재요청은 같은 권한을 재사용할 수 있다. 이전 URL로 늦게 올라온 파일이 검증된 원본을 덮어쓰지 못하게 한다. 지난 업로드 행도 만료·고아 파일 정리를 마칠 때까지 보존한다.

클라이언트가 쓰는 임시 경로와 검증 완료 원본 경로를 분리한다. 검증 완료 파일은 서버만 쓰는 변경 불가 경로로 승격하거나 객체 저장소의 고정 버전 ID로 참조한다. `verified_object_version`은 버전 저장소를 사용할 때 필수다. 덮어쓸 수 있는 URL의 현재 파일을 그대로 학습 대상으로 삼지 않는다.

### label_reviews — 검수 도구 연결 시 추가

`review_id uuid PK`, `sample_id uuid FK`, `revision integer`, `decision text(accepted/rejected/uncertain)`, `reviewed_category_id text?`, `catalog_version text`, `reviewer_ref text`, `reviewed_at timestamptz`를 기록한다. `(sample_id, revision)`은 UNIQUE이며 sample 잠금 안에서 리비전을 증가시켜 최신 검수를 결정한다. accepted에는 유효한 검수 라벨이 필수다. 검수 변경은 새 이력으로 추가한다. 미검수는 행이 없는 상태이며 모델 예측·문제 정답을 검수 라벨로 자동 입력하지 않는다.

이 테이블과 검수 UI는 첫 게임 화면 연결에 필요하지 않다. 후속 데이터셋 생성 시 **verified 원본 + 사용 가능한 동의 + 삭제 대상 아님 + 최신 검수 accepted**를 모두 확인한다. 최초 수집 동의 정책도 사용할 학습 목적을 허용해야 한다. 모델 예측과 검수 라벨이 다를 때도 원래 예측은 보존한다.

## 4. 제출 트랜잭션 순서

격리 수준은 초기 `READ COMMITTED`, 잠금 순서는 **익명 세션 → 게임 진행 → 수집 표본**으로 통일한다. 세션 단위 직렬화는 초기 규모에서 단순함을 위한 선택이며 서로 다른 사용자를 막지 않는다. 실제 부하 측정 전 분산 잠금·Redis 카운터를 추가하지 않는다. PostgreSQL의 `SELECT ... FOR UPDATE`로 같은 행의 동시 변경을 직렬화한다. [공식 잠금 설명](https://www.postgresql.org/docs/17/explicit-locking.html)

1. HTTP 형식·수치 입력을 검사한다. 새 판정에 필요한 고정 artifact는 잠금 밖에서 캐시에 준비한다. 로딩 실패는 기존 확정 결과 조회를 막지 않으며, 새 판정이 필요한 경우에만 503을 반환한다. 파일 다운로드·외부 API·모델 학습을 DB 잠금 안에서 기다리지 않는다.
2. submissions service가 트랜잭션을 연다. 익명 세션을 잠그고 만료·소유권을 다시 확인한다.
3. `(session_id, puzzle_id)` 게임 행을 고유 제약과 함께 생성/조회하고 잠근다. 요청과 게임의 문제·릴리스 관계를 재확인한다.
4. 기존 request ID가 있으면 지문을 비교한다. 같으면 대표 결과와 최신 진행 상태를 반환하고, 다르면 409다. 기존 결과 재조회에는 신규 제출의 게임 종료 검사를 적용하지 않는다.
5. 새 request ID면 요청 버전의 유효성을 확인한다. 같은 그림 키가 있으면 별칭+지문을 저장하고 기존 결과를 반환한다. 게임이 이미 성공했어도 기존 그림 재사용은 허용한다.
6. 새 그림인데 게임이 성공했다면 409, 문제가 닫혔다면 410이다. 그 외에는 순수 판정 함수를 호출한다. 보류는 시도 수를 올리지 않는다.
7. 서버 대표 UUID를 발급하고 판정·계산 근거·최초 요청 매핑을 저장한다. 표본 선정 정책과 결과도 한 번 정해 기록한다. 실제 원본 업로드는 기다리지 않는다.
8. 유효 판정에만 현재 attempt_count+1을 배정한다. 제출 삽입과 게임의 횟수·최고 기록·성공 상태 변경은 같은 트랜잭션 안에서 처리한다.
9. commit 후 응답한다. commit 전 오류면 모두 rollback한다. 응답만 유실되면 같은 request ID 재전송으로 결과를 복구한다.

같은 그림의 동시 요청 두 개는 첫 요청이 commit한 뒤 두 번째가 기존 결과를 재사용한다. 각 repository나 하위 service에서 중간 commit하지 않는다. 일시적인 DB 충돌은 동일 요청으로 제한적으로 재시도하고, 결과를 확정하지 못한 상태를 deferred나 0점으로 저장하지 않는다.

요청 지문은 [API 계약 6절](api-contract-v1.md#6-중복-처리-계약)을 따른다. 결과를 보존하면서 요청 별칭만 먼저 삭제하면 재시도 보장이 깨지므로 게임 결과와 함께 보존·정리한다.

## 5. 업로드·철회와 DB/객체 저장의 경계

DB와 객체 저장소는 하나의 트랜잭션이 아니다. 이를 성공한 것으로 가정하지 않고 아래 상태를 재처리할 수 있게 남긴다.

- **권한 발급:** 세션 → sample을 잠근다. 최신 동의 리비전·소유권·선정·삭제 상태 확인 → sample/upload 행 확정 → 해당 시도에 한정된 업로드 권한 반환 순으로 처리한다. 재발급은 이전 시도 이력을 보존한다.
- **완료 확인:** 객체 읽기·형식/크기/획 해시·바이트 해시 검사는 긴 DB 잠금 밖에서 수행한다. 확인한 파일은 변경 불가 위치/객체 버전으로 확보한다. 이후 세션 → sample을 잠그고 최신 동의·active upload·삭제 상태를 다시 확인한 뒤에만 verified를 commit한다.
- **철회:** 같은 세션 잠금을 사용해 선택 리비전을 올리고 관련 sample을 delete_pending으로 전환한다. DB 상태부터 학습 대상에서 제외하고 실제 파일 삭제는 재처리 작업이 담당한다. 이미 발급된 URL의 늦은 쓰기를 승인된 수집으로 인정하지 않는다.
- **재처리:** worker는 upload 이력과 고정 경로 규칙으로 미완료/고아 파일을 찾아 검증·삭제한다. 검증 중 철회되어 승격 파일이 남더라도 사용 대상으로 편입하지 않고 삭제한다. 임시 저장소 만료 정책도 함께 둔다.
- **삭제 완료:** 임시 업로드 파일·검증 원본·생성한 파생 파일을 모두 정리한 뒤 deleted로 전환한다. 삭제용 추적 정보와 동의 이력의 보존 기간은 별도로 정한다. 파일 누락을 곧바로 게임 결과 삭제로 연결하지 않는다.

후속 학습은 데이터셋 생성 시점에 동의와 삭제 상태를 다시 확인한다. 데이터셋 사본의 삭제 추적도 향후 manifest 설계에 포함한다. 이미 학습된 모델의 처리 정책은 MLOps 도입 전에 별도로 정하며 초기 삭제 기능이 모델 재학습까지 수행한다고 안내하지 않는다.

## 6. 우선 인덱스와 구현 완료 조건

PK/UNIQUE가 제공하는 인덱스 외에는 아래 조회에 필요한 것부터 추가한다. 모든 JSONB에 미리 GIN 인덱스를 만들지 않는다.

| 조회 | 인덱스 후보 |
|---|---|
| 게임의 확정 기록 페이지 | submissions(game_session_id, attempt_number DESC), attempt_number가 NULL 아닌 행 |
| 만료 세션 정리 | anonymous_sessions(expires_at) |
| 세션별 수집 상태·철회 | drawing_samples(session_id, state) |
| 업로드 재처리 | drawing_samples(state, updated_at), drawing_uploads(state, expires_at) |
| 표본의 최신 검수 | UNIQUE(sample_id, revision) 인덱스의 역방향 조회 활용 |

완료 확인은 실제 PostgreSQL 통합 테스트로 한다. SQLite나 메모리 저장만으로 잠금·고유 제약을 확인한 것으로 간주하지 않는다.

1. 같은 요청 재전송, 같은 ID의 다른 본문, 다른 ID의 같은 그림, 별칭 ID 재사용을 구분한다.
2. 같은 그림의 동시 제출·서로 다른 그림의 동시 제출에서 횟수/시도 번호/성공이 일관된다.
3. commit 직전 실패는 부분 기록을 남기지 않고, commit 뒤 응답 유실은 같은 ID로 복구된다.
4. 보류·중복·오류에 시도 수가 늘지 않고 성공 전 API에 정답이 없다.
5. 철회와 업로드 완료가 겹쳐도 삭제 대상이 verified로 되살아나지 않는다.
6. 원본 검증 실패·업로드 만료·고아 파일 정리가 게임 점수와 성공을 바꾸지 않는다.

이번 단계의 [합성 fixture](../contracts/fixtures/submission-cases.json)는 위 계약을 설명하는 자료다. 실행 가능한 DB 테스트와 마이그레이션은 첫 백엔드 구현 단계에서 작성한다.
