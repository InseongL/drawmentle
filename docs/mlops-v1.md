# MLOps v1 — 수집에서 재학습·배포·관찰까지

기준: [기획서 v3.2](<../AI 스케치 게임 서비스 기획서 v3.2.md>) §11, [서비스 아키텍처](service-architecture-v1.md) §10·§16, [DB 스키마](database-schema-v1.md) §3·§5, [API 계약](api-contract-v1.md) §8, [인수인계서 1](handoff/model-training.md). 작성일: 2026-10-06. 상태: **구조 완성, 수집은 꺼져 있음**(`config/collection/collection.json`의 `enabled: false`).

실제 사용자 그림으로 모델을 다시 학습하고, 지금 모델과 비교해 나을 때만 교체하는 흐름이다. 모든 단계는 사람이 명령을 실행하고 결과를 확인한다. **자동 학습·자동 배포는 하지 않는다.** 운영값(표본 비율, 보관 기간, 교체 기준, 경고 기준, 재학습 권고 조건 등)은 모두 설정 파일에 있고 코드 변경 없이 조정한다.

## 1. 한눈에 보기

```
게임 화면: 학습용 제공 동의(선택) ─┐
제출: 표본 선정(동의와 무관, 1회) ──┴→ 업로드 → 파일 확인(verified) → 검수(사람이 라벨) → 내보내기
                                                                                           │
관찰(metrics --check, mlops-status) ← 퍼즐 배정(사람) ← 릴리스 ← ONNX 확인 ← 비교·교체 기준 ← 보정·평가 ← 재학습 ← 데이터셋
```

| 단계 | 명령 (backend는 `cd backend`) | 결과 | 사람이 확인할 것 |
|---|---|---|---|
| 동의·업로드 | 게임 화면이 자동으로 처리 | `drawing_samples` verified | 수집을 켜기 전 8절 결정 |
| 정리 | `python -m app.cli collection-reconcile` (주기 실행) | 만료·보관 기간·철회 파일 삭제 | 출력의 `datasets_with_deleted_drawings` |
| 검수 | `python -m app.cli review-export` → items.csv 작성 → `review-import <csv> --reviewer <이름>` | `label_reviews` | 라벨 품질 |
| 상태 | `python -m app.cli mlops-status` | 표본·검수 수, 재학습 권고 | 권고 이유 |
| 내보내기~릴리스 | `python -m model.pipelines.retrain --new --until <단계>` | 파이프라인 기록 | 단계별 보고서, 특히 비교 보고서 |
| 배정 | `python -m app.cli assign-release --release-id <새 릴리스>` | 새 퍼즐부터 새 모델 | 비교 보고서·브라우저 확인 |
| 관찰 | `python -m app.cli metrics --check` | 경고 목록(종료 코드 2) | 경고 원인 |

## 2. 운영 설정

### 2.1 수집 — `config/collection/collection.json` (서버 재시작 후 적용)

| 키 | 기본값 | 뜻 |
|---|---|---|
| `enabled` | `false` | 수집 기능 전체. 꺼져 있으면 동의 화면이 없고 제출은 `collection-disabled-v0`·`not_selected`로 기록된다 |
| `notice_version` | `collection-notice-v1-draft` | 사용자가 동의하는 안내 버전. 안내를 고치면 올리고, 이전 동의자는 다시 동의해야 새 버전으로 기록된다 |
| `training_notice_versions` | 위와 같음 | 학습에 써도 되는 안내 버전 목록. 내보내기가 이 목록으로 거른다 |
| `sampling.version` | `sampling-v1` | 표본 선정 규칙 버전. 비율을 바꾸면 올린다(제출에 기록) |
| `sampling.success_rate` / `failure_rate` / `deferred_rate` | 1.0 / 0.2 / 0.0 | 정답 그림 / 인식됐지만 오답 그림 / 보류 그림을 표본으로 고르는 비율 |
| `upload.*` | 600초, 64 KiB, 획 64, 획당 점 1,024, 점 4,096 | 업로드 권한 유효 시간과 그림 크기 한도 |
| `retention.verified_days` | 365 | 확인된 그림 보관 기간(0이면 무제한). 지나면 정리 작업이 삭제 |
| `retention.temp_hours` | 24 | 임시 파일 기준 시간 |
| `retention.derived_datasets` | `report` | 삭제된 그림이 든 사용자 데이터셋: `report`는 목록만, `delete`는 지움 |
| `storage.backend` / `root` | `local` / `data/collected/objects` | 원본 저장소. 운영은 객체 저장소 구현이 필요(8절) |
| `review.show_model_prediction` / `show_puzzle_answer` | true / false | 검수 화면 참고 정보. 라벨로 자동 채우지 않는다 |
| `export.group_salt` | `drawmentle-export-v1` | 내보내기에서 세션을 가리는 해시 소금 |

