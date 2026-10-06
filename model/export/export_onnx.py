"""Export a training checkpoint to ONNX with its model manifest and reference outputs.

    model/.venv/Scripts/python -m model.export.export_onnx --run data/artifacts/models/runs/<runId>
    python -m model.export.check_onnx --model-dir data/artifacts/models/<modelVersion>    # needs onnxruntime only

Output data/artifacts/models/<modelVersion>/ (untracked):
- model.onnx       input "image" float32 [batch, 1, 64, 64] (background 0, ink 1), output "logits" [batch, 345].
                   No softmax or temperature inside: the browser runtime applies softmax(logits / T) (docs §6.1).
- model-manifest.json  version, file hash, input/output, preprocessing, class order, temperature, source run.
- reference.npz    inputs and PyTorch logits for the ONNX parity check.
Requires the `onnx` package for torch.onnx.export.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch

from model.datasets.preprocess import QD_STROKES_64_V1, render
from model.datasets.sketch_dataset import SketchDataset, to_input
from model.networks.sketch_classifier import build

ROOT = Path(__file__).resolve().parents[2]
OPSET = 17
REFERENCE_DRAWINGS = [
    [[[0, 100, 100, 0, 0], [0, 0, 100, 100, 0]]],
    [[[0, 255], [120, 120]]],
    [[[10, 60], [10, 80]], [[200], [30]]],
    [[[5], [5]]],
]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--checkpoint", default="best", choices=["best", "last"])
    ap.add_argument("--reference-samples", type=int, default=256)
    args = ap.parse_args(argv)
    run_dir = args.run if args.run.is_absolute() else ROOT / args.run

    ck = torch.load(run_dir / f"{args.checkpoint}.pt", map_location="cpu", weights_only=False)
    cfg = ck["config"]
    model = build(cfg["model"]["name"], **{k: v for k, v in cfg["model"].items() if k != "name"})
    model.load_state_dict(ck["model"])
    model.eval()
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    classes = json.loads((run_dir / "classes.json").read_text(encoding="utf-8"))
    calibration_path = run_dir / "calibration.json"
    calibration = json.loads(calibration_path.read_text(encoding="utf-8")) if calibration_path.exists() else None
    if calibration and (calibration["checkpoint"], calibration["epoch"]) != (args.checkpoint, ck["epoch"]):
        raise SystemExit("calibration.json belongs to another checkpoint; rerun model.evaluation.calibrate first")

    version = f"{cfg['model']['name']}-{run_dir.name[:15]}-e{ck['epoch']}"
    out = ROOT / "data/artifacts/models" / version
    out.mkdir(parents=True, exist_ok=True)
    onnx_path = out / "model.onnx"
    torch.onnx.export(model, (torch.zeros(1, 1, 64, 64),), str(onnx_path), dynamo=False, opset_version=OPSET,
                      input_names=["image"], output_names=["logits"],
                      dynamic_axes={"image": {0: "batch"}, "logits": {0: "batch"}})

    # Reference inputs: fixed drawings plus validation images, with PyTorch float32 logits.
    dataset_dir = ROOT / cfg["dataset"]["root"] / cfg["dataset"]["version"]
    val = SketchDataset(dataset_dir, "validation", torch.device("cpu"), "mmap")
    x_val, _ = next(val.batches(args.reference_samples, shuffle=False))
    drawings = torch.from_numpy(np.stack([render(d) for d in REFERENCE_DRAWINGS]))
    inputs = to_input(torch.cat([drawings, x_val]))
    with torch.no_grad():
        logits = model(inputs)
    np.savez(out / "reference.npz", inputs=inputs.numpy(), logits=logits.numpy())

    spec = QD_STROKES_64_V1
    manifest = {
        "modelVersion": version,
        "format": "onnx", "opset": OPSET, "file": "model.onnx",
        "bytes": onnx_path.stat().st_size, "sha256": sha256_file(onnx_path),
        "input": {"name": "image", "dtype": "float32", "shape": [1, 1, spec.size, spec.size], "layout": "NCHW",
                  "values": "0..1, background 0, ink 1 (uint8 render / 255)"},
        "output": {"name": "logits", "dtype": "float32", "shape": [1, len(classes["classIds"])],
                   "kind": "raw logits in class_index order; apply softmax(logits / temperature) over all outputs"},
        "preprocessing": {"version": spec.version, "size": spec.size, "span": spec.span, "radius": spec.radius,
                          "supersample": spec.supersample},
        "classes": {"count": len(classes["classIds"]), "sha256": classes["sha256"]},
        "outputCalibration": {"method": "temperature", "temperature": round(calibration["temperature"], 4)}
        if calibration else {"method": "none", "temperature": 1.0},
        "source": {"runId": run_dir.name, "checkpoint": args.checkpoint, "epoch": ck["epoch"],
                   "configSha256": run["configSha256"], "dataset": run["dataset"]["version"],
                   "validation": ck.get("val")},
        "exportedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "exportedWith": {"torch": torch.__version__, "exporter": "torchscript"},
    }
    (out / "model-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n",
                                             encoding="utf-8")
    print(json.dumps({"out": str(out.relative_to(ROOT)), "bytes": manifest["bytes"], "sha256": manifest["sha256"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
