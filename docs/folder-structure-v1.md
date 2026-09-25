# 프로젝트 폴더 구조 v1

기준: [서비스 아키텍처](service-architecture-v1.md), [기획서 v3.2](<../AI 스케치 게임 서비스 기획서 v3.2.md>). 작성일: 2026-09-22.

아래 구조는 로컬에 생성된 폴더를 문서화한 것이다. 기존 데이터·스크립트 위치를 유지한다. 기능 구현은 [핵심 파일 계획](core-file-plan-v1.md)을 기준으로 진행한다. 데이터의 버전별 하위 폴더와 캐시는 생략했다.

## 1. 폴더와 역할

```text
꼬맨틀/
├─ frontend/
│  ├─ public/                    # 공개 정적 자원
│  ├─ src/
│  │  ├─ app/                    # 앱 진입·화면 구성·초기화
│  │  ├─ features/
│  │  │  ├─ drawing/             # 그림판·획·Undo·Reset
│  │  │  ├─ inference/           # 모델 로딩·전처리·브라우저 추론
│  │  │  ├─ game/                # 문제·제출·기록·성공 화면
│  │  │  └─ collection/          # 수집 선택·그림 업로드
│  │  └─ shared/
│  │     ├─ api/                 # 서버 통신·외부 계약 타입
│  │     ├─ storage/             # 브라우저 저장·캐시
│  │     ├─ ui/                  # 공통 UI
│  │     └─ styles/              # 공통 스타일
│  └─ tests/
│     ├─ unit/                   # 상태·전처리 등 단위 검사
│     ├─ integration/            # 브라우저 기능 사이 연결 검사
│     └─ e2e/                    # 사용자 플레이 흐름 검사
├─ backend/
│  ├─ app/
│  │  ├─ core/                   # 서버 설정·공통 오류·로깅
│  │  ├─ db/                     # DB 연결·테이블 모델
│  │  ├─ modules/
│  │  │  ├─ sessions/            # 익명 세션
│  │  │  ├─ puzzles/             # 데일리 문제
│  │  │  ├─ submissions/         # 제출·중복 처리·진행 기록
│  │  │  ├─ judging/             # 관계 점수·Top-3 혼합·성공 판정
│  │  │  ├─ collections/         # 동의·표본 선정·수집 상태
│  │  │  └─ releases/            # 모델·점수 체계 릴리스
│  │  ├─ storage/                # 로컬·객체 저장소 연동
│  │  └─ workers/                # 업로드 상태 확인·수집 재처리
│  ├─ migrations/                # DB 스키마 변경 이력
│  └─ tests/
│     ├─ unit/                   # 점수·판정 규칙 검사
│     └─ integration/            # API·DB·파일 저장 연결 검사
├─ model/
│  ├─ datasets/                  # 데이터 선택·로딩·전처리 코드
│  ├─ networks/                  # 분류 모델 구조
│  ├─ training/                  # 학습
│  ├─ evaluation/                # 평가·모델 출력 보정
│  ├─ export/                    # ONNX 변환·호환성 확인
│  ├─ pipelines/                 # 학습·평가·릴리스 준비 연결
│  └─ tests/                     # 데이터·모델 입력 계약 검사
├─ contracts/
│  ├─ api/                       # HTTP 요청·응답 규격
│  ├─ model/                     # 모델 입출력·클래스 매핑 규격
│  ├─ drawing/                   # 원본 획·캔버스·직렬화 규격
│  ├─ scoring/                   # 속성·벡터·점수표 규격
│  └─ fixtures/                  # 영역 간 비교용 공통 입력·기댓값
├─ config/                       # 기존 속성 어휘·생성 정책 유지
│  ├─ model/                     # 학습·평가 설정
│  ├─ scoring/                   # 속성 보정·가중치 설정
│  └─ collection/                # 수집 정책 설정
├─ data/
│  ├─ quickdraw/                 # 기존 Quick Draw 원본·이미지·라벨
│  ├─ attributes/                # 기존 속성 사전·생성 이력
│  ├─ collected/                 # 서비스 수집 그림의 로컬 보관
│  ├─ datasets/                  # 학습용 데이터셋 manifest·구성 결과
│  └─ artifacts/
│     ├─ models/                 # 학습 모델·ONNX·평가 산출물
│     ├─ scoring/                # 발행할 속성 벡터·점수표
│     └─ releases/               # 공개/비공개 manifest·배포 묶음
├─ scripts/                      # 기존 데이터·속성 준비 명령
│  └─ scoring/                   # 오프라인 점수표 생성·검사 명령
├─ tests/                        # 기존 데이터·속성 도구 테스트
├─ examples/                     # 도구 사용 예제·응답 예시
├─ infra/
│  ├─ local/                     # 로컬 서비스 실행 환경
│  └─ deploy/                    # 운영 배포 설정
└─ docs/                         # 기획·설계·사용법
```

