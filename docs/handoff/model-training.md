# 인수인계서 1 — 그림 인식 모델 학습

작성 2026-10-06. 이 문서만 읽고 학습을 이어가거나 다음 모델을 만들어 게임에 붙일 수 있도록 정리했다. 설계 근거는 [모델 구조](../model-architecture-v1.md), 명령 상세는 [model/README.md](../../model/README.md)다.

## 0. 한눈에 보는 현재 상태

| 항목 | 상태 |
|---|---|
| 본 학습 | **일시정지**. epoch 11까지 완료, epoch 12부터 재개 가능 |
| 최고 모델 | epoch 10 — 검증 top-1 66.9%, top-3 84.1%, 게임 후보(335개) 기준 top-1 67.8% |
| 게임 연결 | epoch 10 모델을 ONNX로 내보내 릴리스 `model-dev-e10-v1`로 등록, **2026-10-06~11-04 개발용 문제에 배정**(브라우저 AI 인식으로 플레이 중) |
| 판정 기준 | 보정 초안(성공 p1 ≥ 0.9, 보류 p1 < 0.15). 사용자 결정 전 임시값 |
| 커밋 | 마지막 커밋 `83eab4f`(푸시됨). 그 뒤의 모델·평가·브라우저 추론 작업은 **아직 커밋 안 함** |

## 1. 환경

- 장비: 개발 PC 노트북, RTX 4050 Laptop(VRAM 6GB, 드라이버 CUDA 13.1), Core Ultra 7 155H(16코어/22스레드), RAM 31.5GB.
- 학습 전용 가상환경 `model/.venv`(Git 제외). 백엔드 파이썬과 섞지 않는다.