### 2.2 재학습·관찰 — `config/mlops/mlops.json`

| 묶음 | 주요 키 | 뜻 |
|---|---|---|
| `runtime` | `model_python`, `backend_python`, `pipelines_dir` | 파이프라인이 단계마다 부르는 파이썬과 기록 위치 |
| `champion` | `run`, `checkpoint`, `release_id` | 지금 게임에 붙은 모델. 교체하면 바꾼다 |
| `dataset` | `base_version`, `user_split`(0.7/0.15/0.15), `split_salt`, `train_repeat`(4), `min_accepted_per_label` | Quick Draw 기준 데이터셋, 사용자 그림 분할 비율, 학습 때 사용자 그림 반복 횟수 |
| `training` | `init`(`warm_start`/`scratch`), `epochs`(5), `lr`(3e-4), `warmup_epochs`, `placement` | 재학습 방식 |
| `gates` | 아래 6.2 | 교체 기준 |
| `monitoring` | 아래 7 | `metrics --check` 경고 기준 |
| `retrain_triggers` | `min_new_accepted`(2,000), `max_days_since_training`(90), `min_accepted_for_time_trigger`(200) | `mlops-status`가 재학습을 권할 조건 |
| `release` | `id_prefix`(`model-user`) | 새 릴리스 ID 앞부분 |

## 3. 수집

### 3.1 흐름

1. **동의**(`PUT /api/collection-consent`): 그림판 아래 체크박스(기본 해제, 제출 버튼과 분리). 바꿀 때마다 리비전이 1 오르고 `collection_consents`에 이력이 쌓인다. 같은 값을 다시 보내면 그대로 돌려준다. 다른 값이 오래된 리비전으로 오면 409 `CONSENT_REVISION_CONFLICT`.
2. **표본 선정**: 제출마다 한 번, 동의와 무관하게 `sha256(sampling.version:submissionId)`로 정해 제출 행에 기록한다. 같은 그림 재시도에서 다시 뽑지 않는다.
3. **업로드**(`POST /api/submissions/{id}/drawing-upload` → `PUT` 권한 URL → `POST .../drawing-complete`): 화면은 동의한 상태에서 낸 제출의 **고정 사본**(제출 때 해시를 만든 바로 그 JSON)을 브라우저에 잠시 보관했다가 결과가 나오면 조용히 보낸다. 실패해도 게임에는 영향이 없고 다음 방문 때 한 번 더 시도한다.
4. **확인**: 서버가 파일을 읽어 형식·한도·정규화된 직렬화를 확인하고 SHA-256이 제출의 그림 해시와 같을 때만 `verified/<sample>/<sha>.json`에 덮어쓸 수 없게 복사한다. 그다음 세션 → 표본 → 업로드를 잠그고 동의를 다시 확인해야 `verified`가 된다. `verified`는 파일 확인이지 라벨 검수가 아니다.
5. **철회**: 체크를 해제하면 그 세션의 모든 표본이 즉시 `delete_pending`(학습 제외)이 되고, 정리 작업이 파일을 지운 뒤 `deleted`가 된다. 다시 동의해도 지운 표본은 돌아오지 않는다.

### 3.2 상태

`drawing_samples.state`: `pending_upload → uploaded → verified`, 실패 `upload_failed`(다시 권한을 받아 재시도), 삭제 `delete_pending → deleted`. 응답의 `collection.state`는 여기에 `not_consented`·`not_selected`·`eligible`(동의·선정됐지만 아직 표본 없음)을 더한 9가지이고 삭제 상태가 우선한다. 세션 응답에서는 `eligible`이 "동의함"이다.

### 3.3 정리 작업 (`collection-reconcile`)

하루 한 번 이상 실행한다(작업 스케줄러 등). 하는 일:
1. 만료된 업로드 권한을 `expired`로, 그 표본을 `upload_failed`로 바꾸고 임시 파일을 지운다.
2. `verified_days`가 지난 표본을 `delete_pending`으로 바꾼다.
3. `delete_pending` 표본의 임시·확인 파일을 모두 지우고 `deleted`로 바꾼다.
4. 주인 없는 임시 파일과, 어떤 표본도 가리키지 않는 확인 파일을 지운다.
5. 삭제된 그림이 든 **파생 사본**을 정리한다: 검수 묶음·내보내기 폴더는 지우고, 사용자 데이터셋은 `derived_datasets`에 따라 지우거나 목록만 보고한다(학습 run의 재현성과 삭제 요구 중 사람이 고른다).

## 4. 검수

