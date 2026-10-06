"""Compare an exported ONNX model with the PyTorch reference outputs (needs numpy + onnxruntime, not torch).

    python -m model.export.check_onnx --model-dir data/artifacts/models/<modelVersion>

Checks the file hash against model-manifest.json, the maximum absolute logit difference, top-1 / top-3 agreement
and that batch-1 runs equal the batched run. Writes onnx-check.json next to the model; exits 1 on failure.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

MAX_ABS_DIFF = 1e-3


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model-dir", type=Path, required=True)
    args = ap.parse_args(argv)
    import onnxruntime as ort

    folder = args.model_dir
    manifest = json.loads((folder / "model-manifest.json").read_text(encoding="utf-8"))
    model_path = folder / manifest["file"]
    if hashlib.sha256(model_path.read_bytes()).hexdigest() != manifest["sha256"]:
        raise SystemExit("model.onnx does not match the manifest hash")
    ref = np.load(folder / "reference.npz")
    session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
    batched = session.run([manifest["output"]["name"]], {manifest["input"]["name"]: ref["inputs"]})[0]
    single = np.concatenate([session.run(None, {manifest["input"]["name"]: ref["inputs"][i:i + 1]})[0]
                             for i in range(len(ref["inputs"]))])
    diff = float(np.abs(batched - ref["logits"]).max())
    batch_diff = float(np.abs(batched - single).max())
    top1 = float((batched.argmax(1) == ref["logits"].argmax(1)).mean())
    top3 = float(np.mean([set(a) == set(b) for a, b in zip(np.argsort(-batched, 1)[:, :3],
                                                            np.argsort(-ref["logits"], 1)[:, :3])]))
    ok = diff <= MAX_ABS_DIFF and batch_diff <= MAX_ABS_DIFF and top1 == 1.0
    result = {"modelVersion": manifest["modelVersion"], "samples": int(len(ref["inputs"])),
              "maxAbsDiff": diff, "batchVsSingleMaxAbsDiff": batch_diff, "top1Agreement": top1,
              "top3SetAgreement": top3, "onnxruntime": ort.__version__, "passed": ok}
    (folder / "onnx-check.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(result))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
