# Quick, Draw! 개발용 데이터

이 폴더는 **그림 인식 모델과 그림판 전처리의 초기 검증**을 위한 데이터 준비본이다.
Google 공식 simplified NDJSON에서 **345개 라벨 × 1,000장 = 345,000장**을 추출한다.
전체 데이터셋 다운로드나 운영 모델 학습 완료를 의미하지 않는다.

## 선택한 형식

- `raw/*.ndjson`: 공식 **simplified 획 데이터**. 각 줄은 하나의 그림이며 `key_id`, `word`, `recognized`, `countrycode`, `timestamp`, `drawing`을 보존한다.
- `processed/<category_id>/images.npy`: 같은 그림을 프로젝트 전처리로 렌더링한 `uint8 (N, 28, 28)` 이미지. CNN 기준선 학습용이다.
- `processed/<category_id>/key_ids.npy`: 원본과 연결하는 문자열 ID. JavaScript 숫자로 변환하지 않는다.
- `processed/<category_id>/recognized.npy`: 원본 게임의 인식 성공 여부. 사람 검수 라벨이 아니다.
- `processed/<category_id>/split.npy`: `0=train`, `1=validation`, `2=test`.
- `processed/<category_id>/manifest.json`: 전처리 버전, 개수, 파일 체크섬.
- `manifests/*.json`: 원본 URL, GCS 객체 버전·ETag, 다운로드 시각, 표본 정책, SHA-256.
- `metadata/labels.json`: 영문 라벨, 안정적인 프로젝트 클래스 번호, 한국어 이름, 대분류, 정답 적합성 초안.
- `metadata/verification.json`: 실제 준비 결과와 검증 통계.
- `previews/index.html`: 345개 라벨별 20장씩 보는 검색 가능한 로컬 미리보기.

공식 `.npy` 비트맵은 사용하기 간단하지만 개별 그림의 `key_id`·획·인식 메타데이터를 담지 않는다.
이 준비본은 **획 → 이미지 → ID → 분할**을 연결하기 위해 simplified NDJSON을 선택했다.
`raw`라는 디렉터리 이름은 프로젝트 입력 원본이라는 뜻이며, 공식 `full/raw` 형식은 아니다.
획의 타이밍 정보는 simplified 데이터에 없다. 리플레이 시간 정보가 필요하면 공식 raw 형식이 필요하다.

## 재현 및 확장

저장소 루트에서 Python 3.10 이상을 사용한다. 실제 준비 환경의 패키지 버전은 `metadata/environment.json`을 참고한다.

```powershell
python -m pip install -r requirements-data.txt
python scripts/quickdraw_data.py catalog
python scripts/quickdraw_data.py download --samples-per-class 1000 --workers 8
python scripts/quickdraw_data.py prepare
python scripts/quickdraw_data.py verify
python scripts/quickdraw_data.py preview
```

다운로드는 공개 Google Cloud Storage HTTPS 주소만 사용하며 계정이나 API 키가 필요 없다.
동일한 샘플 수와 체크섬이 확인된 파일은 건너뛴다. 실패 시 다운로드 명령을 다시 실행하면 된다.
`--samples-per-class 10000`으로 늘릴 수 있다. 이 경우 원본 표본 파일을 교체하므로 `prepare`, `verify`, `preview`도 다시 실행해야 한다.
변경 전 실험을 보존하려면 별도 데이터셋 버전을 만들어 보관한다.
진행 중 `.part` 파일은 불완전한 파일이며 학습에 사용하지 않는다.
학습은 모든 명령이 성공하고 검증 보고서의 `passed`가 `true`인 준비본만 사용한다.

현재 표본은 **각 공식 파일 앞부분에서 구조가 유효하고 ID가 중복되지 않는 첫 N장**이다.
전체 파일을 내려받지 않기 위한 개발용 선택이며 **전체 모집단의 무작위 표본이 아니다**.
확장 명령 역시 같은 prefix 정책이다. 최종 성능 평가용 표본은 전체 스트림의 reservoir sampling 등으로 별도 구성하고,
실제 서비스 그림판으로 그린 독립 검증 그림도 준비해야 한다.

## 라벨을 읽는 방법

`word`는 **Google 게임이 사용자에게 그리라고 제시했던 단어**다.
실제로 그린 대상이 항상 그 단어라는 보장은 없고, `recognized=true` 역시 사람의 정답 확인이 아니다.
`recognized=false`를 임의로 다른 클래스로 바꾸거나 성공 라벨로 확정하지 않는다.
현재 준비본은 true/false 모두 보존한다. 첫 기준선에서 true만 골라 학습하더라도 검증 결과를 true/false별로 나누어 확인한다.

공식 파일은 영어 클래스 이름 345개를 제공한다. 아래는 프로젝트가 추가한 초안이다.

