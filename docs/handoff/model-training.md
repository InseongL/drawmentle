# 인수인계서 1 — 그림 인식 모델 학습

작성 2026-10-06, 같은 날 epoch 20 최종 모델 기준으로 갱신. 이 문서만 읽고 다음 모델을 학습하거나 게임에 붙일 수 있도록 정리했다. 설계 근거는 [모델 구조](../model-architecture-v1.md), 명령 상세는 [model/README.md](../../model/README.md)다.

## 0. 한눈에 보는 현재 상태

| 항목 | 상태 |
|---|---|
| 본 학습 | **끝남**(조기 종료). epoch 25에서 멈췄고 최고는 epoch 20 |
| 최고 모델 | epoch 20 — 검증 top-1 70.2%, top-3 86.1%, 게임 후보 기준 top-1 71.1%(카테고리 v1.1, 335개) / 71.6%(v1.2, 331개) |
| 게임 연결 | 릴리스 `model-dev-e20-v2`(epoch 20 + 카테고리 정리 v1.2 + `scoring-v2`)를 **2026-10-07~11-04 개발용 문제에 배정**. 10-06 문제는 이미 플레이돼서 `model-dev-e10-v1`(epoch 10)에 남았다 |
| 판정 기준 | epoch 20 보정 초안(성공 p1 ≥ 0.85, 보류 p1 < 0.15). 2026-10-06 사용자가 초안 사용을 골랐다 |
| 테스트 분할 | epoch 20으로 **한 번 평가함**(2026-10-06). 게임 후보 top-1 71.0%, τ 0.85에서 잘못된 성공 4.7%로 검증과 같다(§6). 다시 쓰지 않는다 |
| 커밋 | 마지막 코드 커밋 `61a46d9`. epoch 20 작업은 Git 제외 산출물과 개발 DB만 바꿨고, 문서는 그 결과에 맞춰 따로 고쳤다 |

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
- 검증 분할은 다시 이미지 해시 홀짝으로 **모델 선택용(select, 짝수, 172,139장)** / **보정용(calibrate, 홀수, 172,188장)**으로 나눈다(`model/evaluation/evaluate.py`의 `subset_mask`). 현재 학습 스크립트는 최고 epoch를 고를 때 검증 전체를 쓰므로 보정용 절반 결과가 약간 낙관적이다.
- **테스트 분할은 마지막 한 번만** 쓴다. `evaluate --split test`는 `--final` 없이는 거부한다. 2026-10-06 epoch 20 모델로 한 번 썼다. `--final`은 다시 돌리는 것까지 막지는 않으므로, 이 데이터셋의 테스트 결과로 모델·기준값을 다시 고르지 않는다. 다음 모델을 비교할 때는 검증 분할을 쓰고, 새 최종 평가가 필요하면 새 데이터셋 버전의 테스트 분할을 쓴다.

## 3. 본 학습 실행 기록

- run 폴더: `data/artifacts/models/runs/20261001-093849-mobilenet_v3_small-main/`(`run.json`, `history.jsonl`, `classes.json`, `last.pt`, `best.pt`, `calibration.json`, `eval/`)
- 로그: `data/artifacts/models/logs/qd-10k-64-v1.log`
- 설정: MobileNetV3-Small(1채널, stem stride 2, 187만 파라미터), 배치 512, AdamW lr 1e-3 / wd 1e-4, 1 epoch 워밍업 후 코사인(30 epoch 기준, 5,392 step/epoch), bf16 자동 혼합 정밀도, 증강(회전 ±8°, 이동 4%, 크기 0.9~1.1), 조기 종료 인내 5.
- 주의: `config/model/training.json`의 기본 데이터셋은 아직 `qd-local1k-64-v1`이다. 본 학습은 `--dataset qd-10k-64-v1`로 덮어써서 돌렸고, run에 실제 설정이 저장돼 있다. 새 학습을 시작할 때 `--dataset`을 빠뜨리지 않는다.
- 진행: 2026-10-01 시작 → epoch 3 뒤 1차 일시정지(mmap으로 재개) → epoch 11 뒤 2차 일시정지 → 2026-10-06 09:48(KST) 재개 → 11:19 조기 종료. `run.json`의 `status`는 `early_stopped`, `resumes`에 재개 두 번이 기록돼 있다. 2차 일시정지 때 적은 `pausedAt`·`note` 칸이 남아 있지만 지난 기록일 뿐이다.

