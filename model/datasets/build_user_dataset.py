"""Build a dataset version from reviewed user drawings (docs/mlops-v1.md §5).

    python -m model.datasets.build_user_dataset --export data/collected/exports/<export-id> --version user-<id>

Input: a training export from the backend (`python -m app.cli collection-export`): samples.jsonl with strokes-v1
points ([[x, y], ...] per stroke, 0..coordinateMax) and the reviewed raw category ID, plus manifest.json.
Output: data/datasets/<version>/ in the same layout as build_manifest.py (images.npy, labels.npy, split.npy,
recognized.npy, key_ids.npy, manifest.json, manifest.public.json) and samples.json (row -> sampleId, group).

- Rendering is the same qd-strokes-64-v1 rule as Quick Draw and the browser (preprocess.render).
- Split by person: sha256(split_salt:group) with the ratios in config/mlops/mlops.json, so one session's drawings
  never land in two splits. Identical images are then forced into the lowest split, as for Quick Draw.
- The user test split is the real-canvas evaluation set; it is never trained on.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from model.datasets.preprocess import QD_STROKES_64_V1, render

ROOT = Path(__file__).resolve().parents[2]
LABELS = ROOT / "data/quickdraw/metadata/labels.json"
MLOPS_CONFIG = ROOT / "config/mlops/mlops.json"
OUT_ROOT = ROOT / "data/datasets"
SPLITS = ("train", "validation", "test")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def to_quickdraw(strokes: list[list[list[int]]]) -> list[list[list[int]]]:
    """[[x, y], ...] per stroke -> [[xs], [ys]] per stroke (the renderer accepts any coordinate unit)."""
    return [[[p[0] for p in s], [p[1] for p in s]] for s in strokes]


def split_of(salt: str, group: str, ratios: dict) -> int:
    u = int.from_bytes(hashlib.sha256(f"{salt}:{group}".encode()).digest()[:8], "big") / 2**64
    if u < ratios["train"]:
        return 0
    return 1 if u < ratios["train"] + ratios["validation"] else 2


def key_id(sample_id: str) -> int:
    return int.from_bytes(hashlib.sha256(sample_id.encode()).digest()[:8], "big", signed=True)


def build(export_dir: Path, version: str, out_root: Path = OUT_ROOT, dataset_cfg: dict | None = None) -> dict:
    cfg = dataset_cfg or json.loads(MLOPS_CONFIG.read_text(encoding="utf-8"))["dataset"]
    ratios = cfg["user_split"]
    if abs(sum(ratios[s] for s in SPLITS) - 1) > 1e-9:
        raise SystemExit("dataset.user_split ratios must add up to 1")
    out = out_root / version
    stage = out_root / f"{version}.partial"
    if out.exists():
        raise SystemExit(f"{out} already exists; dataset versions are never rebuilt in place")
    export = json.loads((export_dir / "manifest.json").read_text(encoding="utf-8"))
    if sha256_file(export_dir / "samples.jsonl") != export["samplesSha256"]:
        raise SystemExit("samples.jsonl does not match its export manifest")
    labels = sorted(json.loads(LABELS.read_text(encoding="utf-8"))["categories"], key=lambda c: c["class_index"])
    class_index = {c["category_id"]: c["class_index"] for c in labels}
    class_ids = [c["category_id"] for c in labels]

    records = [json.loads(line) for line in (export_dir / "samples.jsonl").read_text(encoding="utf-8").splitlines()
               if line.strip()]
    per_label = Counter(r["label"] for r in records)
    dropped = {k: n for k, n in per_label.items() if n < cfg.get("min_accepted_per_label", 0)}
    unknown = sorted({r["label"] for r in records} - set(class_index))
    if unknown:
        raise SystemExit(f"labels not in the catalogue: {unknown}")
    records = [r for r in records if r["label"] not in dropped]
    if not records:
        raise SystemExit("no usable samples in this export")

    spec = QD_STROKES_64_V1
    images = np.stack([render(to_quickdraw(r["strokes"]), spec) for r in records]).astype(np.uint8)
    split = np.array([split_of(cfg["split_salt"], r["group"], ratios) for r in records], dtype=np.uint8)
    digests = [hashlib.sha256(img.tobytes()).digest() for img in images]
    lowest: dict[bytes, int] = {}
    for d, s in zip(digests, split):
        lowest[d] = min(lowest.get(d, 3), int(s))
    fixed = np.array([lowest[d] for d in digests], dtype=np.uint8)
    moved, split = int((fixed != split).sum()), fixed

    stage.mkdir(parents=True, exist_ok=False)
    arrays = {"images": images,
              "labels": np.array([class_index[r["label"]] for r in records], dtype=np.int16),
              "split": split, "recognized": np.ones(len(records), dtype=bool),
              "key_ids": np.array([key_id(r["sampleId"]) for r in records], dtype=np.int64)}
    for name, arr in arrays.items():
        np.save(stage / f"{name}.npy", arr, allow_pickle=False)
    (stage / "samples.json").write_text(json.dumps([{"sampleId": r["sampleId"], "group": r["group"]}
                                                    for r in records]) + "\n", encoding="utf-8")
    counts = {name: int((split == i).sum()) for i, name in enumerate(SPLITS)}
    public = {
        "datasetVersion": version, "kind": "user",
        "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "preprocessing": {"version": spec.version, "size": spec.size, "span": spec.span, "radius": spec.radius,
                          "supersample": spec.supersample},
        "source": {"name": "reviewed user drawings (consented)", "exportId": export["exportId"],
                   "exportSha256": export["samplesSha256"], "drawingVersion": "strokes-v1"},
        "classes": {"count": len(class_ids), "sha256": hashlib.sha256(json.dumps(class_ids).encode()).hexdigest()},
        "samples": len(records), "splits": counts, "labels": len(set(r["label"] for r in records)),
        "splitPolicy": f"sha256({cfg['split_salt']}:group) {ratios}; identical images forced into the lowest split",
        "duplicates": {"identicalImages": len(digests) - len(lowest), "movedBetweenSplits": moved},
        "droppedLabels": dropped,
        "files": {f"{name}.npy": sha256_file(stage / f"{name}.npy") for name in arrays},
    }
    (stage / "manifest.json").write_text(json.dumps(public | {"classIds": class_ids}, ensure_ascii=False, indent=1)
                                         + "\n", encoding="utf-8")
    (stage / "manifest.public.json").write_text(json.dumps(public, ensure_ascii=False, indent=1) + "\n",
                                                encoding="utf-8")
    stage.rename(out)
    return {"out": str(out), "samples": len(records), "splits": counts, "droppedLabels": dropped}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--export", type=Path, required=True, help="data/collected/exports/<export-id>")
    ap.add_argument("--version", required=True, help="new dataset version, e.g. user-20261101-1")
    args = ap.parse_args(argv)
    export_dir = args.export if args.export.is_absolute() else ROOT / args.export
    print(json.dumps(build(export_dir, args.version), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
