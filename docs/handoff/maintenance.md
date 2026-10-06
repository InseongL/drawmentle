# 인수인계서 2 — 유지보수와 설정 변경

작성 2026-10-06. 다른 에이전트가 드로맨틀을 운영·수정할 때 필요한 구조, 실행·복구 절차, 설정을 안전하게 바꾸는 방법, 깨면 안 되는 약속을 정리했다. 모델 학습은 [인수인계서 1](model-training.md)을 본다.

## 0. 먼저 지킬 것 (사용자와 합의된 작업 방식)

- **요청 범위만 한다.** "준비만"이면 실행하지 않는다. 요청하지 않은 분석·학습을 늘리지 않는다.
- **확인 후에만**: 커밋, 푸시(커밋 승인과 별개로 다시 묻는다), 파일·패키지 다운로드(이름·출처·크기를 밝혀 묻는다), 학습 실행.
- **비밀값**: `.env.local`(GMS_KEY 등)은 읽거나 출력하지 않는다. `.env.example`만 추적한다.
- **정답 비공개**: 정답·문제 일정 시드는 DB에만 둔다. API는 성공 전 정답을 내보내지 않는다. 화면에도 AI 예측 단어·순위를 보여주지 않는다(사용자 결정).
- 저장소는 공개(비영리라 무방, 사용자 확인). 점수표 역산 우려를 다시 제기하지 않는다.
- 사용자는 한국어로 대화한다. 문서도 한국어로 쓴다.

## 1. 구조 한눈에

| 구성 | 위치 | 실행 |
|---|---|---|
| 화면 | `frontend/`(React 19 + Vite 8 + TS) | `npm --prefix frontend run dev` → http://127.0.0.1:5173. `/api`를 8000으로 프록시 |
| API | `backend/app/`(FastAPI, SQLAlchemy 2, Alembic) | `python -m uvicorn app.main:create_app --factory --app-dir backend --port 8000` |
| DB | PostgreSQL 17, Docker `drawmentle-local-db-1`, `127.0.0.1:5433` | `docker compose -f infra/local/docker-compose.yml up -d` |
| 릴리스 자료 | `data/artifacts/releases/<id>/`(공개 manifest만 추적, `private/`은 제외) | CLI `build-dev-release`·`build-model-release` |
| 모델 파일(개발) | `frontend/public/models/<modelVersion>/model.onnx`(Git 제외) | `build-model-release`가 복사, Vite가 `/models/...`로 제공 |
| 점수표 | `data/artifacts/scoring/scoring-v1/`(Git 제외) | `scripts/scoring/*.py` |
| 학습 | `model/`, 가상환경 `model/.venv` | 인수인계서 1 |

요청 한 번의 흐름: 화면이 세션·오늘 문제·공개 manifest를 받는다. 모델 릴리스면 브라우저가 모델을 받아 해시를 확인한다. 그림을 64px로 렌더해 추론하고, 후보별 확률을 합산한 Top-3를 보낸다. 서버는 릴리스 비공개 자료(점수표·판정 기준)로 판정하고 한 트랜잭션에 기록한다. 계약 상세는 [API 계약](../api-contract-v1.md)과 [DB 스키마](../database-schema-v1.md)다.

## 2. 실행과 재시작 (재부팅 뒤에 자주 필요)

이 PC는 재부팅되면 Docker Desktop과 개발 서버가 꺼진다. DB가 꺼진 채 통합 테스트를 돌리면 연결 타임아웃 뒤 "skipped"로 끝나므로 결과를 오해하기 쉽다.

```powershell
# Docker Desktop 시작 (꺼져 있을 때)
Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
```

```bash
docker compose -f infra/local/docker-compose.yml up -d
cd backend && python -m alembic upgrade head
```

- Claude Code 데스크톱의 미리보기 도구는 `.claude/launch.json`(Git 미추적)의 `backend`·`frontend` 설정으로 두 서버를 띄운다.
- 처음 받은 저장소에서는 점수표·릴리스 파일·모델 파일이 없다(Git 제외). 다음 순서로 만든다.
    1. `python scripts/scoring/extract_label_vectors.py`: fastText 스트리밍, 다운로드 승인 필요.
    2. `python scripts/scoring/build_score_table.py`
    3. `cd backend && python -m app.cli build-dev-release`
    4. `python -m app.cli schedule --days 30`
    5. 모델 릴리스는 인수인계서 1의 §5 순서로 만든다.

