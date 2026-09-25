# AI 스케치 추측 게임

기획 문서: [AI 스케치 게임 서비스 기획서 v3.2](<AI 스케치 게임 서비스 기획서 v3.2.md>)

그림판 데모: [실행 방법과 구현 범위](frontend/README.md). `frontend`에서 `npm ci` 후 `npm run dev`로 실행한다. 그리기·Undo·Reset·제출 사본·썸네일·요청 데이터 초안을 확인할 수 있다.

아키텍처 초안: [React + FastAPI 기반 서비스 구조](docs/service-architecture-v1.md)

개발 구조: [폴더 구조와 배치 원칙](docs/folder-structure-v1.md) · [핵심 파일명과 기능 계획](docs/core-file-plan-v1.md)

판정: [판정 기준 v1](docs/judging-criteria-v1.md) — 요청 검사 → 보류 → 점수 → 성공 순서와 정답 인정 범위. 인식·성공 임계값은 모델 평가 후 정한다.

점수 계산: [점수 계산 규칙 v1](docs/scoring-v1.md) — 속성 태그 3축(분류·형태·기능) + 영어 라벨 단어 벡터 연상 1축. `scripts/scoring`으로 334×334 점수표를 만들고 검사한다.

구현 기준: [게임 API 계약](docs/api-contract-v1.md) · [DB 스키마와 트랜잭션](docs/database-schema-v1.md) · [합성 제출 사례 14개](contracts/fixtures/submission-cases.json)

프론트 화면: [그림판·제출 기록·Q&A와 모바일/데스크톱 계획](docs/frontend-plan-v1.md)

모델 구조: [Quick Draw 레퍼런스·모델 선택·입출력·학습·모바일 배포 계획](docs/model-architecture-v1.md)

아키텍처 문서에는 프론트·백엔드·모델·속성·수집 담당의 산출물, Top-3/릴리스 연결 규격, 수집 상태와 후속 MLOps 연결 지점, 단계별 완료 기준을 정리했다. 현재 프론트에는 그림판 단독 프로토타입이 있으며 게임 API·학습 모델은 아직 구현 전이다. 데모는 서버 전송·AI 판정을 수행하지 않으며 아래 데이터 도구와 구분한다.

모듈 의존성, 요청 재시도·같은 그림 중복 처리, 수집 동의 리비전, 업로드 실패와 게임 결과의 분리까지 설계했다. `.gitignore`는 사용자 그림·내부 데이터셋 manifest·모델/점수 산출물을 기본 제외하고 명시된 공개 요약만 허용한다. 아직 운영 임계값·점수 범위·수집 비율·보관 기간은 확정하지 않았다.

카테고리 정리: [통합·보류 판단과 적용 규칙](docs/catalog-curation-v1.md). 검토 반영 버전 `catalog-curation-v1.1`은 345개 원본을 인식 후보 335개로 묶는다(통합 10, 별개 개념 6쌍 통합 보류). 점수 지원 초안은 334개, 데일리 후보는 323개다. `bird`는 확률을 유지하는 미지원 후보로 남기며 Top-3에 있으면 판정을 보류한다. 매핑은 [catalog-curation-v1.json](config/model/catalog-curation-v1.json)에 있다.

## 준비한 Quick, Draw! 데이터

- **345개 라벨 × 1,000장**, 전체 클래스의 초기 개발용 표본.
- 공식 simplified 획 원본과 같은 그림에서 생성한 28×28 학습 이미지.
- 영어·한국어 라벨, 프로젝트 클래스 ID, 18개 대분류와 데일리 정답 적합성 초안.
- 이미지 SHA-256 기반 train/validation/test 분할 및 데이터 검증 보고서.

바로 확인할 파일:

- [사용법·전처리·출처](data/quickdraw/README.md)
- [라벨 검토 내용](docs/quickdraw-label-review.md)
- [전체 라벨 JSON](data/quickdraw/metadata/labels.json)
- [그림 미리보기](data/quickdraw/previews/index.html) — 다운로드 및 미리보기 생성 후 로컬 브라우저로 열기
- [검증 결과](data/quickdraw/metadata/verification.json)
- [다운로드·전처리 스크립트](scripts/quickdraw_data.py)

이 표본은 원본 파일 앞부분에서 추출한 개발용 데이터이며 전체 데이터의 무작위 표본이 아니다.
아직 모델을 학습하거나 인식 정확도를 평가하지 않았다.

## 속성 사전 자동화

사용법: [속성 사전 생성·검토·이어 실행](docs/attribute-dictionary.md). 현재 v3 어휘와 compact 요청을 기준으로 한다. v3는 345개 전체 초안이 있으며 모두 미검수다.

분류·형태·기능 속성 초안을 생성하고 검사하는 스크립트를 준비했다. API를 통한 일괄 생성과, API 없이 생성 요청을 만들어 응답을 가져오는 방식을 지원한다.

- [사용법과 검토·확장 방법](docs/attribute-dictionary.md)
- [자동화 스크립트](scripts/attribute_dictionary.py)
- [v3 허용 태그 설정](config/attribute-vocabulary-v3.json) · [v3 분류 트리·의미 정책](config/attribute-policy-v3.json)
- [현재 v3 검토 보고서](data/attributes/draft-v3/review-report.md)

v1은 실제 속성 초안 290개를 저장했다. v2는 GMS 생성이 120개에서 HTTP 401(사용량 소진)로 중단됐다. 나머지 225개와 의미 규칙에 걸린 6개는 API 없이 수동 `import`로 채웠다. 이후 v3에서 단계형 분류 트리를 만들고 스케치 형태·기능 태그를 보강했다. 345개 전체를 같은 기준으로 다시 작성했고 실험용 태그 벡터(`draft-v3/vectors.json`)도 출력했다. 이후 학습된 텍스트 임베딩 생성과 운영 점수 보정은 후속 작업이다.
