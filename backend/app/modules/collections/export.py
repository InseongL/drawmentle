"""Training export of reviewed drawings (docs/mlops-v1.md §5, docs/database-schema-v1.md §3).

A sample is exported only if, at export time: its file is verified and still matches its hash, the session still
consents, the consent it was collected under names a notice allowed for training (`training_notice_versions`),
it is not being deleted, and its latest review is `accepted`. Sessions appear only as a salted hash (`group`),
used to keep one person's drawings in one split. The manifest lists every exported sample ID so a later deletion can
be traced to the dataset copies built from it.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections import Counter
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.core.settings import Settings
from app.storage.object_store import ObjectStore

EXPORT_SQL = text("""
SELECT s.sample_id, s.session_id, s.selection, s.verified_object_key, s.file_sha256, sub.drawing_hash,
       sub.status, sub.release_id, sub.top3 -> 0 ->> 'categoryId' AS model_top1,
       lr.reviewed_category_id, lr.catalog_version, lr.revision
FROM drawing_samples s
JOIN anonymous_sessions a ON a.session_id = s.session_id
JOIN collection_consents c ON c.session_id = s.session_id AND c.revision = s.consent_revision
JOIN submissions sub ON sub.submission_id = s.submission_id
JOIN LATERAL (SELECT decision, reviewed_category_id, catalog_version, revision FROM label_reviews r
              WHERE r.sample_id = s.sample_id ORDER BY r.revision DESC LIMIT 1) lr ON true
WHERE s.state = 'verified' AND a.collection_enabled AND c.enabled AND c.policy_version = ANY(:notices)
  AND lr.decision = 'accepted'
ORDER BY s.sample_id
""")


def group_of(salt: str, session_id) -> str:
    return hashlib.sha256(f"{salt}:{session_id}".encode()).hexdigest()[:32]


def export_training(factory: sessionmaker, settings: Settings, store: ObjectStore, out_root: Path,
                    now: dt.datetime) -> dict:
    cfg = settings.collection
    with factory() as db:
        rows = db.execute(EXPORT_SQL, {"notices": list(cfg.training_notice_versions)}).mappings().all()
    export_id = f"user-{now:%Y%m%d-%H%M%S}"
    out = out_root / export_id
    out.mkdir(parents=True, exist_ok=False)
    labels, skipped, ids = Counter(), Counter(), []
    with open(out / "samples.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            data = store.get(r["verified_object_key"])
            if data is None or hashlib.sha256(data).hexdigest() != r["file_sha256"]:
                skipped["file_missing_or_changed"] += 1
                continue
            doc = json.loads(data)
            line = {"sampleId": str(r["sample_id"]), "group": group_of(cfg.export_group_salt, r["session_id"]),
                    "label": r["reviewed_category_id"], "reviewCatalogVersion": r["catalog_version"],
                    "reviewRevision": r["revision"], "selection": r["selection"], "result": r["status"],
                    "releaseId": r["release_id"], "modelTop1": r["model_top1"], "drawingHash": r["drawing_hash"],
                    "coordinateMax": doc["coordinateMax"], "strokes": doc["strokes"]}
            f.write(json.dumps(line, ensure_ascii=False, separators=(",", ":")) + "\n")
            labels[r["reviewed_category_id"]] += 1
            ids.append(str(r["sample_id"]))
    digest = hashlib.sha256((out / "samples.jsonl").read_bytes()).hexdigest()
    manifest = {"exportId": export_id, "createdAt": now.isoformat(timespec="seconds"), "count": len(ids),
                "samplesSha256": digest, "collectionConfigVersion": cfg.version,
                "trainingNoticeVersions": list(cfg.training_notice_versions), "perLabel": dict(sorted(labels.items())),
                "skipped": dict(skipped), "sampleIds": ids,
                "note": "user drawings: keep out of Git; delete this folder when its samples are deleted"}
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return {"out": str(out), "count": len(ids), "labels": len(labels), "skipped": dict(skipped)}