### 지금 개발 DB 상태 (2026-10-06)

| 릴리스 | 내용 | 배정된 문제 |
|---|---|---|
| `dev-release-v1` | 모델 없음(개발 패널), 영어 이름 없음 | 2026-09-24 ~ 09-26 |
| `dev-release-v2` | 모델 없음(개발 패널), 영어 이름 포함 | 2026-09-27 ~ 10-05 |
| `model-dev-e10-v1` | epoch 10 모델, T 1.036, 기준: 성공 p1 ≥ 0.9 / 보류 p1 < 0.15 | 2026-10-06(플레이돼서 남음) |
| `model-dev-e20-v1` | epoch 20 모델(최종), T 1.093, 기준: 성공 p1 ≥ 0.85 / 보류 p1 < 0.15 | **2026-10-07 ~ 11-04** |

문제 일정은 11-04까지다. 그 뒤에는 오늘 문제가 없어 화면에 "오늘의 문제가 아직 준비되지 않았어요"가 뜬다. 연장하려면 `python -m app.cli schedule --days 30 --release-id <릴리스>`를 쓴다(기본 릴리스는 `dev-release-v2`라 개발 패널 문제가 생긴다).

## 3. 설정 바꾸는 법

**대원칙: 등록된 릴리스와 열린 문제는 바꾸지 않는다.** 판정·점수·모델 무엇이 바뀌든 새 버전 → 새 릴리스 → 아직 안 열렸고 플레이되지 않은 문제에 배정한다. 릴리스 파일을 직접 고치면 해시 검사에서 막혀 그 릴리스의 새 판정이 503(`RELEASE_UNAVAILABLE`)이 된다.

### 3.1 판정 기준(성공·보류 확신도)

1. 기준 JSON을 만든다. 버전 이름은 새로 짓는다.
    ```json
    {"version": "recognition-e20-relaxed-v1", "status": "dev-only", "min_top1_p": 0.15, "min_top3_sum": null,
     "min_known_axes": 1, "success_min_p": 0.7, "success_min_margin": null}
    ```
2. `cd backend && python -m app.cli build-model-release --release-id model-dev-e20-v2 --model-dir ../data/artifacts/models/mobilenet_v3_small-20261001-093849-e20 --recognition <JSON 경로>`
3. `python -m app.cli assign-release --release-id model-dev-e20-v2`. 오늘 문제가 아직 플레이되지 않았으면 `--include-open-unplayed`(개발 전용)를 붙인다.

- 개발 패널 릴리스의 기준은 `config/scoring/recognition.json`(`recognition-dev-v0`)이고 `build-dev-release`가 읽는다.
- 기준 판단 근거는 `model.evaluation.calibrate`의 기준표, [인수인계서 1 §6](model-training.md)의 epoch 20 기준표, [판정 기준 §4.1](../judging-criteria-v1.md)(epoch 10 기준)이다. 개발 릴리스는 보정 초안(잘못된 성공 ≤ 5% → τ 0.85)을 쓰기로 했다(2026-10-06). 운영용 목표는 아직 정하지 않았다.

### 3.2 점수(유사도) 규칙

- 설정은 `config/scoring/scoring.json`(축 가중치, IDF, 계열 부분 점수, 연상 보정), 근거는 [점수 계산 규칙](../scoring-v1.md)이다.
- 바꿀 때는 `version`과 `output_dir`을 새로 정하고(예: `scoring-v2`), `build_score_table.py` → `check_score_table.py`로 무결성과 데일리 후보의 가까운 카테고리를 확인한다.
- **함정**: `backend/app/cli.py`의 `SCORE_TABLE_DIR`가 `data/artifacts/scoring/scoring-v1`로 고정돼 있다. 새 점수 버전으로 릴리스를 만들려면 이 경로를 바꾸거나 인자로 받게 고쳐야 한다.
- 점수만 바꿀 때는 모델을 다시 학습하지 않는다(기획서 원칙).

### 3.3 카테고리(통합·데일리 후보)

