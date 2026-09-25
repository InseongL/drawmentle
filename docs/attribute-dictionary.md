# 속성 사전 생성·검토 사용법

현재 구현 기준: **v3 어휘 + compact 요청**(`draft-v3`). v1·v2 자료는 기록으로 보존한다. 이 문서를 속성 사전 도구의 단일 사용 안내로 유지한다.

게임에서 사용할 대상의 `classification`(분류), `shape`(형태), `function`(기능·행동)을 미리 생성하고 검토한다. 색상은 비활성 상태다. 분류된 대상의 전형적인 속성을 정리하며 게임 중에는 LLM을 호출하지 않는다.

## 현재 상태와 파일

2026-09-23 기준, [draft-v3](../data/attributes/draft-v3/)에 전체 라벨 345개의 v3 초안이 있다. 모두 미검수(`unreviewed`)다. 최초 수동 `import` 35개 job(출처 `claude-code-manual`) 이후 검토 수정 job 1개(출처 `codex-review-correction`)로 2개 항목을 교체했다. API 호출은 없었다. 결과는 다음과 같다.

- 의미 규칙 위반 0, `uncertain` 축 0
- `not_applicable` 17개: 자연 지형·수역, 무지개, 도형, 수염류의 기능 축
- 태그 구성이 완전히 같은 쌍: `cup/mug`, `bus/school_bus` (실제로 겹치는 개념). [카테고리 정리 v1](catalog-curation-v1.md)에서 대표 하나로 통합했다. 통합된 쪽 레코드는 보존하지만 점수에는 쓰지 않는다.
- 실험용 태그 벡터 [vectors.json](../data/attributes/draft-v3/vectors.json)

| 파일 | 역할 |
|---|---|
| [생성 스크립트](../scripts/attribute_dictionary.py) | 요청 준비·API 생성·가져오기·검사·보고서·실험용 벡터 출력 |
| [v3 어휘](../config/attribute-vocabulary-v3.json) | 속성별 허용 태그와 한국어 정의 |
| [v3 의미 정책](../config/attribute-policy-v3.json) | 분류 트리(상위 분류)·도메인 배타 규칙·혼동 후보·생성 지시 |
| [v3 compact 설정](../config/attribute-request-compact-v3.json) | 설명 길이·메모 제한·v3 의미 검사 규칙 |
| [v3 검토 보고서](../data/attributes/draft-v3/review-report.md) | 항목별 초안·혼동 후보 비교·우선 검토 목록 |

`draft-v1`(290개)과 `draft-v2`(345개)는 태그 좌표가 달라 v3와 섞지 않고 보존한다. [v1 어휘](../config/attribute-vocabulary.json)와 [예시 응답](../examples/attribute-response.json)은 기존 자료 읽기와 테스트에 사용한다. `example-v1`의 12개는 수작업 예시이며 API 생성·검수 완료 자료가 아니다.

어휘 파일은 `request_config_file`로 자신의 compact 설정을 지정할 수 있다. 지정하지 않은 v1·v2는 기존 [compact 설정](../config/attribute-request-compact.json)을 그대로 읽는다.

검토 수정은 `screwdriver`의 속이 찬 쇠대에서 `straight_tube`를 제거하고, `sea_turtle`에서 근거 없는 `hiding`을 제거한 것이다. 태그 정의·좌표와 사전의 어휘 해시는 유지했다. 나머지 343개 레코드는 그대로이며, [검토 이력](../data/attributes/draft-v3/review-corrections-2026-09-23.json)에 수정 전 레코드·출처·설정과 변경하지 않은 레코드의 해시를 남겼다.