- `class_index`: **이 저장소가 정한** 0~344 모델 출력 인덱스. 고정된 공식 `categories.txt`의 행 순서를 따른다. Google의 보편적인 공식 숫자 ID가 아니다.
- `category_id`: 영문 소문자 + 공백을 밑줄로 바꾼 프로젝트 식별자.
- `display_name_ko`: 사람이 작성한 한국어 표시명 초안. 원래 `label_en`은 수정하지 않는다.
- `primary_group`: 18개 탐색용 대분류. 단일 분류이므로 최종 의미 유사도 태그를 대체하지 않는다.
- `daily_status`: `candidate_unvalidated` 314개, `review` 18개, `exclude_proposed` 13개.
- `attribute_tags`: 현재 빈 배열. 공식 데이터에 색·재질·용도·온도·의미 유사도 정답은 없다. 미주석은 '그 속성이 없음'이라는 뜻이 아니다.

정답 제외 제안은 학습 데이터 삭제가 아니다. 모델이 아는 라벨과 데일리로 출제할 라벨을 분리한다.
314개 후보도 인식 품질이 검증되기 전에는 출시 정답 목록이 아니다.
한국어로 이름을 바꾸거나 일부 정답을 제외해도 모델의 클래스 순서를 재정렬하지 않는다.

## 전처리 계약: `qd-strokes-28-v1`

1. 모든 획 좌표의 bounding box를 구한다.
2. 종횡비를 유지하며 가장 긴 좌표 구간을 20픽셀로 맞춘다.
3. bounding box 중심을 28×28 이미지의 `(13.5, 13.5)`에 맞춘다.
4. 4배 해상도에서 선 굵기 7픽셀(최종 1.75픽셀), 둥근 연결부와 점으로 그린다.
5. Lanczos로 28×28로 축소한다.
6. 검은 배경 0, 흰 선 255의 `uint8`을 저장한다. 모델 입력에서는 `float32 / 255`와 채널 축을 추가한다.

이 이미지는 공식 numpy bitmap을 그대로 내려받은 것이 아니며, 공식 렌더러와 픽셀 단위로 같다고 보장하지 않는다.
브라우저 그림판이 흰 배경·검은 펜이어도 모델 입력은 위 극성·정렬·굵기를 따라야 한다.
브라우저 Canvas의 안티앨리어싱과 Pillow는 다를 수 있으므로 실제 입력과 비교하는 테스트가 필요하다.
현재 원본 획을 보관하므로 이후 64×64 등 다른 해상도로 재전처리할 수 있다.

## 학습용 로딩 예시

```python
import json
from pathlib import Path
import numpy as np

root = Path('data/quickdraw')
labels = json.loads((root / 'metadata/labels.json').read_text(encoding='utf-8'))['categories']
item = next(label for label in labels if label['label_en'] == 'cat')
folder = root / 'processed' / item['category_id']
images = np.load(folder / 'images.npy', mmap_mode='r', allow_pickle=False)
split = np.load(folder / 'split.npy', allow_pickle=False)
recognized = np.load(folder / 'recognized.npy', allow_pickle=False)

# 기준선 예: 학습 split에서 원래 게임이 인식한 그림만 사용.
mask = (split == 0) & recognized
x = images[mask].astype(np.float32)[:, None, :, :] / 255.0  # NCHW
y = np.full(len(x), item['class_index'], dtype=np.int64)
```

각 카테고리 폴더의 클래스 라벨은 `labels.json`의 `class_index`로 정한다.
이미지 파일·ID·인식 여부·분할 배열은 **같은 행 순서**다.
분할은 렌더링 이미지 SHA-256으로 결정하므로 같은 픽셀 이미지가 다른 라벨에 있어도 다른 split으로 유출되지 않는다.
기대 비율은 80/10/10이며 카테고리별 개수가 정확히 800/100/100인 것은 아니다.
거의 같은 그림, 동일 사용자 그림의 분할 문제까지 해결하지는 않는다. 공식 데이터에 사용자 ID는 없다.
정확히 같은 이미지의 중복 및 라벨 충돌은 검증 보고서에 기록하며 자동으로 정답을 수정하지 않는다.

## 출처와 표시

Source: **The Quick, Draw! Dataset**, made available by **Google, Inc.**

- 원본: https://github.com/googlecreativelab/quickdraw-dataset
- 설명·라벨 고정 커밋: `5fe6c0a910b3732bc3db7639d3c9e7c287617f2f`
- 획 데이터: `https://storage.googleapis.com/quickdraw_dataset/full/simplified/<URL-encoded English label>.ndjson`
- 공식 고지: `metadata/LICENSE`
- 라이선스: **Creative Commons Attribution 4.0 International (CC BY 4.0)**, https://creativecommons.org/licenses/by/4.0/
- 프로젝트의 변경: 첫 N장 표본 추출, 한국어 이름·대분류·검토 상태 추가, 이미지 렌더링, 학습/검증/테스트 분할, 미리보기 생성.

원본과 파생 대용량 데이터는 `.gitignore`로 Git 추적에서 제외하지만 로컬에는 실제 파일로 존재한다.
재현 스크립트, 라벨, 출처, 검증 보고서는 추적 가능하다. 저장소를 복제한 사람은 다운로드 명령을 실행해야 한다.
