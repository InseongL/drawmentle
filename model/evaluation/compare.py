"""Compare a candidate model with the champion on the same data and apply the promotion gates (docs/mlops-v1.md §6).

    model/.venv/Scripts/python -m model.evaluation.compare --candidate data/artifacts/models/runs/<run> \\
        [--champion <run>] [--user-dataset user-<id>]

Data: the base dataset's validation split (gates.eval_subset half; the champion never trained on it) and, when given,
the user dataset's test split (real-canvas drawings neither model trained on). Each model uses its own calibrated
temperature; both are judged at the same success threshold (the candidate's calibration draft by default).
Gates come from config/mlops/mlops.json. A gate without enough data is "pending" and does not block; the ONNX gate is
added by the pipeline after check_onnx. Writes <candidate>/eval/compare-<champion>/compare.json and report.md.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from model.evaluation.evaluate import Catalog, load_catalog, predict_dataset, softmax

ROOT = Path(__file__).resolve().parents[2]
MLOPS_CONFIG = ROOT / "config/mlops/mlops.json"
DATASETS = ROOT / "data/datasets"


def calibration(run_dir: Path) -> dict:
    path = run_dir / "calibration.json"
    if not path.exists():
        raise SystemExit(f"{run_dir.name}: run calibrate first (no calibration.json)")
    return json.loads(path.read_text(encoding="utf-8"))


def metrics(pred: dict, catalog: Catalog, mask: np.ndarray, temperature: float, tau: float) -> dict:
    if not mask.any():
        return {"n": 0}
    probs = softmax(pred["logits"][mask], temperature) @ catalog.merge_matrix()
    ys = catalog.raw_to_service[pred["labels"][mask]]
    order = np.argsort(-probs, axis=1)[:, :3]
    top, p1 = order[:, 0], probs[np.arange(len(ys)), order[:, 0]]
    ok, conf = top == ys, p1 >= tau
    daily = {}
    for k, sid in enumerate(catalog.service_ids):
        m = ys == k
        if sid in catalog.daily and m.any():
            daily[sid] = float((ok & conf)[m].mean())
    return {"n": int(mask.sum()), "top1": float(ok.mean()), "top3": float((order == ys[:, None]).any(1).mean()),
            "falseSuccess": float(1 - ok[conf].mean()) if conf.any() else None,
            "successRate": float((ok & conf).mean()), "daily": daily}


def gate(name: str, ok: bool | None, detail: str) -> dict:
    return {"gate": name, "status": "pending" if ok is None else "pass" if ok else "fail", "detail": detail}


def evaluate_gates(champ: dict, cand: dict, g: dict) -> list[dict]:
    """Pure function of the two metric sets and config/mlops/mlops.json `gates`."""
    cb, kb = champ["base"], cand["base"]
    out = [gate("top1", kb["top1"] >= cb["top1"] - g["max_top1_drop"],
                f"{kb['top1']:.4f} vs champion {cb['top1']:.4f} (allowed drop {g['max_top1_drop']})"),
           gate("false_success", kb["falseSuccess"] is not None and kb["falseSuccess"] <= g["max_false_success"],
                f"{kb['falseSuccess']:.4f} <= {g['max_false_success']}" if kb["falseSuccess"] is not None
                else "no confident predictions")]
    below = sorted(s for s, r in kb["daily"].items() if r < g["daily_floor_rate"])
    out.append(gate("daily_floor", len(below) <= g["max_daily_below_floor"],
                    f"{len(below)} daily answers below {g['daily_floor_rate']:.0%}: {below[:10]}"))
    drops = sorted(((cb["daily"][s] - r, s) for s, r in kb["daily"].items() if s in cb["daily"]), reverse=True)
    worst = drops[0] if drops else (0.0, None)
    out.append(gate("answer_regression", worst[0] <= g["max_answer_regression"],
                    f"largest drop {worst[0]:.3f} ({worst[1]}) <= {g['max_answer_regression']}"))
    cu, ku = champ.get("user", {"n": 0}), cand.get("user", {"n": 0})
    if ku["n"] < g["min_user_eval_samples"]:
        out.append(gate("user_top1", None, f"{ku['n']} real-canvas drawings < {g['min_user_eval_samples']}"))
    else:
        out.append(gate("user_top1", ku["top1"] - cu["top1"] >= g["min_user_top1_gain"],
                        f"{ku['top1']:.4f} vs champion {cu['top1']:.4f} (min gain {g['min_user_top1_gain']})"))
    return out


def passed(gates: list[dict]) -> bool:
    return all(g["status"] != "fail" for g in gates)


def report(result: dict) -> str:
    pct = lambda v: "-" if v is None else f"{v * 100:.1f}%"  # noqa: E731
    rows = []
    for part in ("base", "user"):
        c, k = result["champion"].get(part, {"n": 0}), result["candidate"].get(part, {"n": 0})
        if k.get("n"):
            rows.append(f"| {part} ({k['n']:,}) | {pct(c.get('top1'))} → {pct(k['top1'])} | "
                        f"{pct(c.get('top3'))} → {pct(k['top3'])} | {pct(c.get('falseSuccess'))} → "
                        f"{pct(k['falseSuccess'])} | {pct(c.get('successRate'))} → {pct(k['successRate'])} |")
    lines = [f"# 모델 비교 — {result['candidate']['run']} vs 챔피언 {result['champion']['run']}", "",
             f"- 성공 기준 τ = {result['tau']}, 온도 챔피언 {result['champion']['temperature']:.3f} / "
             f"후보 {result['candidate']['temperature']:.3f}",
             f"- 결과: **{'통과' if result['passed'] else '불합격'}**", "",
             "| 자료 | top-1 | top-3 | 잘못된 성공 | 한 장 성공 |", "|---|---|---|---|---|", *rows, "",
             "| 기준 | 결과 | 내용 |", "|---|---|---|",
             *[f"| {g['gate']} | {g['status']} | {g['detail']} |" for g in result["gates"]]]
    return "\n".join(lines) + "\n"


def compare(champion: Path, candidate: Path, base: str, user: str | None, subset: str, gates_cfg: dict,
            tau: float | None = None, checkpoint: str = "best") -> dict:
    catalog = load_catalog()
    cal_c, cal_k = calibration(champion), calibration(candidate)
    tau = tau or cal_k["draft"]["success_min_p"]
    result = {"tau": tau}
    for role, run_dir, cal in (("champion", champion, cal_c), ("candidate", candidate, cal_k)):
        pred = predict_dataset(run_dir, checkpoint, DATASETS / base, "validation")
        mask = np.ones(len(pred["labels"]), bool) if subset == "all" else pred["odd"] == (subset == "calibrate")
        entry = {"run": run_dir.name, "temperature": cal["temperature"],
                 "base": metrics(pred, catalog, mask, cal["temperature"], tau)}
        if user:
            upred = predict_dataset(run_dir, checkpoint, DATASETS / user, "test")
            entry["user"] = metrics(upred, catalog, np.ones(len(upred["labels"]), bool), cal["temperature"], tau)
        result[role] = entry
    result["gates"] = evaluate_gates(result["champion"], result["candidate"], gates_cfg)
    result["passed"] = passed(result["gates"])
    return result


def main(argv=None) -> int:
    cfg = json.loads(MLOPS_CONFIG.read_text(encoding="utf-8"))
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--candidate", type=Path, required=True)
    ap.add_argument("--champion", type=Path, default=Path(cfg["champion"]["run"]))
    ap.add_argument("--base-dataset", default=cfg["dataset"]["base_version"])
    ap.add_argument("--user-dataset", help="user dataset version whose test split is the real-canvas check")
    ap.add_argument("--tau-success", type=float)
    args = ap.parse_args(argv)
    champion = args.champion if args.champion.is_absolute() else ROOT / args.champion
    candidate = args.candidate if args.candidate.is_absolute() else ROOT / args.candidate
    result = compare(champion, candidate, args.base_dataset, args.user_dataset, cfg["gates"]["eval_subset"],
                     cfg["gates"], args.tau_success, cfg["champion"].get("checkpoint", "best"))
    out = candidate / "eval" / f"compare-{champion.name}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "compare.json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (out / "report.md").write_text(report(result), encoding="utf-8")
    print(json.dumps({"out": str(out), "passed": result["passed"],
                      "gates": {g["gate"]: g["status"] for g in result["gates"]}}, ensure_ascii=False))
    return 0 if result["passed"] else 3


if __name__ == "__main__":
    sys.exit(main())
