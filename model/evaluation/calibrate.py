"""Temperature scaling and threshold candidates on the calibration half of validation (docs §7.3, judging §4).

    model/.venv/Scripts/python -m model.evaluation.calibrate --run data/artifacts/models/runs/<runId>

1. T minimises the negative log-likelihood of softmax(logits / T) over all 345 raw classes.
2. With T applied and probabilities summed into game candidates (like the browser), it tabulates p1 thresholds:
   - success: the smallest tau whose false-success share (drawings ending the game that are not the answer)
     is at most --max-false-success overall;
   - recognition (deferral): the largest tau that defers at most --max-deferral of drawings.
3. Writes <run>/calibration.json with T, before/after NLL and ECE, the tables and a draft recognition config.

The draft is a proposal for a reviewed recognition version, not an operating value by itself. The "calibrate"
half was still part of the validation data that chose the best epoch during training (slightly optimistic).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from model.evaluation.evaluate import ROOT, load_catalog, predict, softmax, threshold_table


def nll(logits: np.ndarray, labels: np.ndarray, temperature: float) -> float:
    z = logits.astype(np.float64) / temperature
    z -= z.max(axis=1, keepdims=True)
    log_norm = np.log(np.exp(z).sum(axis=1))
    return float((log_norm - z[np.arange(len(labels)), labels]).mean())


def fit_temperature(logits: np.ndarray, labels: np.ndarray, lo: float = 0.3, hi: float = 5.0) -> float:
    """Golden-section search on log T (NLL is unimodal in T for a fixed model)."""
    a, b = np.log(lo), np.log(hi)
    g = (np.sqrt(5) - 1) / 2
    c, d = b - g * (b - a), a + g * (b - a)
    fc, fd = nll(logits, labels, np.exp(c)), nll(logits, labels, np.exp(d))
    for _ in range(40):
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - g * (b - a)
            fc = nll(logits, labels, np.exp(c))
        else:
            a, c, fc = c, d, fd
            d = a + g * (b - a)
            fd = nll(logits, labels, np.exp(d))
    return float(np.exp((a + b) / 2))


def ece(p1: np.ndarray, correct: np.ndarray, bins: int = 15) -> float:
    edges = np.linspace(0, 1, bins + 1)
    total = 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (p1 > lo) & (p1 <= hi)
        if m.any():
            total += m.mean() * abs(correct[m].mean() - p1[m].mean())
    return float(total)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--checkpoint", default="best", choices=["best", "last"])
    ap.add_argument("--max-false-success", type=float, default=0.05)
    ap.add_argument("--max-deferral", type=float, default=0.05)
    args = ap.parse_args(argv)
    run_dir = args.run if args.run.is_absolute() else ROOT / args.run

    pred = predict(run_dir, args.checkpoint, "validation")
    keep = pred["odd"].astype(bool)  # the calibration half
    logits, labels = pred["logits"][keep], pred["labels"][keep]
    catalog = load_catalog()
    merge = catalog.merge_matrix()

    def game_view(temperature: float):
        probs = softmax(logits, temperature) @ merge
        top = probs.argmax(axis=1)
        p1 = probs[np.arange(len(top)), top]
        return p1, top == catalog.raw_to_service[labels]

    temperature = fit_temperature(logits, labels)
    p1_before, correct_before = game_view(1.0)
    p1, correct = game_view(temperature)

    taus = np.round(np.arange(0.05, 0.96, 0.05), 2)
    table = threshold_table(p1, correct, taus)
    for row in table:
        row["falseSuccess"] = None if row["precision"] is None else 1 - row["precision"]
        row["deferral"] = float((p1 < row["tau"]).mean())
    success_ok = [r for r in table if r["falseSuccess"] is not None and r["falseSuccess"] <= args.max_false_success]
    deferral_ok = [r for r in table if r["deferral"] <= args.max_deferral]
    tau_success = success_ok[0]["tau"] if success_ok else None
    tau_recognition = deferral_ok[-1]["tau"] if deferral_ok else None

    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    result = {
        "runId": run_dir.name, "checkpoint": args.checkpoint, "epoch": pred["epoch"],
        "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data": {"split": "validation", "subset": "calibrate (sha256(image) odd)", "samples": int(len(labels)),
                 "dataset": run["dataset"]["version"]},
        "temperature": temperature,
        "nll": {"before": nll(logits, labels, 1.0), "after": nll(logits, labels, temperature)},
        "ece": {"before": ece(p1_before, correct_before), "after": ece(p1, correct)},
        "targets": {"maxFalseSuccess": args.max_false_success, "maxDeferral": args.max_deferral},
        "thresholds": table,
        "draft": {
            "version": f"recognition-{run_dir.name}-e{pred['epoch']}-draft", "status": "draft",
            "min_top1_p": tau_recognition, "min_top3_sum": None, "min_known_axes": 1,
            "success_min_p": tau_success, "success_min_margin": None,
            "output_calibration": {"method": "temperature", "temperature": round(temperature, 4)},
        },
        "note": "Proposal from the calibration half; review together with per-answer false success in evaluate.py.",
    }
    (run_dir / "calibration.json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n",
                                              encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("epoch", "temperature", "nll", "ece")} | {"draft": result["draft"]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