검사 설정은 `compact-request-v3.1`로 올리고 `single_path_modules: ["classification"]`를 추가했다. compact·legacy 입력과 저장된 사전 검사 모두에 적용하며, 형제 분류를 함께 넣으면 가져오기를 거부한다. 부모 보완은 `normalize_response`에서 수행한다. v1/v2에는 이 제한을 적용하지 않는다. 이전 compact job은 이전 설정 해시에 묶인 기록이므로 현재 설정에서 재수입하면 해시 불일치로 거부된다. 재현 시 검토 이력의 `previous_request_config`를 격리된 설정에 복원하고, 새 수정 작업은 현재 설정으로 새 job을 만든다. 기존 job·response·request-plan은 당시 기록으로 보존한다.

**CLI 기본 `--vocabulary`와 `--out`은 기존 호환성을 위해 v1 경로다. v3에는 아래 명령처럼 두 옵션을 반드시 지정한다.** Python 3.10 이상에서 프로젝트 루트를 기준으로 실행한다. 속성 도구 자체는 표준 라이브러리를 사용하며 공통 옵션은 하위 명령 뒤에 지정한다.

## v3 설계

현재 실험용 벡터·비교 보고서는 모듈별 태그 multi-hot 코사인을 쓴다. 그래서 태그는 "가까운 대상일수록 더 많이 공유되도록" 구성했다. 운영 점수 보정 방식은 아직 확정하지 않았다.

| 모듈 | 구성 원칙 |
|---|---|
| 분류 (145개) | 최상위 도메인 6개(`organism`·`artifact`·`food`·`nature`·`abstract`·`fictional`) 아래 2~4단계 트리다. 가장 구체적인 하위 분류 하나를 고르고 정규화 단계에서 부모를 보완한다. 예: `feline → mammal → animal → organism`. 서로 다른 도메인뿐 아니라 같은 도메인의 형제 분류도 동시에 쓸 수 없다. |
| 형태 (111개) | 단색 스케치에서 실제로 보이는 윤곽·부위·무늬만 쓴다. 불꽃, 나선, 돔, 잘록한 허리, 집게발, 더듬이, 경광등, 소매, 가로 단, 격자무늬, 김 선 등을 v2보다 보강했다. 동물 해부 태그(귀·꼬리·수염·갈기·집게발 등)는 생물·가상 존재·동물 인형에만 쓴다. |
| 기능 (85개) | 인공물은 대표 용도, 생물은 대표 행동을 쓴다. 자연 현상은 관찰되는 작용(빛·열, 물 흐름, 강수, 바람, 방전)만 쓴다. 보기·듣기·냄새, 여행, 우편, 보안, 농사, 통로, 공놀이 등을 추가해 v2의 `uncertain` 원인을 없앴다. |

v2에서 바꾼 점:
- 뜻이 섞였던 태그를 나눴다. 라디오 `antenna`와 곤충 `feelers`, 물 경계 `water_edge`와 일반 윤곽이 그 예다.
- 한 대상만 쓰던 기능 태그(`hoop_shooting`, `bat_striking` 등)를 `ball_game`·`striking`처럼 공유되는 태그로 합쳤다.
- 도형의 변 개수(`hexagonal`·`octagonal` → `polygonal`)는 형태 축의 상위 태그로 연결했다.

Quick Draw 미리보기로 뜻이 모호한 라벨을 확인했다. 다이아몬드는 보석, 위장은 얼룩무늬, 동물의 이동은 새 떼로 작성했다. 한국어 이름과 다른 표본이 섞인 경우(`mouse`의 컴퓨터 마우스 등)는 메모로 남겼다.

해당 없음 축을 점수에서 빼는 정책이면, 남은 축만으로 평균이 올라가는 사례가 생긴다(예: 번개–산). 반대로 0점으로 치면 한쪽에만 기능이 있는 쌍이 내려간다(예: 바다–강). 이 선택은 백엔드 결측 처리 정책에서 정한다.

### 트리 깊이와 코사인 기준값

