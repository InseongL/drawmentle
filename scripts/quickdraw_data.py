"""Download a bounded Quick Draw subset, render it, and audit its labels.

Run from any directory. All outputs stay under this repository's data/quickdraw.
Source records are retained; project annotations never replace official labels.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from urllib.parse import quote
from uuid import uuid4

import numpy as np
from PIL import Image, ImageDraw
import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "quickdraw"
META = DATA / "metadata"
PREPROCESS_VERSION = "qd-strokes-28-v1"
BASE_URL = "https://storage.googleapis.com/quickdraw_dataset/full/simplified/"


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(obj, ensure_ascii=False, indent=2) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return
    temporary = path.with_name(path.name + "." + uuid4().hex + ".part")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def catalog():
    labels = (META / "categories.txt").read_text(encoding="utf-8").splitlines()
    translations = {}
    group = None
    for line in (META / "labels_ko.txt").read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            group = line[1:-1]
            continue
        en, ko = line.split("|")
        if en in translations or group is None:
            raise ValueError(f"Duplicate label or missing group: {en}")
        translations[en] = (ko, group)
    if len(labels) != 345 or set(labels) != set(translations):
        raise ValueError(f"Label mismatch: missing={set(labels)-set(translations)}, extra={set(translations)-set(labels)}")
    review = {
        "bird": "Broad class overlaps specific birds.",
        "fish": "Broad class overlaps shark and other aquatic labels visually.",
        "cup": "Distinguish from mug and coffee cup.",
        "mug": "Distinguish from cup and coffee cup.",
        "coffee cup": "Distinguish from cup and mug.",
        "cake": "Distinguish from birthday cake.",
        "birthday cake": "Distinguish from cake.",
        "clock": "Distinguish from alarm clock and wristwatch.",
        "alarm clock": "Distinguish from clock.",
        "hurricane": "Distinguish from tornado in monochrome sketches.",
        "tornado": "Distinguish from hurricane.",
        "diamond": "May denote gemstone or diamond shape; inspect samples.",
        "stitches": "May denote a pattern or medical sutures; inspect samples.",
        "fan": "Inspect handheld fan versus electric fan interpretations.",
        "spreadsheet": "Screen/document concept; review daily answer suitability.",
        "The Eiffel Tower": "Named landmark; decide daily answer policy.",
        "The Great Wall of China": "Named landmark; decide daily answer policy.",
        "The Mona Lisa": "Named artwork; decide daily answer policy.",
    }
    items = []
    for index, en in enumerate(labels):
        ko, group = translations[en]
        status, note = "candidate_unvalidated", "Requires model and play testing before daily use."
        if group in {"shape_symbol", "action_abstract"} and en != "diamond":
            status, note = "exclude_proposed", "Shape, symbol, action or abstract label; outside proposed concrete-object daily scope."
        if en in review:
            status, note = "review", review[en]
        items.append({"class_index": index, "category_id": en.lower().replace(" ", "_"),
                      "label_en": en, "display_name_ko": ko, "primary_group": group,
                      "daily_status": status, "review_note": note,
                      "attribute_tags": [], "attribute_status": "not_annotated"})
    write_json(META / "labels.json", {"version": "qd-categories-v1",
        "categories_sha256": digest(META / "categories.txt"),
        "index_policy": "Project indices follow pinned official categories.txt order; never reorder.",
        "annotation_source": "Korean names, broad groups and daily status are project-authored drafts, not Google annotations.",
        "categories": items})
    return items


def valid_record(record, label):
    strokes = record.get("drawing")
    if record.get("word") != label or not isinstance(record.get("recognized"), bool):
        return False
    if not str(record.get("key_id", "")).isdigit() or not isinstance(strokes, list) or not strokes:
        return False
    for stroke in strokes:
        if len(stroke) != 2 or len(stroke[0]) != len(stroke[1]) or not stroke[0]:
            return False
        if any(not isinstance(v, (int, float)) or not 0 <= v <= 255 for axis in stroke for v in axis):
            return False
    return True


def download_one(item, count):
    category = item["category_id"]
    out = DATA / "raw" / f"{category}.ndjson"
    manifest_path = DATA / "manifests" / f"{category}.json"
    if out.exists() and manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        if previous["samples"] == count and previous["sha256"] == digest(out):
            return category, "cached"
    out.parent.mkdir(parents=True, exist_ok=True)
    url = BASE_URL + quote(item["label_en"], safe="") + ".ndjson"
    temporary = out.with_suffix(".ndjson.part")
    for attempt in range(4):
        try:
            seen = set()
            recognized = 0
            invalid = 0
            with requests.get(url, stream=True, timeout=(20, 60)) as response:
                response.raise_for_status()
                headers = {key: response.headers.get(key) for key in
                           ["ETag", "Last-Modified", "x-goog-generation", "Content-Length"]}
                with temporary.open("wb") as stream:
                    for line in response.iter_lines(chunk_size=65536):
                        if not line:
                            continue
                        record = json.loads(line)
                        key = str(record.get("key_id"))
                        if not valid_record(record, item["label_en"]) or key in seen:
                            invalid += 1
                            continue
                        seen.add(key)
                        recognized += int(record["recognized"])
                        stream.write(line + b"\n")
                        if len(seen) == count:
                            break
            if len(seen) != count:
                raise ValueError(f"Only {len(seen)} valid records for {category}")
            temporary.replace(out)
            write_json(manifest_path, {"category_id": category, "label_en": item["label_en"],
                "url": url, "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
                "sampling": "first_n_valid_unique_records_in_source_order; NOT a uniform random sample",
                "samples": count, "recognized_true": recognized, "skipped_invalid_or_duplicate": invalid,
                "bytes": out.stat().st_size, "sha256": digest(out), "source_headers": headers})
            return category, "downloaded"
        except (requests.RequestException, ValueError, OSError):
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)


def render(drawing):
    """Project preprocessing, NOT a byte-identical reproduction of official .npy.

    Preserve aspect ratio; longest coordinate span = 20 px, centered at 13.5.
    Render 1.75 px round strokes at 4x resolution, then Lanczos downsample.
    Output uint8 [28,28], black background=0, white strokes=255.
    """
    points = [(x, y) for xs, ys in drawing for x, y in zip(xs, ys)]
    xs, ys = zip(*points)
    xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
    scale = 20 / max(xmax - xmin, ymax - ymin, 1)
    cx, cy = (xmin + xmax) / 2, (ymin + ymax) / 2
    canvas = Image.new("L", (112, 112), 0)
    pen = ImageDraw.Draw(canvas)
    for sx, sy in drawing:
        xy = [((x - cx) * scale * 4 + 54, (y - cy) * scale * 4 + 54) for x, y in zip(sx, sy)]
        if len(xy) > 1:
            pen.line(xy, fill=255, width=7, joint="curve")
        for x, y in xy:
            pen.ellipse((x - 3, y - 3, x + 3, y + 3), fill=255)
    return np.asarray(canvas.resize((28, 28), Image.Resampling.LANCZOS))


def split_for(image_bytes):
    # Equal rendered images across ALL categories must land in the same split.
    bucket = int.from_bytes(hashlib.sha256(image_bytes).digest()[:8], "big") % 100
    return 0 if bucket < 80 else 1 if bucket < 90 else 2


def prepare(items):
    summary = []
    for n, item in enumerate(items, 1):
        cid = item["category_id"]
        raw = DATA / "raw" / f"{cid}.ndjson"
        manifest = json.loads((DATA / "manifests" / f"{cid}.json").read_text(encoding="utf-8"))
        if digest(raw) != manifest["sha256"]:
            raise ValueError(f"Source checksum mismatch: {cid}")
        records = [json.loads(line) for line in raw.read_text(encoding="utf-8").splitlines()]
        if not all(valid_record(r, item["label_en"]) for r in records):
            raise ValueError(f"Invalid record: {cid}")
        images = np.stack([render(r["drawing"]) for r in records])
        splits = np.array([split_for(a.tobytes()) for a in images], dtype=np.uint8)
        folder = DATA / "processed" / cid
        folder.mkdir(parents=True, exist_ok=True)
        arrays = {"images": images, "key_ids": np.array([str(r["key_id"]) for r in records], dtype="U20"),
                  "recognized": np.array([r["recognized"] for r in records], dtype=np.bool_), "split": splits}
        for name, array in arrays.items():
            with (folder / f"{name}.npy.part").open("wb") as stream:
                np.save(stream, array, allow_pickle=False)
            (folder / f"{name}.npy.part").replace(folder / f"{name}.npy")
        row = {"category_id": cid, "class_index": item["class_index"], "count": len(records),
               "recognized_true": int(arrays["recognized"].sum()),
               "splits": {name: int((splits == i).sum()) for i, name in enumerate(["train", "validation", "test"])},
               "raw_sha256": manifest["sha256"], "files_sha256": {f"{name}.npy": digest(folder / f"{name}.npy") for name in arrays}}
        write_json(folder / "manifest.json", {**row, "preprocessing_version": PREPROCESS_VERSION})
        summary.append(row)
        if n % 20 == 0 or n == len(items):
            print(f"Prepared {n}/{len(items)} categories", flush=True)
    write_json(DATA / "processed" / "manifest.json", {"preprocessing_version": PREPROCESS_VERSION,
        "shape": [28, 28], "dtype": "uint8", "background": 0, "stroke": 255,
        "normalization_for_model": "float32(images) / 255.0; add channel dimension",
        "split_codes": {"0": "train", "1": "validation", "2": "test"},
        "split_policy": "SHA256 of rendered image bytes modulo 100: 0-79 train, 80-89 validation, 90-99 test. Exact image duplicates share split globally; near-duplicates and user identities are not resolved.",
        "labels_sha256": digest(META / "labels.json"), "categories": summary})


def verify(items):
    dataset_manifest = json.loads((DATA / "processed" / "manifest.json").read_text(encoding="utf-8"))
    assert dataset_manifest["labels_sha256"] == digest(META / "labels.json"), "Label version mismatch"
    assert dataset_manifest["preprocessing_version"] == PREPROCESS_VERSION
    assert [r["category_id"] for r in dataset_manifest["categories"]] == [r["category_id"] for r in items]
    total = Counter()
    pixel_hashes = {}
    key_ids = set()
    conflicts = Counter()
    for n, item in enumerate(items, 1):
        folder = DATA / "processed" / item["category_id"]
        meta = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        assert meta["class_index"] == item["class_index"]
        assert meta["preprocessing_version"] == PREPROCESS_VERSION
        raw = DATA / "raw" / f'{item["category_id"]}.ndjson'
        assert digest(raw) == meta["raw_sha256"], "Source changed after preprocessing"
        records = [json.loads(line) for line in raw.read_text(encoding="utf-8").splitlines()]
        for name, expected in meta["files_sha256"].items():
            assert digest(folder / name) == expected, (folder, name)
        x = np.load(folder / "images.npy", allow_pickle=False)
        ids = np.load(folder / "key_ids.npy", allow_pickle=False)
        recognized = np.load(folder / "recognized.npy", allow_pickle=False)
        splits = np.load(folder / "split.npy", allow_pickle=False)
        assert x.shape == (meta["count"], 28, 28) and x.dtype == np.uint8
        assert len(ids) == len(recognized) == len(splits) == len(x)
        assert ids.tolist() == [str(record["key_id"]) for record in records]
        assert recognized.tolist() == [record["recognized"] for record in records]
        for index in {0, len(records) // 2, len(records) - 1}:
            assert np.array_equal(x[index], render(records[index]["drawing"])), "Image/source mapping mismatch"
        assert recognized.dtype == np.bool_ and set(splits.tolist()) <= {0, 1, 2}
        assert np.all(x.max(axis=(1, 2)) > 0), item["category_id"]
        for pixels, key, split in zip(x, ids, splits):
            assert str(key) not in key_ids, f"Duplicate key_id {key}"
            key_ids.add(str(key))
            image_hash = hashlib.sha256(pixels.tobytes()).digest()
            assert int(split) == split_for(pixels.tobytes())
            previous = pixel_hashes.get(image_hash)
            if previous is not None:
                total["exact_duplicate_images_after_first"] += 1
                assert previous[0] == int(split), "Exact image leaked across splits"
                if previous[1] != item["category_id"]:
                    conflicts[" / ".join(sorted([previous[1], item["category_id"]]))] += 1
            else:
                pixel_hashes[image_hash] = (int(split), item["category_id"])
        total["samples"] += len(x)
        total["recognized_true"] += int(recognized.sum())
        for i, split_name in enumerate(["train", "validation", "test"]):
            total[split_name] += int((splits == i).sum())
        if n % 50 == 0:
            print(f"Verified {n}/{len(items)} categories", flush=True)
    report = {"verified_at_utc": datetime.now(timezone.utc).isoformat(), "categories": len(items),
        "counts": dict(total), "unique_image_hashes": len(pixel_hashes),
        "cross_label_exact_duplicate_pairs": dict(conflicts.most_common()),
        "raw_bytes": sum(p.stat().st_size for p in (DATA / "raw").glob("*.ndjson")),
        "processed_bytes": sum(p.stat().st_size for p in (DATA / "processed").rglob("*.npy")),
        "label_groups": dict(Counter(i["primary_group"] for i in items)),
        "daily_status": dict(Counter(i["daily_status"] for i in items)),
        "passed": True, "limitations": ["Prefix subset, not random full-dataset sampling.",
            "recognized is the original game's output, not human-verified ground truth.",
            "Prompt labels may not match what was actually drawn.",
            "Near-duplicate and same-user leakage not audited; use independent service drawings for final evaluation.",
            "Exact duplicates are reported, retained, and grouped into the same split."]}
    write_json(META / "verification.json", report)
    print(json.dumps(report, ensure_ascii=True, indent=2), flush=True)


def preview(items):
    # Contact sheets are data visualizations; no image generation/editing involved.
    target = DATA / "previews"
    target.mkdir(parents=True, exist_ok=True)
    from html import escape
    cards = []
    for item in items:
        cid = item["category_id"]
        pixels = np.load(DATA / "processed" / cid / "images.npy", mmap_mode="r", allow_pickle=False)
        sheet = Image.new("L", (10 * 60, 2 * 60), 255)
        for i, sample in enumerate(pixels[:20]):
            thumb = Image.fromarray(255 - sample).resize((56, 56), Image.Resampling.NEAREST)
            sheet.paste(thumb, ((i % 10) * 60 + 2, (i // 10) * 60 + 2))
        sheet.save(target / f"{cid}.png")
        cards.append(f'<section data-search="{escape(item["label_en"] + " " + item["display_name_ko"] + " " + item["primary_group"])}"><h2>{item["class_index"]}: {escape(item["label_en"])} / {escape(item["display_name_ko"])}</h2><p>{escape(item["primary_group"])} · {escape(item["daily_status"])}</p><img loading="lazy" src="{cid}.png" alt="20 sample sketches"></section>')
    html = '<!doctype html><html lang="ko"><meta charset="utf-8"><title>Quick Draw labels</title><style>body{font:16px system-ui;max-width:1000px;margin:30px auto;background:#f6f7fa}input{padding:12px;width:90%}section{background:white;padding:16px;margin:16px 0}img{max-width:100%}h2{font-size:18px}</style><h1>Quick, Draw! 라벨과 샘플 345개</h1><p>Google Quick, Draw! · CC BY 4.0. 한국어 이름·그룹·정답 적합성은 프로젝트 초안. 각 라벨의 첫 20장.</p><input id="q" placeholder="영문 / 한국어 / 그룹 검색">' + ''.join(cards) + '<script>document.getElementById("q").oninput=e=>{let q=e.target.value.toLowerCase();document.querySelectorAll("section").forEach(s=>s.hidden=!s.dataset.search.toLowerCase().includes(q))}</script></html>'
    (target / "index.html").write_text(html, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["catalog", "download", "prepare", "verify", "preview"])
    parser.add_argument("--samples-per-class", type=int, default=1000)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    if args.samples_per_class < 1 or not 1 <= args.workers <= 16:
        parser.error("samples must be positive; workers must be between 1 and 16")
    items = catalog()
    if args.command == "download":
        failures = []
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            tasks = {pool.submit(download_one, i, args.samples_per_class): i for i in items}
            for n, future in enumerate(as_completed(tasks), 1):
                try:
                    cid, status = future.result()
                    print(f"[{n}/{len(items)}] {cid}: {status}", flush=True)
                except Exception as error:
                    failures.append((tasks[future]["category_id"], str(error)))
                    print(f"FAILED: {failures[-1]}", flush=True)
        if failures:
            raise RuntimeError(f"Incomplete download; rerun to resume: {failures}")
    elif args.command == "prepare":
        prepare(items)
    elif args.command == "verify":
        verify(items)
    elif args.command == "preview":
        preview(items)
    else:
        print(f"Catalog complete: {len(items)} labels")


if __name__ == "__main__":
    main()