| epoch | 학습 손실 | 검증 손실 | top-1 | top-3 | 비고 |
|---|---|---|---|---|---|
| 1 | 2.852 | 1.971 | 52.2% | 72.8% | |
| 3 | 1.541 | 1.674 | 58.9% | 78.2% | 1차 일시정지 → mmap으로 재개 |
| 5 | 1.387 | 1.364 | 66.2% | 83.6% | |
| 10 | 1.230 | 1.329 | 66.9% | 84.1% | 첫 게임 연결 모델(`model-dev-e10-v1`) |
| 11 | 1.208 | 1.336 | 66.7% | 84.0% | 2차 일시정지 |
| 12 | 1.187 | 1.259 | 68.5% | 85.2% | 재개 |
| 15 | 1.129 | 1.231 | 69.3% | 85.6% | |
| 18 | 1.078 | 1.213 | 70.0% | 86.0% | |
| **20** | 1.047 | **1.203** | **70.2%** | **86.1%** | best.pt, 현재 게임 모델(`model-dev-e20-v1`·`v2`) |
| 21 | 1.033 | 1.211 | 70.1% | 86.0% | |
| 25 | 0.987 | 1.209 | 70.2% | 86.1% | 5 epoch 연속 개선 없음 → 조기 종료(last.pt) |

해석: epoch 20 이후 학습 손실은 계속 줄었지만(1.05 → 0.99) 검증은 1.20~1.22, top-1 70% 근처에서 멈췄다. 이 모델 크기·64px·클래스당 1만 장 조건에서는 거의 한계다. 더 올리려면 구조나 데이터를 바꿔야 한다(§8). 재개 뒤 속도는 epoch 12~20이 6.5~7천 장/초(epoch당 약 7분), 21~25가 7.5~9천 장/초(약 5~6분)였다.

## 4. 학습 실행·재개·중지 방법

이번 run은 끝났으므로 재개할 일이 없다. 아래는 새 run을 돌리거나 다음에 멈췄다 이을 때의 방법이다.

```bash
# 새 학습 (run 폴더는 data/artifacts/models/runs/ 아래에 새로 생긴다)
model/.venv/Scripts/python -u -m model.training.train --dataset qd-10k-64-v1 --run-name <이름> >> data/artifacts/models/logs/<이름>.log 2>&1
# 멈춘 run 재개 (최대 epoch 또는 조기 종료까지)
model/.venv/Scripts/python -u -m model.training.train --resume <run 폴더> --placement mmap >> data/artifacts/models/logs/<이름>.log 2>&1
```

- **전원 확인**: 배터리로 돌면 GPU가 전력 제한(SW Power Cap)으로 클럭이 210~990MHz까지 떨어져 3배 가까이 느려진다. 확인: `nvidia-smi -q -d PERFORMANCE`, PowerShell `(Get-CimInstance Win32_Battery).BatteryStatus`(2 = 전원 연결).
- **데이터 위치**: 11GB 학습 분할을 RAM에 복사하면 Windows가 페이지 파일로 밀어내 느려진다(약 6천 장/초). 4GB 초과 분할은 기본이 mmap이고 6.5~10천 장/초가 나왔다. 재개할 때도 `--placement`로 바꿀 수 있다.
- **잠자기**: 노트북 덮개를 닫거나 절전하면 멈춘다. 에이전트는 keep-awake를 요청하고, 사용자에게 전원·덮개를 안내한다.
- **중지**: 터미널이면 Ctrl+C(현재 epoch를 last.pt로 저장). 백그라운드면 학습 프로세스 트리를 종료한다. 가상환경 실행기와 실제 파이썬 두 프로세스가 뜨므로 `taskkill /PID <venv python.exe의 PID> /T /F`. 이때 **last.pt는 epoch가 끝날 때만 저장되므로 진행 중 epoch는 버려진다**. epoch 종료 직후(로그에 `epoch N:` 줄이 찍힌 뒤) 멈추는 것이 좋다. 멈춘 뒤 `run.json`의 `status`를 `paused`로 적어 둔다.
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
- 1과 2는 같은 run의 이전 결과(`calibration.json`, `eval/validation-select-best/`)를 덮어쓴다. 비교용으로 남기려면 먼저 복사해 둔다. 평가 logits 캐시는 epoch별 파일(`eval/logits-<split>-<checkpoint>-e<N>.npz`)이라 섞이지 않는다.
- 4의 통과 기준: PyTorch 대비 최대 오차 ≤ 1e-3, Top-1 100% 일치, 배치·단건 일치(epoch 10: 4.2e-5, epoch 20: 2.6e-5).
- 5는 모델 해시와 출력 순서(카탈로그 345개)를 대조하고, `--recognition`이 없으면 run의 보정 초안을 판정 기준으로 쓴다. 모델 파일은 `frontend/public/models/<modelVersion>/model.onnx`(Git 제외)로 복사돼 Vite가 `/models/...`로 제공한다.
- 6에서 오늘 열렸지만 아무도 플레이하지 않은 문제까지 옮기려면 `--include-open-unplayed`(개발 전용). 플레이된 문제는 어떤 경우에도 옮기지 않는다.
- 브라우저 확인(선택): 고정 그림 4장(사각형, 가로선, 획 두 개, 점 하나)을 시스템 파이썬에서 `model.datasets.preprocess.render` + onnxruntime으로 돌려 상위 5개 logits를 기대값으로 만든다. 앱 페이지(개발 서버) 콘솔에서 `onnxSession.ts`의 `loadSession`과 `preprocess.ts`로 같은 그림을 돌려 비교한다. 기대값을 소수 다섯째 자리로 반올림하므로 오차 1e-5 안팎이면 일치다.
    - epoch 10: 상위 5개 일치, 오차 ≤ 6.4e-6, 준비 0.27초, 장당 약 3ms
    - epoch 20: 상위 5개 일치, 오차 ≤ 9.9e-6, 준비 0.09초, 첫 실행 28ms 뒤 장당 5~8ms, 해시 확인 통과