태그 집합 A, B의 코사인은 `공유 태그 수 / sqrt(|A| × |B|)`다. 같은 계층을 공유해도 경로 길이에 따라 값이 달라진다. 현재 분류 축에서 전구–시계는 `artifact` 하나만 공유해 0.5, 의자–노트북은 같은 도메인만 공유해 약 0.333이다. 고양이–새는 `animal/organism`을 공유해 약 0.577이다. '같은 강은 항상 0.75' 같은 고정 단계 점수로 해석하면 안 된다.

이는 코사인 계산 오류가 아니라 분류 체계의 깊이가 점수에 영향을 주는 설계 한계다. 현재 벡터 산식을 임의로 바꾸지 않고, 출시 전 도메인·경로 깊이별 점수 분포와 가까운 쌍/먼 쌍의 순위를 평가한다. 도메인 태그 가중치 축소·깊이 가중·트리 거리 방식은 비교 실험 후 별도 점수 버전으로 선택한다. [점수 계산 규칙 v1](scoring-v1.md) 초안은 희귀도(IDF) 가중으로 흔한 도메인 태그의 비중을 낮춘다. 그래서 전구–시계처럼 `artifact`만 공유하는 쌍은 위 multi-hot 값보다 낮게 나온다. 해당 없음 축 정책도 여전히 별도 결정 사항이다.

## 연결 설정

SSAFY GMS는 `--provider gms`와 `GMS_KEY`, 직접 OpenAI 연결은 `--provider openai`와 `OPENAI_API_KEY`를 사용한다. 선택한 제공자의 키만 읽는다. 키는 환경 변수 또는 프로젝트 루트의 `.env.local`에 넣으며 환경 변수가 우선한다. 형식은 [.env.example](../.env.example)을 따른다.

GMS 주소는 사용자가 지정한 `https://gms.ssafy.io/gmsapi/api.openai.com/v1/chat/completions`이다. 직접 OpenAI 연결은 Responses API를 사용한다. `.env.local`은 단순 `KEY=value` 형식이며 스크립트 실행 시 읽는다. 원본 그림이나 유저 그림을 생성 API에 보내지 않는다.

## 확인한 개선

저장된 실제 요청 12개와 같은 대상을 사용해 비교했다. 공통 지시문·입력 문자열·응답 스키마의 문자 수 합계가 **212,620 → 97,549자, 54.1% 감소**했다. 이는 토큰 수나 요금 절감률이 아니다. 응답 길이·캐시 적용·결과 품질은 실제 호출 후 비교해야 한다.

- 길었던 공통 지시문과 반복 사례 설명을 짧은 규칙으로 정리했다.
- 같은 태그 목록을 입력과 응답 스키마에 이중으로 넣지 않는다. 스키마는 JSON 구조를 강제하고, 허용 태그는 로컬 코드가 검사한다.
- 영어 이름과 중복되는 ID, 한국어 이름, 대분류만 대상 입력으로 보낸다. 검토용 메타데이터는 로컬에 남긴다.
- 혼동 후보는 ID 목록으로 전달한다. 분류 상위 태그 보완은 기존 로컬 규칙으로 처리한다.
- 대분류 순으로 묶고, 해당 묶음 전체에 적용되지 않는 태그를 제외한다. 임의로 태그 대부분을 제거하지는 않는다.
- 한국어 속성 설명은 60자 이내 한 구절, 메모는 최대 2개·각 80자로 제한한다. 임베딩에 사용할 설명은 남긴다.
- 한 응답에서 정상 항목을 먼저 저장한 뒤, **실패한 항목만** 수정 요청한다. ID 누락·중복으로 응답 대상을 신뢰할 수 없을 때는 부분 저장하지 않는다.

이 동작은 새 기본 요청 방식인 `--profile compact`에 적용된다. 이전 요청 방식을 재현할 때만 `--profile legacy`를 사용한다. 저장 형식과 v2 태그 좌표를 변경하지 않았으므로 기존 120개를 재생성할 필요가 없다. 항목별 생성 이력과 요청 정책 해시는 별도로 기록한다.