- 설정은 `config/model/catalog-curation-v1.json`, 근거는 [카테고리 정리](../catalog-curation-v1.md)다. 대표 ID 합산, 미지원 `bird`, 데일리 후보 여부를 담는다.
- 데일리 후보에서만 빼는 일(`daily_candidate`)은 비교적 가볍다. 버전을 올린 뒤 새 릴리스와 `schedule`로 반영한다. 이미 잡힌 문제의 정답은 `set-answer`로 바꿀 수 있다(플레이 전만).
- 통합(service_id)을 바꾸면 후보 목록·점수표 ID·브라우저 합산이 모두 바뀐다. 카탈로그 버전, 점수표, 새 릴리스를 함께 다시 만든다. 모델 출력 345개는 그대로라 재학습은 필요 없다.

### 3.4 문제 일정·정답 (개발)

`cd backend` 후 `python -m app.cli <명령>`으로 쓴다.

| 명령 | 하는 일 |
|---|---|
| `list-puzzles` | 날짜·ID·상태·릴리스만 보여줘요(정답 없음) |
| `schedule --days N [--release-id]` | 시드를 저장하지 않는 무작위 일정 |
| `set-answer 날짜 카테고리` | 플레이된 문제는 거부 |
| `show-answer 날짜` | 개발 전용. 정답이 출력되니 사용자에게 스포일러임을 알린다 |
| `assign-release` | 미래 문제(또는 오늘 미플레이 문제)의 릴리스 교체 |

### 3.5 화면 문구·언어

- 모든 문구는 `frontend/src/shared/i18n/messages.ts` 한 곳에 있다. 한국어(`ko`)를 고치면 영어(`en`)도 같은 항목을 고친다. 타입과 `tests/unit/i18n.test.ts`가 빠진 항목을 잡는다.
- 서버 오류 문구는 서버 메시지가 아니라 오류 코드로 사전에서 찾는다(`errors`). 새 오류 코드를 만들면 두 언어에 추가한다.
- 카테고리 영어 이름은 릴리스 manifest의 `displayNameEn`에서 온다(v1 릴리스는 ID로 대체).

### 3.6 서버 환경 변수 (`backend/app/core/settings.py`)

| 변수 | 기본 | 비고 |
|---|---|---|
| `APP_ENV` | `development` | `production`이면 개발 DB URL·보안 안 된 쿠키를 거부하고, 개발 전용 CLI를 막는다 |
| `DATABASE_URL` | `postgresql+psycopg://drawmentle:drawmentle-dev@127.0.0.1:5433/drawmentle` | 로컬 전용 비밀번호 |
| `SESSION_COOKIE_NAME` / `SESSION_TTL_DAYS` | `dm_session` / 30 | |
| `COOKIE_SECURE` | 운영에서만 true | |
| `ALLOWED_ORIGINS` | `http://127.0.0.1:5173,http://localhost:5173` | 쉼표 구분. 변경 요청의 Origin 검사 |
| `ARTIFACT_ROOT` | 저장소 루트 | 릴리스 비공개 파일 경로 기준 |

### 3.7 DB 스키마

마이그레이션은 Alembic `backend/migrations/versions/0001_game_tables.py` 하나다. 바꿀 때는 `backend/app/db/models.py` 수정 → `cd backend && python -m alembic revision --autogenerate -m "..."` → 생성된 파일 검토 → `upgrade head` → `python -m alembic check`(차이 없음 확인). game_sessions와 submissions는 서로 참조하므로(최고·성공 제출) 외래 키를 테이블 생성 뒤에 따로 만든다.

## 4. 깨면 안 되는 동작 (테스트가 지키는 것)

- 같은 요청 ID를 다시 보내면 같은 결과를 돌려준다. 같은 ID에 다른 본문이면 409. 같은 그림을 다시 내면 기존 결과를 재사용한다. 보류된 제출은 시도 수에 넣지 않는다. 성공 후 새 그림은 409(`GAME_ALREADY_SOLVED`)다.
- 세션 잠금 → 게임 잠금 순서로 한 트랜잭션 안에서 처리한다. 동시 제출에도 시도 번호가 겹치지 않는다.
- 릴리스 자료에 문제가 있으면 새 판정만 503으로 막고, 이미 확정된 결과 조회는 된다.
- 브라우저와 파이썬의 64px 렌더가 바이트 단위로 같다(공통 사례 파일).
- 브라우저 Top-3는 345개 출력 전체에 softmax(logits / T)를 적용한 뒤 대표 ID별로 합산한다. 미지원 후보도 빼지 않는다. 확률이 같으면 candidate_index가 작은 쪽이 앞이다(서버가 다른 순서를 거부한다).