- 릴리스 ID는 바꿀 때마다 새로 만든다. 등록된 릴리스의 파일·DB 행은 수정하지 않는다.

### 5.1 epoch 20 적용 기록 (2026-10-06)

| 단계 | 결과 |
|---|---|
| 1. 보정 | T = 1.093, ECE 2.51% → 0.92%. 초안: 성공 p1 ≥ 0.85, 보류 p1 < 0.15 |
| 2. 평가 | 기본 보고서(τ 0.85)와 비교용 τ 0.9 보고서(`eval/validation-select-best-tau090/`) |
| 3. 내보내기 | `data/artifacts/models/mobilenet_v3_small-20261001-093849-e20/`, 7,494,398 bytes, sha256 `0083a705…3739c8`, manifest에 T 1.093 |
| 4. 확인 | 260장, 최대 오차 2.6e-5, Top-1·Top-3 100% 일치, 배치·단건 차이 0 → 통과 |
| 5. 릴리스 | `model-dev-e20-v1`, 판정 기준 `recognition-20261001-093849-mobilenet_v3_small-main-e20-draft` |
| 6. 배정 | `--include-open-unplayed`로 10-07~11-04의 29개 이동. 10-06은 플레이돼서 유지 |
| 브라우저 확인 | 고정 그림 4장 상위 5개 일치, 오차 ≤ 9.9e-6. 릴리스 manifest의 모델 주소·해시·온도가 확인한 파일과 같음 |
| 테스트 평가 | `evaluate --split test --final` 1회 → `eval/test-all-best/`(§6) |
| 카테고리 v1.2 | 통합 4쌍·데일리 제외 7개 → `scoring-v2` → 보정·평가 다시(τ 0.85 유지) → 릴리스 `model-dev-e20-v2`, 10-07~11-04 배정. v1.1 기준 결과는 `eval/calibration-e20-catalog-v1.1.json`, `eval/validation-select-best-catalog-v1.1/` |

epoch 10 때의 결과는 같은 run의 `eval/calibration-e10.json`, `eval/validation-select-best-e10/`에 보관했다.

## 6. epoch 20 모델 분석 결과

### 확신도 기준별 (보정용 절반 172,188장, `calibration.json`)

| 성공 기준 p1 ≥ | epoch 20 잘못된 성공 / 그림 한 장 성공 | epoch 10 |
|---|---|---|
| 0.5 | 15.6% / 62.5% | 17.2% / 58.2% |
| 0.7 | 8.8% / 52.7% | 10.0% / 48.1% |
| **0.85** | **4.7% / 42.1%** | 5.5% / 37.5% |
| 0.9 | 3.4% / 36.7% | 4.0% / 32.2% |

- 잘못된 성공 = 성공으로 끝날 그림 중 실제로는 다른 것. 잘못된 성공 ≤ 5%를 지키는 가장 낮은 기준이 epoch 10은 0.9, epoch 20은 0.85다. 그래서 초안이 0.85로 내려왔다.
- 보류(p1 < 0.15) 3.6%(epoch 10: 4.0%).
- 온도 T = 1.093으로 epoch 10(1.036)보다 조금 커졌다. 학습이 길어지며 확률이 약간 과신 쪽으로 갔고, 보정 뒤 ECE는 0.92%로 더 좋다.

### 정확도와 어려운 정답 (모델 선택용 절반 172,139장, 보고서)