## v2 기록

v2는 v3 이전의 어휘로 만든 초안이다. 참고용으로만 보존한다.

| 구분 | 대상 수 | 출처 |
|---|---:|---|
| GMS 생성 | 114 | `gms_chat_completions` (gpt-5.4-mini) |
| 수동 작성 — 미생성 대상 | 225 | `claude-code-manual`, 23개 job |
| 수동 교체 — 의미 규칙에 걸린 대상 | 6 | `claude-code-manual`, `--replace-drafts` |

`missing`·`flagged` 요청 계획은 현재 0건이다. 의미 규칙 검사에 걸린 항목도 없다. 교체한 6개는 `airplane`, `backpack`, `banana`, `chair`, `couch`, `cruise_ship`이다. 이 검사는 대표 사물에 귀·꼬리·지느러미 태그를 붙인 경우를 찾는다. 귀가 달린 장식물 같은 예외를 모두 판별하는 범용 의미 검증은 아니다.

수동 작성분은 어휘에 맞는 태그가 없으면 억지로 채우지 않았다. 그런 축은 `uncertain`으로 두고 부족한 개념을 메모에 남겼다(예: 코의 후각, 콘센트의 전력 공급, 베개·침낭의 침구 분류, 육각형·팔각형). `hexagon/octagon`, `bus/school_bus`는 태그 구성이 완전히 같다. 보고서의 `identical_attribute_profile` 표시는 이 때문이다.

`long_neck`는 악기, `four_legs`는 가구, `wings`는 항공기에도 사용할 수 있어 일괄 금지하지 않았다. `fins`는 이번 규칙에서 해부학적 지느러미로 해석한다. 항공기·선박의 비슷한 부품에도 쓰려면 규칙과 태그 정의를 먼저 조정해야 한다. 검토 대상의 태그를 임의로 삭제하거나 검수 완료로 바꾸지는 않았다.

## API 없이 준비·확인

프로젝트 루트에서 실행한다.

```powershell
python scripts/attribute_dictionary.py prepare --vocabulary config/attribute-vocabulary-v3.json --out data/attributes/draft-v3 --selection missing
python scripts/attribute_dictionary.py prepare --vocabulary config/attribute-vocabulary-v3.json --out data/attributes/draft-v3 --selection flagged
```

준비된 파일:

- [미생성 대상 요청 계획](../data/attributes/draft-v3/request-plan-missing.json) — 현재 0건
- [의심 항목 요청 계획](../data/attributes/draft-v3/request-plan-flagged.json) — 현재 0건
- [수동 작성 응답](../data/attributes/draft-v3/responses/) — job ID별 `import` 입력 원본
- [검토 보고서](../data/attributes/draft-v3/review-report.md)
- v2의 [문자 수 비교·원본 해시 확인](../data/attributes/draft-v2/compact-audit.json)

`prepare`는 API 키를 읽지 않는다. `generate --dry-run`도 호출 없이 요청 범위와 상한을 확인할 수 있다. 계획 파일의 문자 수는 실제 토큰 수가 아니며, 이전 사용량은 응답이 저장된 요청만 합산한다. 실패한 HTTP 요청의 사용량은 알려지지 않았을 수 있다. 캐시 입력은 전체 입력 토큰에 이미 포함된다.

## API 생성과 재개

**아래 명령은 실제 API를 호출한다.** 사용할 수 있는 GMS 키를 환경 변수 또는 `.env.local`에 설정한 뒤 실행한다. v3 작성에는 API를 호출하지 않았다. v3는 현재 남은 대상이 없으므로, 새 어휘 폴더나 새 카테고리에 쓸 때 한 묶음부터 확인한다.

```powershell
python scripts/attribute_dictionary.py generate --provider gms --model gpt-5.4-mini --vocabulary config/attribute-vocabulary-v3.json --out data/attributes/draft-v3 --selection missing --max-batches 1 --max-api-calls 1 --validation-retries 0
```