`review-export`가 확인된 미검수 그림을 `data/collected/review/<batch>/`에 쓴다: `index.html`(그림 SVG와 참고 정보), `items.csv`, `categories.csv`(원본 345개 ID와 이름), `batch.json`. 검수자는 `decision`(accepted / rejected / uncertain)과, accepted면 `category_id`(원본 ID, 예: 머그잔은 `mug`)를 채운다. `review-import`는 모든 줄을 먼저 확인하고 하나라도 틀리면 아무것도 쓰지 않는다. 검수는 덧붙이기만 하고(`revision` 증가) 고치지 않는다. 마지막 결정이 accepted인 그림만 학습에 쓴다. 모델 예측과 퍼즐 정답은 라벨로 자동 채우지 않는다. `uncertain`은 `--include-uncertain`으로 다시 볼 수 있다.

## 5. 내보내기와 데이터셋

- **내보내기**(`collection-export`, 파이프라인 1단계): 확인됨 + 지금도 동의 중 + 수집 당시 안내가 `training_notice_versions`에 있음 + 삭제 대상 아님 + 마지막 검수 accepted인 그림만 `data/collected/exports/<id>/samples.jsonl`로 쓴다. 세션은 소금 친 해시(`group`)로만 남고, `manifest.json`에 표본 ID 전체가 있어 나중에 삭제를 추적한다.
- **사용자 데이터셋**(`model.datasets.build_user_dataset`): Quick Draw와 같은 `qd-strokes-64-v1` 렌더로 64px 이미지를 만든다. 분할은 `sha256(split_salt:group)`이라 한 사람의 그림은 한 분할에만 들어간다. **사용자 test 분할은 실제 그림판 평가셋**으로, 학습에 쓰지 않는다.
- **결합 데이터셋**(`model.datasets.compose`): `<base>+user-<id>`는 매니페스트만 있는 폴더다. 학습·평가가 기준 데이터셋(14GB)과 사용자 데이터셋을 제자리에서 함께 읽고, 학습 분할에서만 사용자 그림을 `train_repeat`번 반복한다.

## 6. 재학습 파이프라인 (`model.pipelines.retrain`)

### 6.1 단계

| 단계 | 하는 일 | 실패·중단 조건 |
|---|---|---|
| `export` | `collection-export` | 내보낼 그림이 0장 |
| `dataset` | 사용자 데이터셋 + 결합 데이터셋 | 라벨이 카탈로그에 없음, 같은 버전이 이미 있음 |
| `train` | 결합 데이터셋으로 학습. `warm_start`면 챔피언 가중치에서 시작(`--init-from`) | 학습 오류 |
| `calibrate` / `evaluate` | 온도·기준 초안, 평가 보고서 | |
| `compare` | 챔피언과 같은 자료로 비교, 교체 기준 판정 | 결과는 기록만 하고 release에서 판단 |
| `export_onnx` / `check_onnx` | ONNX와 PyTorch 결과 일치 확인 | 최대 오차 > `max_onnx_diff` |
| `release` | `build-model-release --release-id <prefix>-<pipeline id>` | `--approve-release` 없음, 기준 불합격(사유를 적은 `--override-gates`만 예외로 기록) |

- 기록: `data/artifacts/mlops/pipelines/<id>/pipeline.json`(설정 사본과 해시, 단계별 상태·시각·출력, 기준 무시 사유)과 단계별 로그. 끝난 단계는 다시 하지 않고, 실패한 단계는 원인을 고친 뒤 `--resume`으로 이어 한다. `--dry-run`은 남은 명령만 보여준다.
- `--until`은 필수다. 학습은 `--until train` 이상을 명시해야만 돈다.
- **퍼즐 배정은 하지 않는다.** 끝나면 `assign-release` 명령과 챔피언 갱신 방법을 출력한다. 되돌리기는 이전 릴리스로 다시 `assign-release`.

### 6.2 교체 기준 (`gates`, `model.evaluation.compare`)

두 모델 모두 각자의 보정 온도를 쓰고 같은 성공 기준(후보의 보정 초안)으로 비교한다. 기준 자료는 기준 데이터셋 검증 분할의 모델 선택용 절반(`eval_subset`)과 사용자 test 분할이다.

| 기준 | 기본값 | 통과 조건 |
|---|---|---|
| `top1` | `max_top1_drop` 0.002 | 후보 top-1 ≥ 챔피언 − 0.002 |
| `false_success` | `max_false_success` 0.05 | 후보 잘못된 성공 ≤ 5% |
| `daily_floor` | `daily_floor_rate` 0.05, `max_daily_below_floor` 0 | 한 장 성공률 5% 미만 데일리 정답 0개 |
| `answer_regression` | `max_answer_regression` 0.10 | 어떤 데일리 정답도 성공률이 10%p 넘게 떨어지지 않음 |
| `user_top1` | `min_user_eval_samples` 200, `min_user_top1_gain` 0.0 | 실제 그림판 그림에서 top-1이 챔피언 이상. 그림이 200장 미만이면 **보류**(막지 않음) |
| ONNX | `max_onnx_diff` 0.001 | `check_onnx` 통과 |