## 5. 테스트

| 묶음 | 명령 (저장소 루트) | 비고 |
|---|---|---|
| 백엔드 단위 | `python -m unittest discover -s backend/tests/unit` | 판정·점수 |
| 백엔드 통합 | `python -m unittest discover -s backend/tests/integration` | **Docker DB 필요**. `drawmentle_test` DB를 자동 생성. 합성 사례 14개, 동시성, 릴리스 빌더, 지표 |
| 점수표·카탈로그 | `python -m unittest discover -s tests` | |
| 모델 | `model/.venv/Scripts/python -m unittest discover -s model/tests -t .` | `DATASET_VERSION=qd-10k-64-v1`로 본 데이터셋 계약 검사(약 1분) |
| 프론트 | `npm --prefix frontend test`, `npm --prefix frontend run build` | 27개 + 타입 검사 |

통합 테스트 중 "unhandled error" 출력은 의도된 실패 주입 테스트의 로그다. 학습 수집 업로드 사례 1개는 수집 기능이 꺼져 있어 건너뛴다.

## 6. 운영 관찰

`cd backend && python -m app.cli metrics --days 7`(또는 `--json`)로 날짜·릴리스별 다음 지표를 본다. 정답은 출력하지 않는다.
- 판 수, 제출 수, 보류율(사유별), 성공률
- 성공까지 걸린 시도 수(중앙값), 평균 1위 확신도
- 1위 쏠림(가장 많이 나온 1위 후보의 비율)

모델을 바꾼 뒤 보류율이나 1위 쏠림이 튀면 릴리스를 의심한다. 되돌릴 때는 아직 안 열린 문제를 이전 릴리스로 `assign-release`한다. 자동 재학습·자동 배포는 하지 않는다(MLOps 원칙: 단계마다 사람이 확인).

## 7. 알려진 문제와 함정

- **노트북 전원**: 배터리면 GPU가 크게 느려진다(학습). 덮개를 닫거나 절전하면 학습이 멈춘다.
- **미리보기 도구 캡처**: 앱 창이 다른 창 뒤에 있으면 스크린샷·클릭이 시간 초과된다. 페이지 텍스트 읽기와 스크립트로 대신 확인한다. 화면 비율이 1.5배로 잘려 보일 때도 있다.
- 프론트 `npm install` 때 protobufjs postinstall 경고(allow-scripts)가 나지만 동작에는 영향이 없다.
- `onnxruntime-web`은 단일 스레드 WASM(14MB)이다. 여러 스레드를 쓰려면 페이지에 COOP/COEP 헤더가 필요하다. 실행 엔진은 모델 릴리스일 때만 지연 로딩된다.
- 운영 배포(HTTPS, 정적 파일·모델 CDN, 운영 DB)는 아직 설계만 있다. 개발 서버는 127.0.0.1에서만 받는다. 실제 휴대폰 테스트에는 HTTPS 환경이 필요하다(그림 해시 계산에 보안 컨텍스트 필요).
- 학습용 그림 수집(동의·업로드·검수)은 미구현이다(`collection-disabled-v0`). Q&A에만 안내한다.

## 8. 커밋 상태와 남은 일

- 마지막 코드 커밋 `61a46d9`: 모델 학습·평가·ONNX 도구, 브라우저 추론, 모델 릴리스 CLI, 인수인계서. 그 뒤로는 epoch 20 결과에 맞춰 문서만 고쳤다. 본 학습 완료와 `model-dev-e20-v1` 등록·배정은 Git 제외 산출물과 개발 DB에만 있다.
- 커밋·푸시는 사용자 확인 후에만 한다.
- 남은 일과 결정
    - 운영용 판정 기준 목표, 어려운 데일리 정답 처리, 테스트 분할 평가 시점: 인수인계서 1 §7
    - 10-07 문제가 열리면 실제 게임 화면에서 epoch 20 판정 흐름 확인(브라우저 단독 비교는 끝남, 인수인계서 1 §5)
    - 점수표 경로 하드코딩 정리(§3.2)
    - 운영 배포 설계와 수집 기능
