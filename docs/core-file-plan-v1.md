# 핵심 기능 파일 계획 v1

기준: [폴더 구조](folder-structure-v1.md), [서비스 아키텍처](service-architecture-v1.md), [기획서 v3.2](<../AI 스케치 게임 서비스 기획서 v3.2.md>). 작성일: 2026-09-22.

이 문서는 **파일명과 기능의 계획**이다. 후속 작업으로 `App.tsx`, `DrawingCanvas.tsx`, `drawingState.ts`, `drawingSnapshot.ts`와 실행 설정을 생성해 [그림판 단독 데모](../frontend/README.md)를 구현했다. 나머지 게임·모델·백엔드 파일은 계획 단계이며 기존 도구·합성 fixture는 별도 표시했다. 초기 기능의 소유 파일을 정해 같은 기능을 여러 곳에 만들거나 임의의 보조 파일을 계속 추가하는 일을 줄인다. 패키지·빌드 설정, 세부 디자인 컴포넌트, `__init__.py` 같은 실행 보조 파일은 이 목록의 대상이 아니다.

모듈 간 참조는 [폴더 구조의 의존성 방향](folder-structure-v1.md#의존성-방향), 구체적인 입력·저장은 [API 계약](api-contract-v1.md)과 [DB 스키마](database-schema-v1.md)를 기준으로 한다. 계획된 파일을 빈 상태로 한꺼번에 생성하지 않는다.

## 1. 프론트 핵심 파일

경로 기준: `frontend/src/`.

화면 배치·반응형·기록·Q&A 규칙은 [프론트 화면 계획](frontend-plan-v1.md)을 따른다. 모바일과 데스크톱을 초기 지원하며 기존 폴더 안에서 구성한다.

| 파일 | 담당 기능 |
|---|---|
| `app/App.tsx` | 앱 초기화와 게임 화면 연결. 공통 상태·오류 표시의 최상위 경계 |
| `features/drawing/DrawingCanvas.tsx` | 포인터 입력을 획으로 수집하고 Canvas에 그리기. 전달받은 편집 잠금 상태 반영 |
| `features/drawing/drawingState.ts` | 현재 획·펜·캔버스 상태, Undo·Reset·변경 여부 관리. 제출 기록은 별도로 유지 |
| `features/drawing/drawingSnapshot.ts` | 제출 순간의 변경 불가능한 사본, 규격에 맞는 직렬화·해시·썸네일 생성 |
| `features/inference/modelRuntime.ts` | 릴리스에 맞는 ONNX/WASM 로딩·캐시·추론 실행·해제. 전체 원본 출력 보정·softmax 후 대표 ID별 확률 합산, 미지원 후보와 확률을 유지한 Top-3 반환. 동점은 candidate_index 순 |
| `features/inference/preprocess.ts` | 획 사본을 모델 입력 텐서로 변환. 크기·정렬·굵기·극성·축 순서를 고정 명세에 맞춤 |
| `features/inference/inference.worker.ts` | 모델 로딩·전처리·추론을 UI 스레드와 분리하는 메시지 경계. 요청 ID로 결과와 오류 연결 |
| `features/game/GamePage.tsx` | 문제·그림판·조작 버튼·상태·수집 선택·성공 결과·기록·하단 Q&A를 한 열로 배치하는 플레이 화면 |
| `features/game/useGame.ts` | 문제/릴리스 고정, 시작·복원·판정 보류·성공 상태 관리. UI에서 호출할 게임 동작 제공 |
| `features/game/submissionFlow.ts` | 제출 사본 생성 → 로컬 추론 → API 제출 → 결과 반영을 조정. 중복 클릭·재시도·제출 중 편집 잠금 처리 |
| `features/game/SubmissionHistory.tsx` | 서버 시도 번호·고정 썸네일·유사도의 최신순 기록. 최고·정답 표시, 이전 기록 더 보기, 그림판 복귀 링크 |
| `features/game/ResultPanel.tsx` | 서버가 확정한 성공과 정답·총 시도 수·성공 그림 표시 |
| `features/game/GameFaq.tsx` | 게임 방법·유사도·판정 보류·기록·학습용 제공에 관한 하단 설명과 이용 방법 앵커 |
| `features/game/game.css` | 게임 화면 한 열 레이아웃과 모바일/데스크톱 그림판·버튼·기록·Q&A 스타일 |
| `features/collection/CollectionConsent.tsx` | 학습용 그림 보관 선택과 안내 버전 표시. 현재 선택을 게임 판정과 분리해 전달 |
| `features/collection/drawingUpload.ts` | 선택·선정된 제출의 업로드 권한 요청, 사본 업로드·완료 통지·재시도. 실패해도 게임 결과 유지 |
| `shared/api/client.ts` | 세션·문제·제출·진행 복원·수집 API 호출과 공통 오류 변환. 제출 재시도 시 같은 ID 사용 |
| `shared/storage/gameStorage.ts` | 문제별 획·썸네일·진행 상태·미완료 제출 ID 보관. 서버 결과와 로컬 복원 상태 구분 |

`useGame`은 화면 상태, `submissionFlow`는 한 번의 제출 절차, `client`는 HTTP 전송을 담당한다. 세 곳에 판정 규칙을 중복 구현하지 않는다. 같은 그림인지 판단할 때 화면 썸네일이 아닌 제출 사본의 해시 규격을 사용한다.

Worker는 `modelRuntime`과 `preprocess`를 호출하는 통로이며 자체 판정 수식을 갖지 않는다. 초기 구현에서 Worker를 사용하지 않더라도 동일한 런타임·전처리 함수를 직접 호출할 수 있게 한다. 서버가 반환한 점수를 프론트에서 다시 계산하지 않는다.

게임 화면 스타일은 `features/game/game.css`에 모은다. 공통 UI·스타일의 세부 파일은 실제 재사용할 요소가 생길 때 정한다. 모델 캐시도 초기에는 `modelRuntime`이 책임지고 별도 캐시 서비스 파일을 추가하지 않는다.

## 2. 백엔드 핵심 파일

경로 기준: `backend/app/`.

### 실행 기반과 저장

| 파일 | 담당 기능 |
|---|---|
| `main.py` | FastAPI 앱 구성, 라우터 연결, 시작·종료 시 DB·릴리스 자원 준비 |
| `core/settings.py` | 서버 환경 변수·실행 설정 읽기. 개발/운영 구분과 저장소 설정 검증 |
| `core/errors.py` | 버전 불일치·중복 본문 충돌·소유권 오류 등 공통 오류 코드와 HTTP 응답 변환 |
| `db/session.py` | DB 연결과 요청/작업별 DB 세션 수명 관리. 제출 트랜잭션의 업무 범위는 제출 서비스가 결정 |
| `db/models.py` | 릴리스·문제·익명 세션·진행·대표 제출·요청 별칭·계산 내역 정의. 수집 단계에서 동의 이력·표본·업로드 시도, 검수 단계에서 라벨 이력 추가 |
| `storage/object_store.py` | 파일 저장·조회·해시 확인·업로드 권한에 필요한 공통 인터페이스 |
| `storage/local_store.py` | 개발 환경의 파일 저장소 구현. 지정된 저장 루트 안에서만 파일 처리 |
| `storage/remote_store.py` | 선정한 운영 객체 저장소의 동일 인터페이스 구현. 업체별 동작은 이 파일에 한정 |

초기 테이블 모델은 `db/models.py`에서 한 번만 정의한다. 각 기능의 DB 질의는 해당 `repository.py`가 소유한다. 저장소 어댑터는 동의·샘플 선정·게임 성공 여부를 판단하지 않는다.

### 세션·문제·제출·수집

아래 네 모듈에는 각각 같은 네 파일을 두되 기능을 구분한다. 즉 표의 각 행은 해당 폴더의 `router.py`, `schemas.py`, `service.py`, `repository.py` 네 파일 계획이다.

| 폴더 | `router.py` | `schemas.py` | `service.py` | `repository.py` |
|---|---|---|---|---|
| `modules/sessions/` | 익명 세션 발급과 쿠키 응답 | 세션 응답·인증 문맥 타입 | 세션 생성·만료·쿠키 인증 | 세션 조회·생성·갱신 |
| `modules/puzzles/` | 오늘/지정 문제 조회 | 공개 문제·날짜·릴리스 응답 | 한국 시간 기준 문제 선택, 시작한 문제 유지, 공개 정보 구성 | 날짜·ID로 문제와 고정 릴리스 조회 |
| `modules/submissions/` | 제출 접수, 요청 ID 조회와 자신의 진행 기록 조회 | Top-3 요청, 세 판정 상태의 result·progress·collection 응답 | 버전·소유권 검사, 판정 호출, 중복 재사용, 시도 수·최고 점수·성공을 한 트랜잭션으로 확정 | 대표 결과·요청 별칭 저장, 세션/진행 행 잠금, 그림 키·요청 지문 조회 |
| `modules/collections/` | 업로드 권한 요청·저장 완료 접수, 수집 선택 변경 처리 | 동의 리비전·업로드 권한·완료 요청 타입 | 동의·표본 선정·보관 가능 여부·원본 검증·삭제·검수 대기 상태 관리 | 수집 선택 이력·표본·업로드 시도·검수 기록 저장. 제출 소유권 읽기 |

`router`는 요청을 받는 경계이고 `service`는 업무 흐름이다. `repository`는 DB 접근만 맡는다. `schemas`는 HTTP 입력·출력의 타입과 형식을 정의하며 점수 계산이나 DB 호출을 하지 않는다.

수집 선택을 바꿔도 같은 그림을 다시 채점하지 않는다. 재시도마다 샘플을 다시 추첨하지 않고 최초 선정 결과를 재사용한다. collections service가 정책에 따른 후보 선정 값을 반환하면 submissions service가 대표 제출과 함께 저장한다. 원본 파일 업로드는 기다리지 않는다. 수집 기능 연결 전에는 비활성 정책 버전과 not_selected를 기록한다.

### 판정과 릴리스

| 파일 | 담당 기능 |
|---|---|
| `modules/judging/types.py` | 검증된 Top-3, 판정 문맥, 후보별 기여도, 판정 결과의 내부 타입. HTTP 타입과 구분 |
| `modules/judging/similarity.py` | 속성별 코사인 비교·보정·속성 가중 합산의 공통 계산. 결측/영벡터 정책 처리. DB·HTTP에 의존하지 않는 함수 |
| `modules/judging/scorer.py` | 후보별 관계 점수 조회, q 정규화, Top-3 가중 평균, 화면 점수 변환과 계산 내역 생성 |
| `modules/judging/judge.py` | 인식 가능 여부·미지원 후보·판정 보류 확인, scorer 호출, 원래 p와 Top-1 ID로 성공 판단 |
| `modules/releases/schemas.py` | 공개/비공개 manifest의 서버 표현과 호환성 검증 타입 |
| `modules/releases/repository.py` | 문제에 연결된 릴리스 레코드와 artifact 위치 조회 |
| `modules/releases/artifact_loader.py` | manifest·점수표·해시·지원 ID·속성 완비 여부 확인과 릴리스별 캐시. 불완전한 자료 로딩 거부 |
| `modules/releases/service.py` | 문제에 고정된 릴리스 선택, 공개 manifest 구성, 내부 판정 문맥 제공 |
| `workers/collection_reconcile.py` | DB에 남은 업로드 미완료·실패 상태와 실제 파일을 대조하고 재처리. 게임 결과는 변경하지 않음 |

점수표 생성 도구도 `judging/similarity.py`의 동일한 계산 함수를 사용한다. 순수 계산 코드가 FastAPI 초기화·DB·환경 변수 로딩을 요구하지 않도록 한다. 실시간 제출에서는 준비된 표를 우선 조회하며, 사용자 요청 중 LLM을 호출하거나 점수표를 다시 만들지 않는다.

릴리스는 문제 API를 통해 공개하므로 초기에는 별도 공개 릴리스 라우터나 관리 UI를 두지 않는다. `judge`는 판정만 반환하고, 실제 게임 진행 상태를 저장하는 책임은 `submissions/service.py`에 둔다. 속성 유사도가 높다는 이유만으로 성공시키지 않는다.

## 3. 모델·학습 핵심 파일

경로 기준: `model/`.

모델 후보와 입출력은 [모델 구조](model-architecture-v1.md)를 따른다. 작은 CNN으로 연결을 확인하고 MobileNetV3-Small과 Conv1D-BiLSTM을 비교한다. 첫 배포 후보는 64px MobileNetV3-Small이며 최종 선택은 품질·모바일 측정 후 확정한다.

| 파일 | 담당 기능 |
|---|---|
| `datasets/build_manifest.py` | Quick Draw·검수된 수집 자료에서 학습 대상 선택, 출처·원본 해시·사용 가능 상태 기록, 세션/중복 그룹을 지킨 분할 manifest 작성 |
| `datasets/sketch_dataset.py` | 공통 manifest에서 이미지/좌표 시퀀스 입력·클래스 인덱스 제공. 원본의 `recognized`는 별도 필터·메타데이터로 유지 |
| `datasets/preprocess.py` | 기존 28px 렌더 호환, 새 64px 렌더·좌표 정규화·시퀀스 길이 처리. 입력 종류·전처리 버전 구분 |
| `networks/sketch_classifier.py` | 설정에 따라 작은 CNN·MobileNetV3-Small·Conv1D-BiLSTM 생성. 공통 345개 logits 출력 |
| `training/train.py` | 설정·데이터셋을 받아 학습, 체크포인트·학습 이력·클래스 매핑 저장 |
| `evaluation/evaluate.py` | 라벨별 인식 성능, 혼동 행렬, 판정 기준에 따른 잘못된 성공·보류율 평가 |
| `evaluation/calibrate.py` | 분리된 보정 자료에서 전체 logits의 온도 보정·인식/성공 임계값 후보 평가. 최종 테스트로 보정값을 학습하지 않음 |
| `export/export_onnx.py` | 학습 모델을 ONNX로 변환하고 입출력 이름·축·클래스 매핑 명세 생성 |
| `export/check_onnx.py` | 동일 입력의 학습 환경/ONNX 출력 비교, 브라우저 비교에 쓸 입력·기댓값 작성 |
| `pipelines/run_training.py` | 데이터셋 구성 → 학습 → 보정·평가 → ONNX 확인 절차 연결. 후속 자동 학습 실행기의 진입점 |
| `pipelines/build_release.py` | 검증된 모델·전처리·매핑·점수표·성공 조건을 호환성 검사 후 변경 불가 릴리스 묶음으로 준비 |

`calibrate.py`는 분류 모델 출력 p의 보정을 담당한다. 속성 코사인 유사도 보정은 `similarity.py`와 점수 설정이 담당하며 서로 다른 버전으로 기록한다. 브라우저가 보정을 중복 적용하지 않도록 모델 manifest에 적용 위치를 명시한다.

현재 `scripts/quickdraw_data.py`의 전처리와 새 Python 전처리를 각각 독립 구현하지 않는다. 구현 단계에서 공통 렌더러를 연결하고 기존 출력과 비교한다. 기존 자료를 자동으로 다시 만들거나 전처리 버전을 조용히 바꾸지 않는다.

`build_release.py`는 운영 DB의 오늘 문제를 직접 변경하지 않는다. 점수 artifact는 별도 도구에서 준비된 자료를 입력받으므로 점수표만 바꾸는 경우 CNN을 재학습하지 않는다.

## 4. 기존 도구와 점수 데이터 핵심 파일

| 파일 | 상태 | 담당 기능 |
|---|---|---|
| `scripts/quickdraw_data.py` | 기존 | Quick Draw 다운로드·라벨·이미지·분할·검증·미리보기. 기존 명령 유지 |
| `scripts/attribute_dictionary.py` | 기존 | 속성 초안 생성·가져오기·검사·보고서·실험용 태그 벡터 출력. API 호출량 제한과 재개 처리 유지 |
| `scripts/scoring/build_score_table.py` | 작성 | 지원 대상과 검토된 사전/벡터·설정을 받아 속성별 비교표·관계 점수·후보별 순위를 생성. 실제 내용 해시 기록 |
| `scripts/scoring/check_score_table.py` | 작성 | 지원 대상 누락·비유한값·결측 정책·대칭성·동점·가까운 후보를 검사하고 검토 보고서 생성 |
| `scripts/scoring/extract_label_vectors.py` | 작성 | 연상 축에 쓸 영어 라벨 단어 벡터만 fastText 파일에서 스트리밍 추출. 원본 파일은 저장하지 않음 |

사전 생성과 벡터 변환을 위해 두 번째 LLM 호출 도구를 만들지 않는다. 학습된 설명 임베딩 방식을 선택한다면 기존 사전 도구의 벡터 출력 기능을 확장하되, 태그 벡터와 생성 버전을 구분한다. 운영용 점수표 발행 조건은 실험용 `--allow-drafts` 결과와 구분한다.

`check_score_table`의 기술 검사 통과가 사람이 관계를 납득하거나 게임이 재미있음을 보장하지 않는다. 대표 정답의 가까운 후보 목록과 실제 그림 수정 사례를 함께 확인한다.

## 5. 핵심 계약·설정 파일

아래는 실행 코드가 읽고 쓰는 구조를 고정하기 위한 파일 계획이다. 실제 가중치·임계값·지원 목록은 이 문서에서 정하지 않는다.

| 파일 | 담당 기능 |
|---|---|
| `contracts/api/openapi.json` | 구현된 FastAPI 스키마에서 내보내는 HTTP 계약. 프론트 타입/예제의 기준이며 별도 수동 명세와 이중 관리하지 않음 |
| `contracts/drawing/drawing.schema.json` | 획 좌표·캔버스·펜·직렬화 버전의 원본 그림 규격 |
| `contracts/model/model-manifest.schema.json` | 이미지/시퀀스 입력 종류·축·logits 출력·전처리·보정 위치·실행 위치·원본 클래스 순서·대표 ID 합산 매핑·candidate_index와 각 해시 규격 |
| `contracts/model/release-manifest.schema.json` | 릴리스 구성 규격. 공개/비공개 표현을 구분하고 비공개 내용이 공개 응답에 섞이지 않게 검사 |
| `contracts/scoring/score-artifact.schema.json` | 지원 ID·속성 모듈·보정·가중치·결측 정책·비교표·내용 해시 규격 |
| `contracts/fixtures/drawing-cases.json` | 좌표 이동·크기·빈 그림·단일 점 등 Python/브라우저 전처리 공통 사례 |
| `contracts/fixtures/judging-cases.json` | 계획. 실제 판정 함수의 정상·보류·정답 Top-2·결측·보정 계산 사례 |
| `contracts/fixtures/submission-cases.json` | 작성됨. 합성 API 요청·응답과 중복·동시성·응답 유실·동의 변경 등 14개 시나리오. 실행 테스트는 아님 |
| `config/model/training.json` | 데이터 선택·모델·학습·재현 설정. 배포된 모델의 변경 불가 설정 사본과 연결 |
| `config/scoring/scoring.json` | 활성 모듈·보정·가중치·결측·표시·동점 규칙의 실험 입력 |
| `config/scoring/recognition.json` | 원래 p·Top-3 합 등을 사용하는 판정 보류·성공 기준의 실험 입력 |
| `config/collection/collection.json` | 수집 안내 버전·표본 선정·보관 정책의 입력 |

기존 `config/attribute-vocabulary*.json`, `attribute-policy-v2.json`, `attribute-request-compact.json`은 속성 생성 설정으로 유지한다. 위 점수 설정과 같은 파일로 합치지 않는다.

모듈별 `schemas.py`는 실행 시 HTTP 검증을 맡고 `openapi.json`은 그 결과의 교환 형식이다. 그림·모델·점수 JSON Schema는 각각 해당 자료의 기준 규격이다. 언어별 검증 코드가 이 규격과 어긋나지 않도록 공통 fixture로 확인한다.

`config`의 가변 실험값을 요청마다 바로 읽어 진행 중 문제의 점수를 바꾸지 않는다. 발행 시 설정 사본과 해시를 릴리스에 고정하고 게임 서버는 해당 릴리스를 읽는다.

## 6. 핵심 검증 파일 계획

이 목록은 검증 책임을 정한 것이며 이번 단계에서 테스트 코드를 생성하지 않는다.

| 파일 | 확인할 동작 |
|---|---|
| `frontend/tests/unit/preprocess.test.ts` | 공통 그림 fixture의 정렬·크기·극성·입력 축 |
| `frontend/tests/integration/submissionFlow.test.ts` | 제출 사본 고정, 원래 p 유지, 재시도 ID 유지, 보류/오류 구분 |
| `frontend/tests/e2e/game.spec.ts` | 문제 진입→그리기→제출→기록→성공·새로고침 복원 |
| `backend/tests/unit/test_judging.py` | 보정·가중 합산·Top-3 혼합, 낮은 확신도, 정답이 Top-2인 사례, 결측 |
| `backend/tests/integration/test_submissions.py` | DB 중복·동시 제출·시도 수·버전 고정·성공 전 정답 비공개 |
| `backend/tests/integration/test_collections.py` | 동의·소유권·표본 선정 재사용·업로드 재시도·게임 결과 보존 |
| `backend/tests/integration/test_releases.py` | 모델/점수표/클래스 매핑 불일치 거부, 공개·비공개 분리 |
| `model/tests/test_dataset_contract.py` | 원본 ID와 클래스 연결, 독립 split·동의/검수 조건·전처리 일관성 |
| `tests/test_score_table.py` | 오프라인 표 생성과 온라인 계산의 일치, 내용 해시·지원 목록 검증 |
| `tests/test_attribute_dictionary.py` | 기존 속성 생성 도구의 검사·재개·부분 저장·호출 상한 검증 유지 |

## 7. 파일 사이의 주요 연결

### 한 번의 게임 제출

`GamePage → useGame → submissionFlow → drawingSnapshot → inference.worker → preprocess/modelRuntime → client → submissions/router → submissions/service → releases/service + judging/judge → submissions/repository → 화면 반영`

인증은 `sessions/service`, DB 세션은 `db/session`을 통해 연결한다. 위 흐름에서 파일 저장·LLM 호출·학습을 기다리지 않는다.

### 선택한 그림의 수집

`CollectionConsent → drawingUpload → collections/router → collections/service → collections/repository + object_store → 저장 완료 확인`

장애 후 확인은 `collection_reconcile`이 같은 서비스 규칙을 재사용한다. 게임 정답·모델 예측·검수 라벨은 별도 항목이다.

### 모델과 속성 점수의 준비

`build_manifest → train → calibrate/evaluate → export_onnx/check_onnx → build_release`

`attribute_dictionary + extract_label_vectors → build_score_table → check_score_table → build_release`

2026-09-25 기준 `judging/types.py`·`similarity.py`·`scorer.py`, `config/scoring/scoring.json`, 점수표 도구 3개와 `backend/tests/unit/test_judging.py`·`tests/test_score_table.py`를 작성했다. 규칙은 [점수 계산 규칙 v1](scoring-v1.md)을 따른다. `judge.py`(보류·성공)는 모델 임계값이 필요해 아직 작성하지 않았다.

두 흐름은 마지막 릴리스 단계에서 결합한다. 그 이전까지 모델 학습과 속성 점수 조정은 독립적으로 진행한다.

## 8. 파일 추가 기준

먼저 위 파일의 책임 안에서 함수·타입을 구현한다. 파일을 나누는 이유는 독립적인 기능·의존성·변경 주기가 생겼을 때로 한정한다. 단순히 함수 하나를 만들었다는 이유로 새 파일을 추가하지 않는다.

`public`, 공통 `ui/styles`, DB 마이그레이션, `infra`의 세부 파일은 실제 정적 자원·화면 디자인·DB/배포 도구를 선택할 때 정한다. 모델 체크포인트·데이터 버전·API에서 생성한 타입 등 자동 산출물 이름은 고정된 핵심 소스 파일 목록과 구분한다. 이번 문서가 그 산출물이나 변경 이력까지 영구히 한 파일로 제한하는 것은 아니다.

첫 구현 묶음은 앱 실행 설정과 세션·문제 조회, 다음은 합성 판정기를 사용한 제출·진행 복원이다. 그다음 실제 판정 함수·브라우저 모델을 연결한다. 저장소 운영 어댑터·수집 worker·학습 pipeline은 해당 기능이 필요할 때 추가한다. 구현된 Pydantic 스키마가 생긴 시점에 OpenAPI를 내보내고 fixture와의 차이를 확인한다.