루트의 기존 기획서·README·의존성 목록·환경 설정 파일은 그대로 유지한다. 이 트리는 서비스 개발에 사용하는 디렉터리만 설명하며, 도구가 만든 캐시 폴더까지 프로젝트 구조로 채택하는 것은 아니다.

## 2. 배치 원칙

- **기능별 배치:** 제출 요청·검증·저장은 `submissions`, 수집 조건과 상태는 `collections`에 둔다. 공통 폴더에 기능별 업무 로직을 쌓지 않는다.
- **코드와 결과물 분리:** `model/datasets`는 실행 코드이고 `data/datasets`는 그 코드가 읽거나 만든 자료다. `config`는 실행 조건, `contracts`는 자료 형식이다.
- **온라인과 오프라인 분리:** 실시간 판정은 `backend/app/modules/judging`, 속성 사전 생성은 기존 스크립트, 점수표 발행은 `scripts/scoring`, 모델 학습은 `model`이 담당한다.
- **수집의 경계:** 프론트는 선택·업로드, 백엔드는 동의·선정·검증, 저장소 어댑터는 파일 입출력을 담당한다. `data/collected`가 별도 수집 서버를 뜻하지는 않는다.
- **모델 공개 범위:** 브라우저용 모델은 공개 배포할 수 있지만 `data` 전체를 정적 파일로 노출하지 않는다. 그림 원본·정답·점수표·키는 공개 영역에 두지 않는다.
- **테스트 소유권:** 프론트·백엔드·모델의 테스트는 각 영역에, 기존 준비 스크립트의 테스트는 루트 `tests`에 둔다. 여러 영역이 공유하는 검증 자료만 `contracts/fixtures`에 둔다.
- **확장 위치:** 학습 자동화는 `model/pipelines`, 서비스 재처리는 `backend/app/workers`, 배포 방식 변경은 `infra`에서 수용한다. 모델 학습을 게임 API worker 안에 넣지 않는다.

## 3. 구조 유지 규칙

### 의존성 방향

| 출발 지점 | 허용하는 의존성 | 금지·주의 |
|---|---|---|
| 프론트 `app` | 각 feature, shared | 업무 규칙을 직접 구현하지 않음 |
| 프론트 `game/submissionFlow` | drawing·inference·API의 공개 함수 | 컴포넌트 내부 상태에 직접 접근하지 않음 |
| 프론트 drawing·inference·collection | 자신의 구현, shared, 주입받은 사본·결과 | game의 hook·컴포넌트를 역참조하지 않음 |
| 프론트 shared | 외부 라이브러리, 공통 계약 타입 | feature를 참조하지 않음 |
| 백엔드 router | 자신의 schemas/service, 인증·DB 의존성 제공 함수 | 직접 SQL·판정 계산 금지 |
| 백엔드 service | 자신의 repository, 명시한 다른 service, 순수 judging, 저장소 인터페이스 | 다른 모듈의 repository를 직접 사용하거나 순환 호출하지 않음 |
| 백엔드 repository | db/session·models | router·service·HTTP 응답 타입을 참조하지 않음. 자체 commit 금지 |
| judging | 자신의 types·계산 함수, 전달된 판정 문맥 | FastAPI·DB·환경 변수·네트워크·전역 파일 로딩 금지 |
| storage 어댑터 | 파일/객체 저장소 도구·설정값 | 동의·샘플 선정·정답 판단 금지 |
| workers | 해당 업무 service | 별도 수집 규칙 복제 금지 |
| `scripts/scoring` | judging의 types/similarity, artifact 계약·파일 도구 | FastAPI 앱·router·DB를 가져오지 않음 |
| model 학습 코드 | 자신의 모듈·계약·학습 설정 | 게임 API 초기화·운영 DB 변경 금지 |