보고서는 `<후보 run>/eval/compare-<챔피언 run>/report.md`. 2026-10-06 챔피언을 자기 자신과 비교해 도구를 확인했다(모두 통과, 사용자 기준은 보류).

## 7. 관찰

`metrics --check`는 하루·릴리스별 지표를 `monitoring` 기준과 비교해 경고하고 종료 코드 2를 낸다(판 수가 `min_games` 미만인 날은 건너뜀).

| 기준 | 기본값 | 경고 뜻 |
|---|---|---|
| `max_deferral_rate` | 0.10 | 보류가 많다: 인식 기준(τ_인식)이나 모델 문제 |
| `min_solve_rate` | 0.20 | 게임당 정답률이 낮다 |
| `max_near_miss_share` + `near_miss_p1` | 0.50, 0.70 | 1위는 정답인데 기준에 못 미친 제출이 많고 그 확신도가 높다: τ_성공이 엄격할 수 있다 |
| `max_top1_concentration` | 0.30 | 한 후보가 1위를 독차지: 모델·릴리스 이상 |

`mlops-status`는 표본 상태, 검수 결과, 내보낼 수 있는 그림 수, 마지막 내보내기 이후 새 그림 수, 챔피언 학습 후 지난 날짜를 보여주고 `retrain_triggers`로 재학습을 권할지 알려준다. 권하기만 하고 아무것도 실행하지 않는다.

## 8. 수집을 켜기 전에 정할 것

1. **안내 문구와 법적 검토**: 화면 문구·Q&A는 초안이다(`collection-notice-v1-draft`). 확정하면 `notice_version`을 올린다. 개인정보 처리방침, 연령 기준이 없다.
2. **보관 기간**(`verified_days`), **실패 그림 표본 비율**(`failure_rate`), 삭제 추적 정보·동의 이력 보관 기간.
3. **운영 저장소**: 지금은 로컬 파일(`local`)이다. 운영은 비공개 객체 저장소(S3 호환, 미리 서명한 URL) 구현을 `app/storage/object_store.py`의 같은 인터페이스로 추가해야 한다.
4. **검수자와 검수 도구**: 지금은 HTML+CSV 묶음이다. `reviewer_ref`에 누구를 적을지 정한다.
5. **이미 학습된 모델의 처리**: 철회한 그림은 이후 데이터셋에서 빠지지만 이미 학습된 모델에서 지워지지는 않는다(화면 Q&A에 명시).
6. **그림 크기 한도**(`upload.*`) 확정, 사용자 획 간소화 여부.
7. 정리 작업(`collection-reconcile`)과 관찰(`metrics --check`)의 정기 실행 방법.

## 9. 검증 기록 (2026-10-06)

- 테스트: 백엔드 단위 21개, 통합 27개(수집 14개 포함, 실제 PostgreSQL), 모델 17개(사용자 데이터셋·결합 데이터셋·교체 기준·파이프라인·warm start 학습 포함), 프론트 32개.
- 계약 fixture의 수집 사례(`upload_failure_preserves_solved_game`)는 이전에 건너뛰었는데 이제 실제로 돈다.
- 브라우저 확인(개발 DB, 수집을 잠시 켜고): 동의 → 그림 제출 → 업로드 → `verified`(브라우저가 만든 파일 해시 = 제출 그림 해시) → `mlops-status`·`review-export` → 동의 해제 → `collection-reconcile`로 파일·검수 묶음 삭제. 확인 후 설정을 다시 껐다.

## 10. 관련 파일

| 파일 | 역할 |
|---|---|
| `config/collection/collection.json`, `config/mlops/mlops.json` | 운영 설정 |
| `backend/migrations/versions/0002_collection_tables.py` | 수집·검수 테이블 |
| `backend/app/modules/collections/` | 동의·선정·업로드·확인(`service.py`), 그림 검사(`drawing.py`), 검수(`review.py`), 내보내기(`export.py`) |
| `backend/app/storage/object_store.py` | 원본 저장소 인터페이스와 로컬 구현 |
| `backend/app/workers/collection_reconcile.py` | 정리 작업 |
| `backend/app/cli.py` | `collection-reconcile`, `review-export`, `review-import`, `collection-export`, `mlops-status`, `metrics --check` |
| `frontend/src/features/collection/` | 동의 체크박스, 업로드 흐름 |
| `model/datasets/build_user_dataset.py`, `compose.py` | 사용자·결합 데이터셋 |
| `model/evaluation/compare.py` | 챔피언 비교와 교체 기준 |
| `model/pipelines/retrain.py` | 재학습 파이프라인 |
| `backend/tests/integration/test_collections.py`, `backend/tests/unit/test_mlops.py`, `model/tests/test_mlops.py`, `frontend/tests/integration/drawingUpload.test.ts` | 테스트 |
