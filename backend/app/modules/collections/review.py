"""Label review batches (docs/mlops-v1.md §4). Offline tools for the CLI; no API, no automatic labels.

export_batch writes verified, unreviewed drawings to a folder: index.html (drawings as SVG), items.csv for decisions,
categories.csv for valid labels and batch.json. A reviewer fills `decision` (accepted / rejected / uncertain) and, for
accepted rows, `category_id` with a raw catalogue ID. import_batch checks every row first and then appends
label_reviews rows. Model predictions and puzzle answers are shown only as hints (config) and never copied.
"""
from __future__ import annotations

import csv
import datetime as dt
import html
import json
import uuid
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.core.settings import REPO_ROOT, Settings
from app.db.models import LabelReview
from app.storage.object_store import ObjectStore

from . import repository

LABELS = REPO_ROOT / "data/quickdraw/metadata/labels.json"
CURATION = REPO_ROOT / "config/model/catalog-curation-v1.json"
DECISIONS = ("accepted", "rejected", "uncertain")
FIELDS = ("sample_id", "selection", "result", "model_top1", "puzzle_answer", "decision", "category_id", "note")

PENDING_SQL = text("""
SELECT s.sample_id, s.selection, s.verified_object_key, sub.status, sub.top3 -> 0 ->> 'categoryId' AS top1,
       p.answer_category_id, lr.decision AS last_decision
FROM drawing_samples s
JOIN submissions sub ON sub.submission_id = s.submission_id
JOIN game_sessions g ON g.game_session_id = sub.game_session_id
JOIN puzzles p ON p.puzzle_id = g.puzzle_id
LEFT JOIN LATERAL (SELECT decision FROM label_reviews r WHERE r.sample_id = s.sample_id
                   ORDER BY r.revision DESC LIMIT 1) lr ON true
WHERE s.state = 'verified' AND (lr.decision IS NULL OR (:uncertain AND lr.decision = 'uncertain'))
ORDER BY s.verified_at, s.sample_id
LIMIT :limit
""")


def catalog() -> tuple[dict[str, dict], str]:
    labels = json.loads(LABELS.read_text(encoding="utf-8"))["categories"]
    curation = json.loads(CURATION.read_text(encoding="utf-8"))
    return {c["category_id"]: c for c in labels}, curation["version"]


def svg(strokes: list[list[list[int]]], size: int = 192, coordinate_max: int = 1024) -> str:
    parts = []
    for stroke in strokes:
        if len(stroke) == 1:
            x, y = stroke[0]
            parts.append(f'<circle cx="{x}" cy="{y}" r="4"/>')
        else:
            parts.append('<polyline points="' + " ".join(f"{x},{y}" for x, y in stroke) + '"/>')
    return (f'<svg viewBox="0 0 {coordinate_max} {coordinate_max}" width="{size}" height="{size}" '
            'fill="none" stroke="#111" stroke-width="8" stroke-linecap="round" stroke-linejoin="round" '
            'style="background:#fff;border:1px solid #ccc">' + "".join(parts) + "</svg>")