결과를 확인한 뒤 `--max-batches`와 `--max-api-calls`를 늘린다. 오류가 많으면 상한에 도달해 일부가 남을 수 있다.

`--max-api-calls`는 **한 번 실행하는 동안의 HTTP 요청 수** 상한이다. 최초 호출·내용 수정 요청·HTTP 재시도를 모두 센다. 명령을 다시 실행하면 새로운 상한이 시작되며, 월별 과금 한도나 토큰 한도는 아니다. `--max-output-tokens`는 요청별 출력 토큰 상한이다. HTTP 재시도는 기본 0회로 바꿨다. `--validation-retries`는 기본 1회이며 명시적으로 0으로 끌 수 있다.

`--selection missing`은 저장되지 않은 대상만 생성한다. `--selection flagged`는 새 의미 규칙에 걸린 **미검수** 항목만 교체한다. 일반 검토 메모, 불확실한 속성, 같은 태그 구성이라는 이유만으로 모든 항목을 다시 호출하지 않는다. 검수 완료 항목은 두 방식 모두 자동 교체하지 않는다.

정상 항목은 부분 응답 단위로 저장된다. 예를 들어 10개 중 9개가 통과하면 9개를 저장하고 남은 1개만 다시 묻는다. 수정 요청을 끄거나 상한에 도달해도 9개는 남는다. 다음 실행에서는 누락 항목만 선택한다. 기존 의심 항목 수정의 경우 새 응답이 통과하기 전까지 원본을 유지한다. 한 폴더에는 한 프로세스만 실행한다.

## 수동 응답 가져오기

`prepare`가 만든 `jobs/`의 Markdown 요청을 AI에 전달하고 JSON 본문만 응답 파일로 저장한다. `JOB_ID`와 응답 경로를 실제 파일명으로 바꾼다.

```powershell
python scripts/attribute_dictionary.py import --vocabulary config/attribute-vocabulary-v3.json --out data/attributes/draft-v3 --job data/attributes/draft-v3/jobs/JOB_ID.json --response response.json --source chat-manual
```

수동 `import`는 응답 전체를 엄격하게 검사하며 자동 API 수정 요청을 보내지 않는다. API 생성의 부분 저장과 구분한다.

## v2 생성 규칙 (v3에도 적용)

| 항목 | v2 처리 |
|---|---|
| 표현 가능한 차이 | 봉제선·패널선, 울퉁불퉁한 표면, 직선·곡선 관, 첨탑, 안테나 등 재사용 가능한 태그 추가 |
| 일관된 분류 | `fruit → food`, `mammal → animal`, `aircraft → vehicle` 등 선언된 상위 분류 자동 보완 |
| 개념 혼합 방지 | 이 프로젝트에서 수확한 과일은 `fruit + food`로 표현하고 `plant`는 함께 붙이지 않음. 보석과 도형처럼 다른 뜻을 동시에 확정하는 조합 검사 |
| 비교를 통한 생성 | 혼동 후보의 명칭을 함께 전달. 야구공–농구공, 블랙베리–블루베리, 교회–집 등 각 속성의 공통점과 차이를 고려하도록 요청 |
| 중복 태그 | 순서를 유지하며 중복만 제거. 원본 응답과 변경 내역 기록 |
| 잘못된 응답 | 정상 항목을 먼저 보존하고 실패한 항목만 기본 1회 수정 요청. ID 누락·중복 시 부분 저장하지 않음 |
| 진행 보고서 | 묶음이 끝날 때마다 갱신하고, 실패 시에도 갱신. 초기 10개만 표시되는 오래된 보고서 문제 개선 |
| 검토 목록 | 공통 태그와 서로 다른 태그를 비교 보고서에 기록. 모든 축이 보류인 대상은 의미가 동일한 쌍으로 집계하지 않음 |

