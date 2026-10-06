"""Build a versioned training dataset from Quick Draw simplified strokes.

    python -m model.datasets.build_manifest --version qd-local1k-64-v1
    python -m model.datasets.build_manifest --version qd-10k-64-v1 --source-dir data/quickdraw/full --per-class 10000

Output: data/datasets/<version>/ with images.npy (uint8 [N, 64, 64]), labels.npy (raw class_index), split.npy
(0 train / 1 validation / 2 test), recognized.npy, key_ids.npy, manifest.json (local, untracked) and
manifest.public.json (summary, tracked). The build happens in <version>.partial and is renamed only when every
check passed, so a finished folder is always complete.

Sampling: with --per-class, the records with the smallest sha256(seed:key_id) are kept, which is a reproducible
random sample independent of file order. Split: key_ids already split in data/quickdraw/processed keep that split
(docs/model-architecture-v1.md §7.2); new records use sha256(rendered 64px bytes) buckets 0-79/80-89/90-99.
Identical rendered images are then forced into one split.
"""
from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import os
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from model.datasets.preprocess import QD_STROKES_64_V1, render

ROOT = Path(__file__).resolve().parents[2]
LABELS = ROOT / "data/quickdraw/metadata/labels.json"
PROCESSED = ROOT / "data/quickdraw/processed"
RAW_MANIFESTS = ROOT / "data/quickdraw/manifests"
LOCAL_RAW = ROOT / "data/quickdraw/raw"
OUT_ROOT = ROOT / "data/datasets"
SPLITS = ("train", "validation", "test")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def hash_split(image: np.ndarray) -> int:
    bucket = int.from_bytes(hashlib.sha256(image.tobytes()).digest()[:8], "big") % 100
    return 0 if bucket < 80 else 1 if bucket < 90 else 2


def existing_split(category: str) -> dict[int, int]:
    folder = PROCESSED / category
    if not (folder / "key_ids.npy").exists():
        return {}
    keys = np.load(folder / "key_ids.npy", allow_pickle=False)
    splits = np.load(folder / "split.npy", allow_pickle=False)
    return {int(k): int(s) for k, s in zip(keys, splits)}


def sample_key(seed: int, key_id: int) -> bytes:
    return hashlib.sha256(f"{seed}:{key_id}".encode()).digest()


def read_records(path: Path, per_class: int | None, seed: int) -> list[dict]:
    """All valid records, or the per_class records with the smallest sample key (streaming, bounded memory)."""
    kept: list[dict] = []
    heap: list = []  # max-heap of the smallest sample keys: entries hold the negated key bytes
    seen: set[int] = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            if not rec.get("drawing") or not any(len(xs) for xs, _ in rec["drawing"]):
                continue
            key = int(rec["key_id"])
            if key in seen:  # the same drawing listed twice must not be sampled twice
                continue
            seen.add(key)
            if per_class is None:
                kept.append(rec)
                continue
            item = (tuple(-b for b in sample_key(seed, key)), line)
            if len(heap) < per_class:
                heapq.heappush(heap, item)
            elif item > heap[0]:
                heapq.heapreplace(heap, item)
    if per_class is not None:
        kept = [json.loads(line) for _, line in sorted(heap, reverse=True)]
    return kept


def build_category(job):
    class_index, category, raw_path, per_class, seed = job
    records = read_records(Path(raw_path), per_class, seed)
    size = QD_STROKES_64_V1.size
    images = (np.stack([render(r["drawing"], QD_STROKES_64_V1) for r in records]) if records
              else np.zeros((0, size, size), np.uint8))
    known = existing_split(category)
    keys = np.array([int(r["key_id"]) for r in records], dtype=np.int64)
    split = np.array([known.get(int(k), hash_split(img)) for k, img in zip(keys, images)], dtype=np.uint8)
    recognized = np.array([bool(r.get("recognized")) for r in records], dtype=bool)
    digests = [hashlib.sha256(img.tobytes()).digest() for img in images]
    return {"class_index": class_index, "category": category, "images": images, "digests": digests, "keys": keys,
            "split": split, "recognized": recognized, "reused": sum(int(k) in known for k in keys),
            "raw_sha256": sha256_file(Path(raw_path))}


def git_state() -> dict:
    def run(*cmd):
        return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True).stdout.strip()
    return {"commit": run("git", "rev-parse", "HEAD"), "dirty": bool(run("git", "status", "--porcelain", "--", "model"))}