백엔드의 허용 서비스 연결은 `puzzles → releases`, `submissions → releases + collections + judging`, `collections → sessions`로 제한하는 기본안이다. `submissions`와 `collections`가 서로 호출하지 않는다. 제출 서비스는 수집에 필요한 확정 결과를 값으로 넘기고, 수집 서비스는 이를 받는다. 업로드 요청의 소유권 조회에 필요한 읽기 SQL은 collections repository가 소유한다. 테이블을 읽는 것과 다른 모듈의 상태를 수정하는 것은 구분한다.

트랜잭션은 유스케이스 service가 열고 닫는다. 여러 모듈을 거치는 경우 동일 DB 세션을 전달하며, 하위 service/repository는 중간 commit을 하지 않는다. 인증 문맥은 진입 시 확인해 전달하고 순수 판정 함수에서 쿠키를 읽지 않는다.

각 feature/module은 공개 함수·타입을 통해 연결한다. 처음부터 모든 폴더에 추상 클래스·인터페이스 파일을 만들지는 않는다. 순수 계산을 import하는 테스트는 API/DB 설정 없이도 실행돼야 한다. 추후 의존성 자동 검사 도입 시 이 표를 기준으로 한다.

### 데이터 버전 관리

`.gitignore`에서 수집 원본, 로컬 데이터셋 행별 manifest, 모델·점수·비공개 릴리스 산출물을 제외한다. 파일 크기가 작아도 사용자 식별자·그림 경로가 있는 manifest는 기본적으로 제외한다.

- `contracts/`의 스키마와 **합성** fixture, `config/`의 비밀 값 없는 설정은 추적한다.
- `data/datasets/**/manifest.public.json`은 집계·출처·버전만 담은 공개용 요약에 한해 추적 가능하다.
- `data/artifacts/releases/**/public-manifest.json`은 공개 가능한 모델 배포 명세만 추적 가능하다.
- 위 경로의 README는 실제 그림이나 비밀 값을 넣지 않는 사용 설명으로 한정한다.
- 개인 그림·내부 정답·비공개 경로는 공개 manifest에 넣지 않는다. Git 제외는 이미 추적된 파일의 기록을 지우는 기능이 아니므로 추가 시 변경 목록을 확인한다.

### 파일을 만드는 시점

핵심 파일 계획은 책임 목록이며 빈 파일 일괄 생성 지시가 아니다. 첫 구현은 세션/문제 조회 → 제출/기록 → 실제 판정 연결 순으로 필요한 파일만 만든다. 수집 worker, 운영 저장소 어댑터, 학습 pipeline은 해당 기능 단계에서 생성한다. `db/models.py`도 우선 필요한 테이블부터 구현한다.

새 기능은 먼저 기존 폴더의 책임에 배치한다. 루트 폴더나 공통 계층을 늘리는 것은 기존 책임으로 표현할 수 없을 때 검토한다. 데이터 버전별 디렉터리·자동 생성 산출물·DB 마이그레이션 이력은 개발 구조 변경과 구분한다.

이번 단계에서 애플리케이션 파일·패키지 설치·배포 설정을 만들지는 않았다. 비어 있는 폴더는 로컬에 존재하며, Git은 빈 폴더를 별도로 추적하지 않는다. 실제 파일을 추가하는 단계에서 버전 관리에 포함된다.

구체적인 HTTP/DB 동작은 [API 계약](api-contract-v1.md)과 [DB 스키마·트랜잭션](database-schema-v1.md)을 따른다.