`known`은 여전히 미검수 초안이다. 상위 분류 자동 보완은 모델 판단이 아니라 프로젝트의 명시적 규칙이다. 원래 태그가 틀렸는지까지 자동으로 판별하지는 못한다. 컵·머그처럼 실제로 겹치는 개념은 같은 구성이어도 허용한다. 이름별 고유 태그를 억지로 추가하지 않는다.

`eating`은 음식 자체의 먹는 용도이며 동물의 섭식 행동이나 컵의 용도가 아니다. 음료 용기는 `holding_liquid`, `serving_drink`로 표현한다. 이는 모델에게 전달하는 의미 규칙이며 모든 사례를 로컬 코드가 판별하는 것은 아니다.

## 사전과 검토 상태

`dictionary.json`의 각 대상은 기존 카탈로그의 `category_id`, `class_index`와 연결된다. 원본 `labels.json`이나 그림 파일은 수정하지 않는다. 속성 정보는 별도 파일로 관리한다.

기존 사전을 읽을 때 `class_index`가 정수이며 원본 값과 일치하는지, `label_en`·`display_name_ko`가 원본과 일치하는지도 검사한다. 불일치한 사전은 생성 요청을 보내기 전에 거부하며 자동으로 수정하지 않는다.

각 속성에는 태그 배열, 한국어 설명, 다음 상태가 있다.

| 속성 상태 | 의미 |
|---|---|
| `known` | 현재 어휘로 표현할 수 있는 초안. 사람이 확인했다는 뜻은 아니다. |
| `uncertain` | 단어의 뜻이 모호하거나 필요한 태그가 없어 보류. 태그 배열은 비운다. |
| `not_applicable` | 해당 대상에 이 속성을 적용하기 어려움. 태그 배열은 비운다. |

이것과 별도로 대상의 `review_status`는 모두 `unreviewed`로 시작한다. AI가 높은 확신을 표현하더라도 자동으로 `reviewed`가 되지 않는다.

```powershell
python scripts/attribute_dictionary.py report --vocabulary config/attribute-vocabulary-v3.json --out data/attributes/draft-v3
```

보고서는 다음을 우선 검토 대상으로 모은다.

- 모호하거나 적용되지 않는 속성이 있는 대상
- 기존 카탈로그에서 검토가 필요하다고 표시한 대상
- 작성 메모가 붙은 대상(v1). v2는 메모가 있다는 이유만으로 우선순위를 높이지 않는다.
- 모든 활성 속성의 태그 구성이 다른 대상과 동일한 경우

같은 태그 구성이 반드시 오류는 아니다. 다만 이 태그 벡터만으로는 두 대상을 구분하지 못하므로 게임 점수를 확인할 후보가 된다. 문제가 표시되지 않은 항목도 사실성이 보장되지는 않는다.

먼저 보고서의 속성·설명을 읽고, 뜻이 애매한 이름과 자주 혼동할 대상부터 확인한다. 예를 들어 비행기–헬리콥터, 말–기린, 컵–머그컵이 각 속성에서 어떻게 가까워지는지 살펴본다. 필요하면 실제 그림 표본과 대조한다. 게임에 사용하는 대상은 검토를 마친 범위부터 늘리는 방식이 적합하다.

수정은 원래 응답 JSON에서 하고, 미검토 항목을 교체할 때만 `import`에 `--replace-drafts`를 붙인다. 변경 내용은 다시 검사되며 `unreviewed`로 저장된다. 사람이 검토를 마치면 사전 파일의 해당 `review_status`를 `reviewed`로 바꾼다. 이 상태의 항목은 재가져오기로 덮어쓰지 못한다. 이후 수정이 필요하면 명시적으로 `unreviewed`로 되돌린 뒤 수정·재검토한다. 파일 변경 이력은 Git으로 관리하는 것을 권장한다.

## 벡터와 점수 연결

