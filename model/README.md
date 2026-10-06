# 그림 인식 모델 학습

설계 기준은 [모델 구조](../docs/model-architecture-v1.md)다. 여기에는 **학습 준비와 실행 방법**만 적는다. 평가·보정·ONNX 변환·브라우저 추론은 아직 없다.

## 1. 환경 (한 번만)

백엔드와 섞이지 않게 `model/.venv`를 따로 쓴다(Git 제외). 저장소 루트에서:

```bash
python -m venv model/.venv
model/.venv/Scripts/python -m pip install -r model/requirements.txt --index-url https://download.pytorch.org/whl/cu130 --extra-index-url https://pypi.org/simple
model/.venv/Scripts/python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

PyTorch 저장소에 없는 의존 패키지는 PyPI에서 받으므로 `--extra-index-url`이 필요하다. GPU가 없으면 같은 코드가 CPU로 돈다(느림).

## 2. 데이터셋 만들기

```bash
model/.venv/Scripts/python -m model.datasets.build_manifest --version qd-local1k-64-v1
```

- 입력: `data/quickdraw/raw/*.ndjson`(클래스당 앞부분 1,000장, 무작위 표본 아님). 약 1분 반.
- 출력: `data/datasets/<version>/` — `images.npy`(uint8 64×64), `labels.npy`(원본 class_index 0~344), `split.npy`, `recognized.npy`, `key_ids.npy`, `manifest.json`(로컬), `manifest.public.json`(요약, Git 추적). 버전 폴더는 바꾸지 않으며 다시 만들 때는 새 버전 이름을 쓴다.
- 전처리 `qd-strokes-64-v1`: 긴 변 48px, 중심 정렬, 선 반지름 2px, 4×4 표본 평균. 규칙은 [`datasets/preprocess.py`](datasets/preprocess.py) 상단 주석이 기준이며 브라우저도 같은 식으로 구현한다.
- 분할: 기존 28px 분할을 이어받고 새 그림은 64px 이미지 해시로 정한다. 같은 이미지는 같은 분할로 묶는다.

본 학습용 표본(클래스당 1만 장)은 원본 전체(simplified 345개 파일, **24.0GB**)를 `data/quickdraw/full/`에 받은 뒤 만든다. 다운로드는 아직 하지 않았다.

```bash
model/.venv/Scripts/python -m model.datasets.build_manifest --version qd-10k-64-v1 --source-dir data/quickdraw/full --per-class 10000
```

## 3. 학습

```bash
model/.venv/Scripts/python -m model.training.train
```

- 설정: [`config/model/training.json`](../config/model/training.json) — MobileNetV3-Small(1채널, 345 출력), 배치 512, AdamW 1e-3, 30 epoch, 검증 손실 5회 미개선 시 조기 종료, bf16 자동 혼합 정밀도, 작은 회전·이동·크기 증강. 명령행에서 `--model small_cnn`, `--dataset`, `--epochs`, `--batch-size`로 바꿀 수 있다.
- 데이터 위치: 분할 크기가 GPU 여유 메모리의 절반보다 작으면 GPU, 4GB 이하면 RAM, 그보다 크면 메모리 맵(OS 캐시)을 쓴다. `--placement`로 바꿀 수 있고 `--resume` 때도 바꿀 수 있다.
- 결과: `data/artifacts/models/runs/<runId>/`(Git 제외) — `run.json`(커밋·설정 해시·데이터셋 버전과 파일 해시·환경·결과), `classes.json`, `history.jsonl`(epoch별 손실·top-1/top-3·속도), `last.pt`(이어하기용), `best.pt`(검증 손실 최저).
- 중단과 재개: Ctrl+C로 멈추면 `last.pt`를 저장한다. `--resume data/artifacts/models/runs/<runId>`로 이어서 학습한다.
- 모델 출력은 345개 원본 logits이며 softmax·보정을 넣지 않는다. 대표 ID 합산과 Top-3는 브라우저 런타임이 한다.

## 4. 이 PC에서 잰 속도 (RTX 4050 Laptop 6GB, 2026-09-30)

| 항목 | 값 |
|---|---|
| MobileNetV3-Small 학습 연산만 (합성 입력, 배치 512, bf16) | 약 12,000장/초, GPU 메모리 0.6GB |
| 같은 모델, stem stride 1 (해상도 2배 유지) | 약 5,200장/초 |
| 데이터 공급 + GPU 증강만 | 약 63,000장/초 (GPU·RAM·mmap 배치 모두) |
| 예상: 로컬 1k 데이터 (학습 27.6만 장) | epoch당 약 25초, 30 epoch 약 15분 |
| 예상: 클래스당 1만 장 (학습 약 276만 장) | epoch당 약 4분, 30 epoch 약 2시간 |

예상치는 위 두 측정의 느린 쪽 기준이며 실제 학습으로 확인하지 않았다. 노트북에서는 전원을 연결하고 절전·잠자기를 끈다. 오래 돌리면 발열로 느려질 수 있다.

학습 초반(수백 step)에는 MobileNetV3의 BatchNorm 이동 평균(momentum 0.01)이 아직 따라오지 않아 **평가 모드 정확도가 거의 0**으로 보일 수 있다. 2026-09-26 300 step 점검에서 평가 모드 0.3%, 배치 통계 평가 11%였다. 데이터·라벨 오류가 아니며 1 epoch 이상이면 정상화된다.

## 5. 테스트

```bash
model/.venv/Scripts/python -m unittest discover -s model/tests -t .
```

전처리 고정값(골든 해시)·표본 재현성, 만든 데이터셋의 파일 해시·형태·분할 규칙(없으면 건너뜀), 합성 데이터로 학습·기록·재개 흐름을 확인한다.

## 6. 평가와 보정

```bash
model/.venv/Scripts/python -m model.evaluation.calibrate --run data/artifacts/models/runs/<runId>
model/.venv/Scripts/python -m model.evaluation.evaluate --run data/artifacts/models/runs/<runId> --subset select
```

- 검증 데이터를 이미지 해시 홀짝으로 **모델 선택용(select)**과 **보정용(calibrate)**으로 나눈다. 같은 이미지는 같은 쪽이다. 테스트 분할은 `--final` 없이는 쓰지 않는다(마지막 한 번만).
- `calibrate`: 보정용 절반에서 온도 T(NLL 최소), ECE 전후, p1 기준표, 목표(기본: 잘못된 성공 ≤ 5%, 보류 ≤ 5%)를 만족하는 성공·보류 기준 초안을 `<run>/calibration.json`에 쓴다. 초안은 검토 대상이지 운영값이 아니다.
- `evaluate`: 원본 345개·게임 후보 335개 정확도, Google 인식 성공/실패 그림 구분, 기준별 성공률, **데일리 정답 후보별 성공률·잘못된 성공·주로 헷갈리는 후보**, 혼동 쌍을 `<run>/eval/<split>-<subset>-<checkpoint>/`(`metrics.json`, `per_class.csv`, `report.md`)에 쓴다.
- 로짓은 `<run>/eval/logits-*.npz`에 저장해 다시 쓴다.

## 7. ONNX 변환과 모델 릴리스

```bash
model/.venv/Scripts/python -m model.export.export_onnx --run data/artifacts/models/runs/<runId>
python -m model.export.check_onnx --model-dir data/artifacts/models/<modelVersion>
cd backend && python -m app.cli build-model-release --release-id <id> --model-dir ../data/artifacts/models/<modelVersion>
```

- `export_onnx`: 입력 `image` float32 [batch, 1, 64, 64], 출력 `logits` [batch, 345](softmax·온도 없음), `model-manifest.json`(해시·입출력·전처리·클래스 순서·온도·출처 run)과 비교용 `reference.npz`. `onnx` 패키지가 필요하다(`model/.venv`에 설치됨).
- `check_onnx`: torch 없이 onnxruntime만으로 파일 해시, PyTorch 대비 최대 오차(≤ 1e-3), Top-1 일치, 배치/단건 일치를 확인한다.
- `build-model-release`(백엔드 CLI): 모델 해시·출력 순서를 카탈로그와 대조하고, run의 보정 초안(또는 `--recognition`)을 판정 기준으로 넣어 `inference.mode = browser_onnx` 릴리스를 등록한다. 개발 환경에서는 모델 파일을 `frontend/public/models/<modelVersion>/`(Git 제외)로 복사해 Vite가 `/models/...`로 제공한다. 문제 배정은 바꾸지 않는다(`assign-release`로 따로).
- 브라우저 쪽 전처리 `frontend/src/features/inference/preprocess.ts`는 [공통 사례](../contracts/fixtures/drawing-cases.json)로 파이썬과 바이트 단위 일치를 확인했다. `modelRuntime.ts`는 softmax(logits / T) → 후보 합산 → Top-3, `onnxSession.ts`는 `onnxruntime-web`(WASM, 단일 스레드)으로 모델을 받아 해시를 확인한 뒤 실행한다.
- 2026-10-06 epoch 10 모델: ONNX 7.5MB, PyTorch 대비 최대 오차 4.2e-5(260장 Top-1·Top-3 일치). 브라우저(onnxruntime-web 1.30)에서 고정 그림 4장의 상위 5개가 같고 오차 ≤ 6.4e-6, 준비 0.27초, 그림 한 장 약 3ms. 릴리스 `model-dev-e10-v1`로 등록했으며 문제에는 아직 배정하지 않았다.

## 8. 아직 없는 것

- 모델 릴리스를 실제 문제에 배정해 게임 전체 흐름 확인(`assign-release`)
- 사용자 획의 간소화(Quick Draw는 RDP로 간소화된 획): 렌더 결과 차이가 작다고 보고 아직 적용하지 않음
- 실제 그림판으로 그린 평가 그림(현재 평가는 Quick Draw 검증 분할뿐)
- Conv1D + BiLSTM 비교 모델(획 순서 데이터셋 필요)