def rel(path: Path) -> str:
    path = path.resolve()
    return path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", required=True)
    ap.add_argument("--source-dir", type=Path, default=LOCAL_RAW)
    ap.add_argument("--per-class", type=int, help="reproducible random sample size per class (default: all)")
    ap.add_argument("--seed", type=int, default=20260926)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    args = ap.parse_args(argv)

    out = OUT_ROOT / args.version
    stage = out.with_name(out.name + ".partial")
    if out.exists():
        raise SystemExit(f"{out} already exists; dataset versions are immutable, choose a new --version")
    if stage.exists():
        raise SystemExit(f"{stage} exists from an interrupted build; delete it first")
    categories = sorted(json.loads(LABELS.read_text(encoding="utf-8"))["categories"], key=lambda c: c["class_index"])
    jobs = []
    for c in categories:
        raw = args.source_dir / f"{c['category_id']}.ndjson"
        if not raw.exists():
            raise SystemExit(f"missing source file {raw}")
        jobs.append((c["class_index"], c["category_id"], str(raw), args.per_class, args.seed))

    # Images stream to a temporary file so a 10k-per-class build does not hold every image twice in RAM.
    stage.mkdir(parents=True)
    results = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool, open(stage / "images.tmp", "wb") as tmp:
        for res in pool.map(build_category, jobs, chunksize=4):
            tmp.write(res.pop("images").tobytes())
            results.append(res)
            print(f"\r{len(results)}/{len(jobs)} categories", end="", file=sys.stderr)
    print(file=sys.stderr)

    if args.source_dir.resolve() == LOCAL_RAW.resolve():  # local files must be the ones recorded at download time
        for r in results:
            recorded = json.loads((RAW_MANIFESTS / f"{r['category']}.json").read_text(encoding="utf-8"))["sha256"]
            if recorded != r["raw_sha256"]:
                raise SystemExit(f"{r['category']}: raw file changed since download ({stage} left for inspection)")

    counts_per_class = [len(r["keys"]) for r in results]
    total = sum(counts_per_class)
    labels = np.concatenate([np.full(n, r["class_index"], dtype=np.int16) for n, r in zip(counts_per_class, results)])
    keys = np.concatenate([r["keys"] for r in results])
    split = np.concatenate([r["split"] for r in results])
    recognized = np.concatenate([r["recognized"] for r in results])
    digests = [d for r in results for d in r["digests"]]

    # Identical images (any class) share one split: the lowest code wins, so validation/test never leak into train.
    by_hash: dict[bytes, int] = {}
    for d, s in zip(digests, split):
        by_hash[d] = min(by_hash.get(d, 3), int(s))
    fixed = np.array([by_hash[d] for d in digests], dtype=np.uint8)
    moved = int((fixed != split).sum())
    split = fixed

    size = QD_STROKES_64_V1.size
    images = np.lib.format.open_memmap(stage / "images.npy", mode="w+", dtype=np.uint8, shape=(total, size, size))
    chunk = 20000
    with open(stage / "images.tmp", "rb") as tmp:
        for start in range(0, total, chunk):
            n = min(chunk, total - start)
            images[start:start + n] = np.frombuffer(tmp.read(n * size * size), dtype=np.uint8).reshape(n, size, size)
    images.flush()
    del images
    (stage / "images.tmp").unlink()
    arrays = {"labels": labels, "split": split, "recognized": recognized, "key_ids": keys}
    for name, arr in arrays.items():
        np.save(stage / f"{name}.npy", arr, allow_pickle=False)
    files = {f"{name}.npy": sha256_file(stage / f"{name}.npy") for name in ["images", *arrays]}

    class_ids = [c["category_id"] for c in categories]
    counts = {name: int((split == i).sum()) for i, name in enumerate(SPLITS)}
    spec = QD_STROKES_64_V1
    public = {
        "datasetVersion": args.version,
        "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "preprocessing": {"version": spec.version, "size": spec.size, "span": spec.span, "radius": spec.radius,
                          "supersample": spec.supersample},
        "source": {"name": "Quick, Draw! simplified (Google, CC BY 4.0)", "dir": rel(args.source_dir),
                   "sampling": f"smallest sha256(seed:key_id), {args.per_class} per class" if args.per_class
                   else "all valid records", "seed": args.seed if args.per_class else None},
        "classes": {"count": len(class_ids), "sha256": hashlib.sha256(json.dumps(class_ids).encode()).hexdigest()},
        "samples": total,
        "splits": counts,
        "splitPolicy": "existing 28px split for known key_ids, else sha256(64px image) buckets 80/10/10; "
                       "identical images forced into the lowest split",
        "duplicates": {"identicalImages": len(digests) - len(by_hash), "movedBetweenSplits": moved},
        "recognizedTrue": int(recognized.sum()),
        "files": files,
        "code": git_state(),
    }
    private = dict(public, classIds=class_ids, sources={
        r["category"]: {"sha256": r["raw_sha256"], "samples": n, "reusedSplit": int(r["reused"])}
        for n, r in zip(counts_per_class, results)})
    (stage / "manifest.json").write_text(json.dumps(private, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (stage / "manifest.public.json").write_text(json.dumps(public, ensure_ascii=False, indent=1) + "\n",
                                                encoding="utf-8")
    stage.rename(out)
    print(json.dumps({"out": rel(out), "samples": total, "splits": counts, "duplicates": public["duplicates"]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