def export_batch(factory: sessionmaker, settings: Settings, store: ObjectStore, out_dir: Path, limit: int,
                 include_uncertain: bool, now: dt.datetime) -> dict:
    labels, catalog_version = catalog()
    cfg = settings.collection
    with factory() as db:
        rows = db.execute(PENDING_SQL, {"limit": limit, "uncertain": include_uncertain}).mappings().all()
    out_dir.mkdir(parents=True, exist_ok=False)
    items, cards = [], []
    for r in rows:
        data = store.get(r["verified_object_key"])
        if data is None:
            continue  # the reconcile worker reports missing files
        strokes = json.loads(data)["strokes"]
        hint_top1 = r["top1"] if cfg.review_show_prediction else ""
        hint_answer = r["answer_category_id"] if cfg.review_show_answer else ""
        items.append({"sample_id": str(r["sample_id"]), "selection": r["selection"], "result": r["status"],
                      "model_top1": hint_top1, "puzzle_answer": hint_answer, "decision": "", "category_id": "",
                      "note": "uncertain before" if r["last_decision"] == "uncertain" else ""})
        hints = " · ".join(h for h in (f"모델 1위: {hint_top1}" if hint_top1 else "",
                                       f"정답: {hint_answer}" if hint_answer else "") if h)
        cards.append(f'<figure>{svg(strokes)}<figcaption><code>{r["sample_id"]}</code><br>'
                     f'{html.escape(hints)}</figcaption></figure>')
    with open(out_dir / "items.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(items)
    with open(out_dir / "categories.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["category_id", "name_ko", "name_en"])
        for cid, c in sorted(labels.items(), key=lambda kv: kv[1]["class_index"]):
            w.writerow([cid, c["display_name_ko"], c["label_en"]])
    (out_dir / "index.html").write_text(
        "<!doctype html><meta charset='utf-8'><title>검수 묶음</title>"
        "<style>body{font-family:sans-serif;margin:16px}main{display:flex;flex-wrap:wrap;gap:12px}"
        "figure{margin:0;width:200px;font-size:12px}code{font-size:10px}</style>"
        f"<h1>검수 묶음 {len(items)}장</h1><p>items.csv의 decision(accepted/rejected/uncertain)과 category_id"
        "(categories.csv의 원본 ID)를 채운 뒤 review-import로 가져온다. 힌트는 참고만 하고 그대로 옮기지 않는다.</p>"
        "<main>" + "".join(cards) + "</main>", encoding="utf-8")
    batch = {"batchId": out_dir.name, "createdAt": now.isoformat(timespec="seconds"), "catalogVersion": catalog_version,
             "count": len(items), "sampleIds": [i["sample_id"] for i in items],
             "hints": {"modelPrediction": cfg.review_show_prediction, "puzzleAnswer": cfg.review_show_answer}}
    (out_dir / "batch.json").write_text(json.dumps(batch, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return {"out": str(out_dir), "count": len(items)}


def read_decisions(csv_path: Path, valid: set[str]) -> tuple[list[dict], list[str]]:
    rows, errors = [], []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for n, row in enumerate(csv.DictReader(f), start=2):
            decision = (row.get("decision") or "").strip().lower()
            if not decision:
                continue
            category = (row.get("category_id") or "").strip() or None
            try:
                sample_id = uuid.UUID((row.get("sample_id") or "").strip())
            except ValueError:
                errors.append(f"line {n}: bad sample_id")
                continue
            if decision not in DECISIONS:
                errors.append(f"line {n}: decision must be one of {', '.join(DECISIONS)}")
            elif decision == "accepted" and category not in valid:
                errors.append(f"line {n}: accepted needs a category_id from categories.csv")
            elif category is not None and category not in valid:
                errors.append(f"line {n}: unknown category_id {category}")
            else:
                rows.append({"sample_id": sample_id, "decision": decision, "category": category,
                             "note": (row.get("note") or "").strip() or None})
    return rows, errors


def import_batch(factory: sessionmaker, csv_path: Path, reviewer_ref: str, now: dt.datetime) -> dict:
    """All rows are checked before anything is written; reviews are appended, never edited."""
    labels, catalog_version = catalog()
    rows, errors = read_decisions(csv_path, set(labels))
    if errors:
        raise SystemExit("review file has errors, nothing imported:\n  " + "\n  ".join(errors))
    counts = {"accepted": 0, "rejected": 0, "uncertain": 0, "skipped_not_verified": 0}
    for row in rows:
        with factory() as db:
            sample = repository.lock_sample(db, row["sample_id"])
            if sample is None or sample.state != "verified":
                counts["skipped_not_verified"] += 1
                continue
            db.add(LabelReview(review_id=uuid.uuid4(), sample_id=sample.sample_id,
                               revision=repository.next_review_revision(db, sample.sample_id),
                               decision=row["decision"], reviewed_category_id=row["category"],
                               catalog_version=catalog_version, reviewer_ref=reviewer_ref, note=row["note"],
                               reviewed_at=now))
            db.commit()
            counts[row["decision"]] += 1
    return counts
