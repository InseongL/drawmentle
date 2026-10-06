"""Evaluate a training run on validation data at the raw-class and the game-candidate level.

    model/.venv/Scripts/python -m model.evaluation.evaluate --run data/artifacts/models/runs/<runId>
    model/.venv/Scripts/python -m model.evaluation.evaluate --run ... --subset select --tau-success 0.8

Writes <run>/eval/<split>-<subset>-<checkpoint>/: metrics.json, per_class.csv and report.md (Korean summary).
Game-level numbers sum raw probabilities into the merged candidates of config/model/catalog-curation-v1.json,
like the browser runtime. The test split is refused unless --final is given: it is for one last check only.

Validation is split once, by sha256(image) parity, into "select" (model selection) and "calibrate" (temperature
and thresholds, model/evaluation/calibrate.py). Identical images always land in the same half.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
LABELS = ROOT / "data/quickdraw/metadata/labels.json"
CURATION = ROOT / "config/model/catalog-curation-v1.json"
RECOGNITION = ROOT / "config/scoring/recognition.json"
SPLIT_CODES = {"train": 0, "validation": 1, "test": 2}
TAUS = (0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)


@dataclass(frozen=True)
class Catalog:
    raw_ids: list[str]            # 345, class_index order (model output order)
    service_ids: list[str]        # merged candidates, candidate_index order
    raw_to_service: np.ndarray    # [345] service index per raw class
    ko: dict[str, str]
    daily: set[str]
    held_pairs: set[tuple[str, str]]

    def merge_matrix(self) -> np.ndarray:
        m = np.zeros((len(self.raw_ids), len(self.service_ids)), np.float32)
        m[np.arange(len(self.raw_ids)), self.raw_to_service] = 1
        return m


def load_catalog() -> Catalog:
    labels = sorted(json.loads(LABELS.read_text(encoding="utf-8"))["categories"], key=lambda c: c["class_index"])
    curation = json.loads(CURATION.read_text(encoding="utf-8"))
    cats = curation["categories"]
    raw_ids = [c["category_id"] for c in labels]
    first: dict[str, int] = {}
    for i, c in enumerate(raw_ids):
        first.setdefault(cats[c]["service_id"], i)
    service_ids = sorted(first, key=first.get)
    sidx = {s: i for i, s in enumerate(service_ids)}
    held = set()
    for g in curation["groups"]:
        if g["decision"] == "hold":
            members = [m for m in [g.get("keep"), *g.get("remove", []), *g.get("members", [])] if m]
            held |= {(a, b) for a in members for b in members if a != b}
    return Catalog(raw_ids, service_ids, np.array([sidx[cats[c]["service_id"]] for c in raw_ids]),
                   {c: cats[c]["display_name_ko"] for c in raw_ids},
                   {c for c in raw_ids if cats[c]["daily_candidate"]}, held)


def subset_mask(images: np.ndarray, subset: str) -> np.ndarray:
    if subset == "all":
        return np.ones(len(images), dtype=bool)
    odd = np.fromiter((hashlib.sha256(img.tobytes()).digest()[0] & 1 for img in images), dtype=np.uint8,
                      count=len(images))
    return odd == (1 if subset == "calibrate" else 0)


def predict(run_dir: Path, checkpoint: str, split: str) -> dict:
    """Logits for a split, cached under <run>/eval as float16 (with labels and the subset parity)."""
    import torch

    from model.datasets.sketch_dataset import SketchDataset, to_input
    from model.networks.sketch_classifier import build

    ck = torch.load(run_dir / f"{checkpoint}.pt", map_location="cpu", weights_only=False)
    cfg = ck["config"]
    cache = run_dir / "eval" / f"logits-{split}-{checkpoint}-e{ck['epoch']}.npz"
    if cache.exists():
        data = np.load(cache)
        return {"logits": data["logits"], "labels": data["labels"], "recognized": data["recognized"],
                "odd": data["odd"], "epoch": ck["epoch"], "config": cfg}
    dataset_dir = ROOT / cfg["dataset"]["root"] / cfg["dataset"]["version"]
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = build(cfg["model"]["name"], **{k: v for k, v in cfg["model"].items() if k != "name"}).to(device)
    model.load_state_dict(ck["model"])
    model.eval()
    data = SketchDataset(dataset_dir, split, device)
    chunks, ys = [], []
    with torch.no_grad(), torch.autocast(device.type, dtype=torch.bfloat16, enabled=device.type == "cuda"):
        for x, y in data.batches(2048, shuffle=False):
            chunks.append(model(to_input(x)).float().cpu().numpy().astype(np.float16))
            ys.append(y.cpu().numpy())
    mask = np.load(dataset_dir / "split.npy") == SPLIT_CODES[split]
    images = np.load(dataset_dir / "images.npy", mmap_mode="r")[np.flatnonzero(mask)]
    out = {"logits": np.concatenate(chunks), "labels": np.concatenate(ys),
           "recognized": np.load(dataset_dir / "recognized.npy")[mask], "odd": subset_mask(images, "calibrate")}
    cache.parent.mkdir(parents=True, exist_ok=True)
    np.savez(cache, **out)
    return out | {"epoch": ck["epoch"], "config": cfg}


def softmax(logits: np.ndarray, temperature: float = 1.0) -> np.ndarray:
    z = logits.astype(np.float32) / temperature
    z -= z.max(axis=1, keepdims=True)
    np.exp(z, out=z)
    z /= z.sum(axis=1, keepdims=True)
    return z


def threshold_table(p1: np.ndarray, correct: np.ndarray, taus=TAUS) -> list[dict]:
    rows = []
    for t in taus:
        m = p1 >= t
        rows.append({"tau": round(float(t), 3), "coverage": float(m.mean()),
                     "precision": float(correct[m].mean()) if m.any() else None,
                     "successRate": float((m & correct).mean())})
    return rows


def evaluate(pred: dict, catalog: Catalog, subset: str, temperature: float, tau_success: float,
             tau_recognition: float) -> dict:
    keep = np.ones(len(pred["labels"]), bool) if subset == "all" else pred["odd"] == (subset == "calibrate")
    y, rec = pred["labels"][keep], pred["recognized"][keep]
    probs = softmax(pred["logits"][keep], temperature)
    raw_order = np.argsort(-probs, axis=1)[:, :3]
    raw_correct = raw_order[:, 0] == y
    s_probs = probs @ catalog.merge_matrix()
    s_order = np.argsort(-s_probs, axis=1)[:, :3]
    ys = catalog.raw_to_service[y]
    s_correct = s_order[:, 0] == ys
    p1 = s_probs[np.arange(len(ys)), s_order[:, 0]]
    bird = catalog.service_ids.index("bird")

    per_raw = []
    for i, c in enumerate(catalog.raw_ids):
        m = y == i
        confusions = Counter(raw_order[m & ~raw_correct, 0].tolist()).most_common(2)
        per_raw.append({"categoryId": c, "nameKo": catalog.ko[c], "n": int(m.sum()),
                        "top1": float(raw_correct[m].mean()),
                        "confusedWith": [[catalog.raw_ids[j], round(n / max(m.sum(), 1), 3)] for j, n in confusions]})
    success = s_correct & (p1 >= tau_success)
    per_service = []
    for k, s in enumerate(catalog.service_ids):
        m = ys == k
        if not m.any():
            continue
        wrong = Counter(s_order[m & ~s_correct, 0].tolist()).most_common(3)
        predicted_as = s_order[:, 0] == k
        confident = predicted_as & (p1 >= tau_success)
        per_service.append({
            "serviceId": s, "nameKo": catalog.ko[s], "daily": s in catalog.daily, "n": int(m.sum()),
            "top1": float(s_correct[m].mean()), "successRate": float(success[m].mean()),
            # Of the drawings that would end a game whose answer is s, the share drawn as something else.
            "falseSuccess": float((ys[confident] != k).mean()) if confident.any() else None,
            "confusedWith": [[catalog.service_ids[j], round(n / m.sum(), 3)] for j, n in wrong]})

    pairs = Counter(zip(ys[~s_correct].tolist(), s_order[~s_correct, 0].tolist()))
    counts = Counter(ys.tolist())
    top_pairs = []
    for (a, b), n in sorted(pairs.items(), key=lambda kv: -kv[1] / counts[kv[0][0]])[:25]:
        sa, sb = catalog.service_ids[a], catalog.service_ids[b]
        top_pairs.append({"true": sa, "predicted": sb, "share": round(n / counts[a], 3),
                          "held": (sa, sb) in catalog.held_pairs})
    return {
        "samples": int(len(y)), "subset": subset, "temperature": temperature,
        "raw": {"top1": float(raw_correct.mean()), "top3": float((raw_order == y[:, None]).any(1).mean())},
        "service": {"count": len(catalog.service_ids), "top1": float(s_correct.mean()),
                    "top3": float((s_order == ys[:, None]).any(1).mean())},
        "recognized": {"trueShare": float(rec.mean()), "top1WhenTrue": float(raw_correct[rec].mean()),
                       "top1WhenFalse": float(raw_correct[~rec].mean()) if (~rec).any() else None},
        "thresholds": threshold_table(p1, s_correct),
        "deferral": {"tauRecognition": tau_recognition, "lowConfidence": float((p1 < tau_recognition).mean()),
                     "unsupportedInTop3": float((s_order == bird).any(1).mean())},
        "tauSuccess": tau_success,
        "perRawClass": per_raw, "perService": per_service, "topConfusions": top_pairs,
    }


def report_markdown(m: dict, run_id: str, epoch: int, checkpoint: str, split: str) -> str:
    pct = lambda v: "—" if v is None else f"{v * 100:.1f}%"  # noqa: E731
    daily = sorted((s for s in m["perService"] if s["daily"]), key=lambda s: s["successRate"])
    lines = [
        f"# 평가 보고서 — {run_id} ({checkpoint}, epoch {epoch})",
        "",
        f"- 데이터: {split} / {m['subset']} ({m['samples']:,}장), 온도 T = {m['temperature']:.3f}",
        f"- 원본 345개: top-1 {pct(m['raw']['top1'])}, top-3 {pct(m['raw']['top3'])}",
        f"- 게임 후보 {m['service']['count']}개(통합 후): top-1 {pct(m['service']['top1'])}, top-3 {pct(m['service']['top3'])}",
        f"- Google 인식 성공 그림 {pct(m['recognized']['trueShare'])}: top-1 {pct(m['recognized']['top1WhenTrue'])} / "
        f"실패 그림: {pct(m['recognized']['top1WhenFalse'])}",
        f"- 보류: p1 < {m['deferral']['tauRecognition']} {pct(m['deferral']['lowConfidence'])}, "
        f"미지원 후보(bird) Top-3 포함 {pct(m['deferral']['unsupportedInTop3'])}",
        "",
        "## 확신도 기준별 (게임 후보 기준)",
        "",
        "| 기준 p1 ≥ | 해당 비율 | 그중 정답 비율 | 전체 중 성공 비율 |",
        "|---|---|---|---|",
        *[f"| {r['tau']} | {pct(r['coverage'])} | {pct(r['precision'])} | {pct(r['successRate'])} |" for r in m["thresholds"]],
        "",
        f"## 데일리 정답 후보 중 성공하기 가장 어려운 20개 (성공 = 1위 정답 & p1 ≥ {m['tauSuccess']})",
        "",
        "| 후보 | 성공률 | top-1 | 잘못된 성공 | 주로 이렇게 읽힘 |",
        "|---|---|---|---|---|",
        *[f"| {s['nameKo']} ({s['serviceId']}) | {pct(s['successRate'])} | {pct(s['top1'])} | {pct(s['falseSuccess'])} | "
          + ", ".join(f"{c} {v * 100:.0f}%" for c, v in s["confusedWith"]) + " |" for s in daily[:20]],
        "",
        f"데일리 후보 {len(daily)}개 중 성공률 30% 미만 {sum(s['successRate'] < 0.3 for s in daily)}개, "
        f"50% 미만 {sum(s['successRate'] < 0.5 for s in daily)}개.",
        "",
        "## 많이 헷갈리는 후보 쌍 (실제 → 예측, 실제 그림 중 비율)",
        "",
        *[f"- {p['true']} → {p['predicted']}: {pct(p['share'])}" + (" (통합 보류 쌍)" if p["held"] else "")
          for p in m["topConfusions"][:15]],
        "",
    ]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--checkpoint", default="best", choices=["best", "last"])
    ap.add_argument("--split", default="validation", choices=["validation", "test"])
    ap.add_argument("--subset", default="all", choices=["all", "select", "calibrate"])
    ap.add_argument("--final", action="store_true", help="allow the test split (one final evaluation only)")
    ap.add_argument("--temperature", type=float, help="default: <run>/calibration.json, else 1.0")
    ap.add_argument("--tau-success", type=float, help="default: calibration draft, else config/scoring/recognition.json")
    ap.add_argument("--tau-recognition", type=float)
    args = ap.parse_args(argv)
    if args.split == "test" and not args.final:
        raise SystemExit("the test split is reserved for one final check; pass --final when that is intended")

    run_dir = args.run if args.run.is_absolute() else ROOT / args.run
    calibration = json.loads((run_dir / "calibration.json").read_text(encoding="utf-8")) \
        if (run_dir / "calibration.json").exists() else None
    rules = json.loads(RECOGNITION.read_text(encoding="utf-8"))
    temperature = args.temperature or (calibration["temperature"] if calibration else 1.0)
    draft = calibration["draft"] if calibration else {}
    tau_success = args.tau_success or draft.get("success_min_p") or rules["success_min_p"]
    tau_recognition = args.tau_recognition or draft.get("min_top1_p") or rules["min_top1_p"]

    pred = predict(run_dir, args.checkpoint, args.split)
    metrics = evaluate(pred, load_catalog(), args.subset, temperature, tau_success, tau_recognition)
    out = run_dir / "eval" / f"{args.split}-{args.subset}-{args.checkpoint}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    with open(out / "per_class.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["serviceId", "nameKo", "daily", "n", "top1", "successRate", "falseSuccess", "confusedWith"])
        for s in metrics["perService"]:
            w.writerow([s["serviceId"], s["nameKo"], s["daily"], s["n"], f"{s['top1']:.4f}", f"{s['successRate']:.4f}",
                        "" if s["falseSuccess"] is None else f"{s['falseSuccess']:.4f}",
                        "; ".join(f"{c}:{v}" for c, v in s["confusedWith"])])
    (out / "report.md").write_text(report_markdown(metrics, run_dir.name, pred["epoch"], args.checkpoint, args.split),
                                   encoding="utf-8")
    print(json.dumps({"out": str(out.relative_to(ROOT)) if out.is_relative_to(ROOT) else str(out),
                      "raw": metrics["raw"], "service": metrics["service"], "temperature": temperature,
                      "tauSuccess": tau_success}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