```bash
python -m venv model/.venv
model/.venv/Scripts/python -m pip install -r model/requirements.txt --index-url https://download.pytorch.org/whl/cu130 --extra-index-url https://pypi.org/simple
model/.venv/Scripts/python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

- 설치 버전: torch 2.14.0+cu130, torchvision 0.29.0+cu130, onnx 1.23.1. PyTorch 저장소에 없는 의존 패키지 때문에 `--extra-index-url`이 꼭 필요하다(없으면 `filelock` 설치 실패).
- ONNX 결과 확인(`check_onnx`)은 torch 없이 **시스템 파이썬의 onnxruntime 1.28**로 돌린다(가상환경에는 onnxruntime이 없다).
- 명령은 모두 저장소 루트에서 실행한다(`python -m model....`).

## 2. 데이터

| 이름 | 위치(Git 제외) | 내용 |
|---|---|---|
| 로컬 원본 | `data/quickdraw/raw/*.ndjson` | 클래스당 파일 앞부분 1,000장(무작위 아님). 기존 28px 분할의 기준 |
| 전체 원본 | `data/quickdraw/full/*.ndjson` | Quick Draw simplified 345개 파일 전체 **24.01GB**. 파일마다 크기·MD5(ETag) 검증, 옆 `*.json`에 기록 |
| `qd-local1k-64-v1` | `data/datasets/` | 로컬 원본 34.5만 장, 64px. 빠른 점검용 |
| **`qd-10k-64-v1`** | `data/datasets/` | 본 학습용. 클래스당 1만 장 무작위(시드 20260926), 345만 장. 학습 2,760,943 / 검증 344,327 / 테스트 344,730. 동일 이미지 914장(분할이 달랐던 45장은 한 분할로 옮김) |

- 전체 원본 다시 받기: `python scripts/quickdraw_data.py download-full --workers 8`(시스템 파이썬, requests 필요). 받은 파일은 건너뛴다. 24GB 다운로드는 사용자 승인 사항이었다(2026-10-01 승인됨).
- 데이터셋 만들기: `model/.venv/Scripts/python -m model.datasets.build_manifest --version <새버전> --source-dir data/quickdraw/full --per-class 10000`. 버전 폴더는 바꾸지 않는다(이미 있으면 거부). 약 14분.
- `manifest.public.json`만 Git에 올라가고 배열·`manifest.json`은 제외된다.

### 전처리 `qd-strokes-64-v1` — 바꾸면 안 되는 약속

- 정의는 [`model/datasets/preprocess.py`](../../model/datasets/preprocess.py) 주석이 기준: 긴 변 48px·중심 정렬, 4×4 표본점이 획에서 반지름 2px 이내면 잉크, 평균 후 반올림. 라이브러리 선 그리기를 쓰지 않는 산술 정의라 브라우저([`preprocess.ts`](../../frontend/src/features/inference/preprocess.ts))가 바이트 단위로 같은 값을 낸다.
- [공통 사례 9개](../../contracts/fixtures/drawing-cases.json)를 파이썬·TS 테스트가 모두 확인한다. **렌더 규칙을 바꾸면 버전 이름을 올리고**(예: `qd-strokes-64-v2`) 사례 파일·데이터셋·모델을 모두 다시 만든다. 해시를 고쳐 테스트를 통과시키지 않는다.
- 알려진 차이: Quick Draw 획은 RDP로 간소화돼 있고 사용자 획은 간소화하지 않는다. 64px에서는 차이가 작다고 보고 아직 적용하지 않았다.

### 분할 규칙

- 데이터셋 분할: 기존 28px 분할이 있는 key_id는 그대로, 새 그림은 64px 이미지 SHA-256 버킷(80/10/10). 같은 이미지는 가장 낮은 분할 코드로 묶는다.
- 검증 분할은 다시 이미지 해시 홀짝으로 **모델 선택용(select, 짝수)** / **보정용(calibrate, 홀수)**으로 나눈다(`model/evaluation/evaluate.py`의 `subset_mask`). 현재 학습 스크립트는 최고 epoch를 고를 때 검증 전체를 쓰므로 보정용 절반 결과가 약간 낙관적이다.
- **테스트 분할은 마지막 한 번만** 쓴다. `evaluate --split test`는 `--final` 없이는 거부한다. 아직 한 번도 쓰지 않았다.

## 3. 본 학습 실행 기록

- run 폴더: `data/artifacts/models/runs/20261001-093849-mobilenet_v3_small-main/`(`run.json`, `history.jsonl`, `classes.json`, `last.pt`, `best.pt`, `calibration.json`, `eval/`)
- 로그: `data/artifacts/models/logs/qd-10k-64-v1.log`
- 설정: MobileNetV3-Small(1채널, stem stride 2, 187만 파라미터), 배치 512, AdamW lr 1e-3 / wd 1e-4, 1 epoch 워밍업 후 코사인(30 epoch 기준, 5,392 step/epoch), bf16 자동 혼합 정밀도, 증강(회전 ±8°, 이동 4%, 크기 0.9~1.1), 조기 종료 인내 5.
- 주의: `config/model/training.json`의 기본 데이터셋은 아직 `qd-local1k-64-v1`이다. 본 학습은 `--dataset qd-10k-64-v1`로 덮어써서 돌렸고, run에 실제 설정이 저장돼 있다. 새 학습을 시작할 때 `--dataset`을 빠뜨리지 않는다.

| epoch | 학습 손실 | 검증 손실 | top-1 | top-3 | 비고 |
|---|---|---|---|---|---|
| 1 | 2.852 | 1.971 | 52.2% | 72.8% | |
| 3 | 1.541 | 1.674 | 58.9% | 78.2% | 여기서 1차 일시정지 → mmap으로 재개 |
| 5 | 1.387 | 1.364 | 66.2% | 83.6% | |
| 8 | 1.279 | 1.352 | 66.4% | 83.7% | |
| **10** | 1.230 | **1.329** | **66.9%** | **84.1%** | best.pt |
| 11 | 1.208 | 1.336 | 66.7% | 84.0% | 여기서 2차 일시정지(last.pt, 인내 남은 횟수 4) |

해석: 학습률이 아직 최대의 73%라 후반 감소 구간에서 더 오를 여지가 있다. 과적합 신호는 없다(학습 1.21 / 검증 1.34).

## 4. 학습 재개·중지 방법

```bash
# 재개 (epoch 12부터, 최대 30 또는 조기 종료까지; 남은 약 19 epoch ≈ 1시간 반, 전원 연결 기준)
model/.venv/Scripts/python -u -m model.training.train --resume data/artifacts/models/runs/20261001-093849-mobilenet_v3_small-main --placement mmap >> data/artifacts/models/logs/qd-10k-64-v1.log 2>&1
```

- **전원 확인**: 배터리로 돌면 GPU가 전력 제한(SW Power Cap)으로 클럭이 210~990MHz까지 떨어져 3배 가까이 느려진다. 확인: `nvidia-smi -q -d PERFORMANCE`, PowerShell `(Get-CimInstance Win32_Battery).BatteryStatus`(2 = 전원 연결).
- **데이터 위치**: 11GB 학습 분할을 RAM에 복사하면 Windows가 페이지 파일로 밀어내 느려진다(약 6천 장/초). 4GB 초과 분할은 기본이 mmap이고 9~10천 장/초가 나왔다. 재개할 때도 `--placement`로 바꿀 수 있다.
- **잠자기**: 노트북 덮개를 닫거나 절전하면 멈춘다. 에이전트는 keep-awake를 요청하고, 사용자에게 전원·덮개를 안내한다.
- **중지**: 터미널이면 Ctrl+C(현재 epoch를 last.pt로 저장). 백그라운드면 학습 프로세스 트리를 종료한다. 가상환경 실행기와 실제 파이썬 두 프로세스가 뜨므로 `taskkill /PID <venv python.exe의 PID> /T /F`. 이때 **last.pt는 epoch가 끝날 때만 저장되므로 진행 중 epoch는 버려진다**. epoch 종료 직후(로그에 `epoch N:` 줄이 찍힌 뒤) 멈추는 것이 좋다. 멈춘 뒤 `run.json`의 `status`를 `paused`로 적어 둔다(이전 두 번 모두 그렇게 했다).
- **초반 검증 정확도 0%**: MobileNetV3의 BatchNorm 이동 평균(momentum 0.01) 때문에 수백 step 안에서는 평가 모드 정확도가 거의 0이다. 버그가 아니며 1 epoch 이후 정상이다.
- 사용자 선호: "준비만"이라고 하면 학습을 돌리지 않는다. 학습·다운로드·커밋·푸시는 사용자 확인 후에만 한다.

## 5. 학습이 끝난 뒤: 모델을 게임에 붙이는 순서

```bash
RUN=data/artifacts/models/runs/20261001-093849-mobilenet_v3_small-main
model/.venv/Scripts/python -m model.evaluation.calibrate --run $RUN                 # 1. T와 기준 초안 → $RUN/calibration.json
model/.venv/Scripts/python -m model.evaluation.evaluate --run $RUN --subset select  # 2. 보고서 → $RUN/eval/validation-select-best/report.md
model/.venv/Scripts/python -m model.export.export_onnx --run $RUN                   # 3. data/artifacts/models/<modelVersion>/
python -m model.export.check_onnx --model-dir data/artifacts/models/<modelVersion> # 4. 시스템 파이썬(onnxruntime)
cd backend
python -m app.cli build-model-release --release-id <새 릴리스 ID> --model-dir ../data/artifacts/models/<modelVersion> [--recognition <기준 JSON>]  # 5
python -m app.cli assign-release --release-id <새 릴리스 ID>                          # 6. 아직 안 열리고 플레이 안 된 문제만 이동
```

- 1→3 순서를 지킨다. `export_onnx`는 같은 checkpoint·epoch의 `calibration.json`이 있으면 그 온도를 manifest에 넣고, 다른 epoch 것이면 거부한다.
- 4의 통과 기준: PyTorch 대비 최대 오차 ≤ 1e-3, Top-1 100% 일치, 배치·단건 일치(epoch 10: 4.2e-5).
- 5는 모델 해시와 출력 순서(카탈로그 345개)를 대조하고, `--recognition`이 없으면 run의 보정 초안을 판정 기준으로 쓴다. 모델 파일은 `frontend/public/models/<modelVersion>/model.onnx`(Git 제외)로 복사돼 Vite가 `/models/...`로 제공한다.
- 6에서 오늘 열렸지만 아무도 플레이하지 않은 문제까지 옮기려면 `--include-open-unplayed`(개발 전용). 플레이된 문제는 어떤 경우에도 옮기지 않는다.
- 브라우저 확인(선택): 앱 페이지 콘솔에서 `onnxSession.ts`의 `loadSession`으로 모델을 불러 `reference.npz`의 고정 그림 4장 상위 5개를 비교했다(epoch 10: 일치, 오차 ≤ 6.4e-6, 준비 0.27초, 장당 약 3ms).
- 릴리스 ID는 바꿀 때마다 새로 만든다(예: `model-dev-e20-v1`). 등록된 릴리스의 파일·DB 행은 수정하지 않는다.

## 6. epoch 10 모델 분석 결과 (보정용 절반, 172,188장)

- T = 1.036(ECE 1.55% → 1.15%). 확률은 원래도 크게 치우치지 않았다.
- 기준별 잘못된 성공 / 그림 한 장 성공률: p1 ≥ 0.5 → 17% / 58%, 0.7 → 10% / 48%, 0.9 → 4% / 32%.
- 잘못된 성공 ≤ 5%를 지키면 τ_성공 = 0.9이고, 데일리 후보 323개 중 154개가 그림 한 장 성공률 30% 미만이다.
- 잘 헷갈리는 쌍: 오토바이→자전거 47%, 허리케인→토네이도 46%(통합 보류 쌍), 야구공→농구공 26%, 밴→버스 23%, 여권→책 23%(통합 보류 쌍), 컴퓨터→노트북 22%, 육각형→팔각형 22%, 기타→바이올린 21%.
- 사실상 맞힐 수 없는 데일리 정답: 허리케인, 마커펜, 연못(성공률 0%), 정원 호스·곰·항공모함·키보드(1% 미만).
- 통합해 둔 쌍(생일 케이크→케이크, 버스→통학버스, 커피잔·컵→머그잔 등)은 실제로 가장 많이 헷갈렸다. 카테고리 정리가 맞았다는 근거다.

## 7. 사용자 결정이 필요한 것

1. **잘못된 성공 목표**(5%·10% 등) → τ_성공. 현재 배정된 릴리스는 0.9(엄격)다. 느슨한 기준으로 바꾸려면 기준 JSON을 만들어 새 릴리스로 등록한다(인수인계서 2의 §3.1).
2. **맞히기 어려운 데일리 정답** 처리: 제외할지, 통합할지(허리케인/토네이도, 여권/책, 오토바이/자전거 등). 카탈로그 변경은 버전·점수표·모델 출력까지 영향이 크다.
3. 학습 재개 시점(사용자가 PC를 다른 작업에 쓰는 중이면 기다린다).

## 8. 다음 작업 후보

- 학습 마무리 → 5절 순서로 새 릴리스. 마지막에 테스트 분할 평가 1회(`--split test --final`).
- 비교 실험: stem stride 1(해상도 유지, 약 2.3배 느림), Conv1D+BiLSTM(획 순서 데이터셋 필요).
- 실제 그림판 그림 평가셋(현재 평가는 Quick Draw뿐), 사용자 획 간소화 실험.
- 학습 스크립트가 최고 epoch를 검증 선택용 절반으로만 고르게 바꾸기(보정용 절반 누수 제거).
- 학습용 그림 수집은 꺼져 있다(`collection-disabled-v0`). 재학습 루프를 돌리려면 수집·검수 기능이 먼저 필요하다.

## 9. 관련 파일

| 파일 | 역할 |
|---|---|
| `model/datasets/preprocess.py` | 64px 렌더 규칙(기준 정의) |
| `model/datasets/build_manifest.py` | 데이터셋 빌드·표본·분할 |
| `model/datasets/sketch_dataset.py` | 배치 공급(GPU/RAM/mmap), GPU 증강 |
| `model/networks/sketch_classifier.py` | 작은 CNN, MobileNetV3-Small(1채널) |
| `model/training/train.py` | 학습·기록·재개·조기 종료 |
| `model/evaluation/evaluate.py` · `calibrate.py` | 평가 보고서, 온도·기준 초안 |
| `model/export/export_onnx.py` · `check_onnx.py` | ONNX 변환, 결과 일치 확인 |
| `model/tests/` | 전처리 고정값·공통 사례·표본, 데이터셋 계약, 학습 흐름 |
| `backend/app/cli.py` | `build-model-release`, `assign-release`, `metrics` |
| `frontend/src/features/inference/` | `preprocess.ts`, `modelRuntime.ts`, `onnxSession.ts`, `useModelSession.ts` |
| `scripts/quickdraw_data.py` | `download-full`(전체 원본), 기존 1k 다운로드·28px 처리 |