- 원본 345개 top-1 70.3% / top-3 86.1%, 게임 후보 335개 top-1 71.1% / top-3 86.3%(epoch 10: 67.8% / 84.4%).
- Google이 인식에 성공한 그림(91.7%) top-1 74.8%, 실패한 그림 19.9%. 미지원 후보(bird)가 Top-3에 들어간 비율 1.2%.
- 데일리 후보 323개 중 그림 한 장 성공률 30% 미만: **τ 0.85 기준 92개**(50% 미만 195개), τ 0.9 기준 128개(epoch 10은 154개).
- 사실상 맞힐 수 없는 데일리 정답(τ 0.85): 마커펜 0%, 연못 1.0%, 허리케인 1.1%, 토네이도 1.2%, 항공모함 1.6%, 곰 2.0%, 정원 호스 2.4%.
- 토네이도는 top-1이 67%인데도 성공률이 1%다. 허리케인과 확률을 나눠 가져 p1이 기준까지 오르지 못한다. 헷갈리는 쌍은 1위를 맞혀도 확신도에서 막힌다. 통합 여부를 판단할 때 이 점을 본다.
- 잘 헷갈리는 쌍(실제 → 예측): 허리케인→토네이도 32.0%(epoch 10: 46%, 통합 보류 쌍), 오토바이→자전거 28.5%(47%), 바이올린→기타 24.7%, 토네이도→허리케인 24.5%, 밴→버스 24.1%, 라디오→스테레오 23.0%, 팔각형→육각형 20.7%, 재킷→스웨터 18.2%, 바이올린→첼로 18.2%(통합 보류 쌍), 소방차→버스 18.1%.
- 통합해 둔 쌍(생일 케이크→케이크, 버스→통학버스, 커피잔·컵→머그잔 등)은 epoch 10에서 실제로 가장 많이 헷갈렸다. 카테고리 정리가 맞았다는 근거다.

### 테스트 분할 최종 평가 (344,730장, 1회, `eval/test-all-best/report.md`)

| | 검증 | 테스트 |
|---|---|---|
| 원본 345개 top-1 / top-3 | 70.3% / 86.1% | 70.1% / 86.2% |
| 게임 후보 335개 top-1 / top-3 | 71.1% / 86.3% | 71.0% / 86.4% |
| τ 0.85 잘못된 성공 / 한 장 성공 | 4.7% / 42.1% | 4.7% / 42.0% |
| τ 0.9 잘못된 성공 / 한 장 성공 | 3.4% / 36.7% | 3.4% / 36.7% |
| 보류(p1 < 0.15) | 3.6% | 3.5% |
| 데일리 정답 중 성공률 30% 미만(τ 0.85) | 92개 | 88개 |

- 검증과 차이가 0.2%p 이내다. 검증으로 고른 epoch·온도·기준값이 처음 보는 Quick Draw 그림에서도 그대로 통한다.
- 테스트에서도 성공률이 가장 낮은 정답은 마커펜 0.5%, 허리케인 1.0%, 연못 1.5%, 토네이도 1.8%, 정원 호스·항공모함 2.3%, 곰 3.3%다. 헷갈리는 쌍도 같다(허리케인→토네이도 25.9%, 오토바이→자전거 25.6%, 바이올린→기타 21.5%·첼로 19.8%).
- 테스트도 Quick Draw 그림뿐이다. 실제 그림판 그림에서의 성능은 아직 모른다.

## 7. 사용자 결정이 필요한 것

1. ~~운영용 잘못된 성공 목표~~: 2026-10-06 운영 시작값을 τ_성공 0.85, τ_인식 0.15로 정했다([판정 기준 §4.2](../judging-criteria-v1.md)). 실제 그림판 그림 평가와 출시 뒤 `metrics`(`near%` 등)로 0.75까지 낮출지 판단한다. 바꾸려면 기준 JSON을 만들어 새 릴리스로 등록한다(인수인계서 2의 §3.1).
2. ~~맞히기 어려운 데일리 정답~~: 2026-10-06 [카테고리 정리 v1.2](../catalog-curation-v1.md)로 처리했다. 헷갈리는 짝 4개 통합(허리케인→토네이도, 첼로→바이올린, 크레용→연필, 오토바이→자전거), 인식이 너무 어려운 7개를 정답에서 제외. 데일리 312개 중 성공률 5% 미만 0개, 30% 미만 79개. 통합·제외는 브라우저 합산과 점수표만 바꾸므로 재학습은 필요 없다. 성공률 5~10%인 10개는 실제 플레이 정답률을 보고 다시 정한다.

## 8. 다음 작업 후보

- 10-07 문제가 열리면 실제 게임 화면에서 epoch 20 판정 흐름 확인(브라우저 단독 비교는 끝남).
- 비교 실험: stem stride 1(해상도 유지, 약 2.3배 느림), Conv1D+BiLSTM(획 순서 데이터셋 필요). 현재 구조는 top-1 70% 근처에서 한계라 정확도를 더 올리려면 이쪽이다.
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