게임 점수는 아래 실험용 multi-hot 벡터가 아니라 [점수 계산 규칙 v1](scoring-v1.md)의 점수표를 쓴다. 점수표는 이 사전의 태그를 희귀도로 가중하고, 형태·기능은 태그 계열 부분 점수를 준다. 여기에 영어 라벨 단어 벡터의 연상 축을 더한다.

이번 스크립트의 본체는 **태그와 속성별 설명이 들어 있는 사전 생성**이다. `description_ko`를 모듈별 텍스트 임베딩 모델에 넣는 단계는 아직 구현하지 않았다.

우선 동작을 실험할 수 있도록 태그를 숫자 벡터로 내보내는 기능을 넣었다.

```powershell
python scripts/attribute_dictionary.py vectorize --vocabulary config/attribute-vocabulary-v3.json --out data/attributes/draft-v3 --allow-drafts
```

이 결과는 **선택한 태그 위치에 값을 주고 길이를 정규화한 특징 벡터**다. 학습된 텍스트 임베딩은 아니다. 같은 모듈 안에서 코사인 유사도를 계산할 수 있지만, 태그가 겹치지 않으면 의미상 가까운 대상도 0이 될 수 있다. 상위·하위 분류 태그의 중복도 점수에 영향을 준다. `experimental: true`로 표시하며 운영 점수표로 확정하지 않는다.

태그 좌표는 사전 전체 설정을 기준으로 고정한다. `uncertain`과 `not_applicable`은 영벡터가 아닌 `null`로 내보낸다. 백엔드에서 이를 유사도 0으로 바꾸지 말고, 제외·가중치 재분배·판정 보류 중 처리 정책을 먼저 정해야 한다. 사용할 수 있는 모듈이 하나도 없는 경우에는 점수를 만들지 않는다.

이후 기존 기획대로 속성별 설명을 각각 임베딩하려면 `classification`, `shape`, `function`의 설명을 따로 입력하고, 모델·사전·점수 보정 버전을 함께 관리한다. 모듈별 점수 보정과 가중치, Top 3 확률 결합, 정답 판정은 별도 백엔드 작업이다.

## 속성을 확장할 때

`config/attribute-vocabulary-v3.json`의 `modules`에 새 속성의 `enabled`, `description_ko`, `tags`를 추가하면 요청 스키마와 검증, 실험용 벡터 출력에 자동 반영된다. 색상을 쓰려면 기존 `color.enabled`를 켠다.

다만 새로운 축을 추가한 것만으로 점수 품질이 좋아지는 것은 아니다. 적절한 설명과 태그, 기존 대상의 새 속성 생성, 백엔드 가중치와 결측 처리, 유사도 순위 검증이 함께 필요하다.

태그를 바꾸거나 속성을 추가할 때는 설정의 `version`을 올리고 `--out data/attributes/draft-v4`처럼 기존 자료와 다른 새 출력 폴더를 사용한다. 의미 검사 규칙도 바꾸면 새 compact 설정 파일을 만들고 어휘의 `request_config_file`로 지정한다. 서로 다른 태그 좌표나 라벨 버전이 섞이지 않도록 스크립트가 입력 파일의 해시를 검사한다. 기존 사전의 자동 마이그레이션은 제공하지 않는다.

## 검증과 한계

```powershell
python -m unittest discover -s tests -p 'test_attribute_dictionary.py' -v
```

오프라인 검사는 입력 형식·매핑·재개·검수 보호·제공자 키 분리·정상 항목 보존·수정 요청·호출 상한을 확인한다. 실제 속성의 사실성이나 게임 재미를 보장하는 검사는 아니다. compact 요청으로 실제 모델을 호출하지 않았으므로 축소한 질문의 품질은 후속 확인이 필요하다.

게임의 Top-3 혼합·성공 판정은 [서비스 아키텍처](service-architecture-v1.md), 구현 위치는 [핵심 파일 계획](core-file-plan-v1.md)을 따른다.
