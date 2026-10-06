"""Collection clean-up, run on a schedule:  python -m app.cli collection-reconcile  (docs/mlops-v1.md §3.4)

1. Expire upload grants past their time; their samples become `upload_failed`.
2. Retention: verified samples older than `retention.verified_days` move to `delete_pending`.
3. Delete files of `delete_pending` samples (temporary and verified), then mark them `deleted`.
4. Remove orphan files: temporary files of finished uploads, verified files no current sample points at.
5. Derived copies of deleted drawings: review batches and training exports that contain one are removed; user
   datasets are removed or only reported (`retention.derived_datasets`), with the composites built on them.

The DB state is the source of truth. Each sample is handled in its own short transaction, locking only the sample
(never the session), so the API's lock order (session -> sample) cannot deadlock with it. Game rows are never touched.
"""
from __future__ import annotations

import datetime as dt
import json
import shutil
import uuid
from collections import Counter
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import Settings
from app.db.models import DrawingSample, DrawingUpload
from app.modules.collections import repository
from app.storage.object_store import ObjectStore

OPEN_UPLOADS = ("issued", "received")


def _ids(db: Session, stmt) -> list[uuid.UUID]:
    return list(db.execute(stmt).scalars())


def expire_uploads(factory: sessionmaker, now: dt.datetime, store: ObjectStore, counts: Counter) -> None:
    with factory() as db:
        ids = _ids(db, select(DrawingUpload.upload_id).where(DrawingUpload.state.in_(OPEN_UPLOADS),
                                                             DrawingUpload.expires_at <= now))
    for upload_id in ids:
        with factory() as db:
            upload = db.get(DrawingUpload, upload_id)
            sample = repository.lock_sample(db, upload.sample_id)
            upload = repository.lock_upload(db, upload_id)
            if upload.state not in OPEN_UPLOADS or upload.expires_at > now:
                continue
            upload.state, upload.last_error_code, upload.updated_at = "expired", "UPLOAD_EXPIRED", now
            if sample.active_upload_id == upload.upload_id and sample.state in ("pending_upload", "uploaded"):
                sample.state, sample.last_error_code, sample.updated_at = "upload_failed", "UPLOAD_EXPIRED", now
            db.commit()
            store.delete(upload.object_key)
            counts["uploads_expired"] += 1


def apply_retention(factory: sessionmaker, settings: Settings, now: dt.datetime, counts: Counter) -> None:
    days = settings.collection.verified_days
    if days <= 0:
        return
    cutoff = now - dt.timedelta(days=days)
    with factory() as db:
        ids = _ids(db, select(DrawingSample.sample_id).where(DrawingSample.state == "verified",
                                                             DrawingSample.verified_at < cutoff))
    for sample_id in ids:
        with factory() as db:
            sample = repository.lock_sample(db, sample_id)
            if sample.state != "verified":
                continue
            sample.state, sample.deletion_requested_at, sample.updated_at = "delete_pending", now, now
            sample.last_error_code = "RETENTION_EXPIRED"
            db.commit()
            counts["retention_expired"] += 1


def delete_pending(factory: sessionmaker, now: dt.datetime, store: ObjectStore, counts: Counter) -> None:
    with factory() as db:
        ids = _ids(db, select(DrawingSample.sample_id).where(DrawingSample.state == "delete_pending"))
    for sample_id in ids:
        with factory() as db:
            sample = repository.lock_sample(db, sample_id)
            if sample.state != "delete_pending":
                continue
            uploads = list(db.execute(select(DrawingUpload).where(DrawingUpload.sample_id == sample_id)
                                      .with_for_update()).scalars())
            keys = [u.object_key for u in uploads] + store.list(f"verified/{sample_id}")
            for key in keys:
                store.delete(key)
            for upload in uploads:
                if upload.state in OPEN_UPLOADS:
                    upload.state, upload.last_error_code, upload.updated_at = "expired", "SAMPLE_DELETED", now
            sample.state, sample.deleted_at, sample.updated_at = "deleted", now, now
            db.commit()
            counts["samples_deleted"] += 1


def remove_orphans(factory: sessionmaker, store: ObjectStore, counts: Counter) -> None:
    with factory() as db:
        for key in store.list("tmp"):
            try:
                upload_id = uuid.UUID(key.removeprefix("tmp/").removesuffix(".json"))
            except ValueError:
                upload_id = None
            upload = db.get(DrawingUpload, upload_id) if upload_id else None
            if upload is None or upload.object_key != key or upload.state not in OPEN_UPLOADS:
                store.delete(key)
                counts["orphan_tmp_removed"] += 1
        for key in store.list("verified"):
            parts = key.split("/")
            try:
                sample = db.get(DrawingSample, uuid.UUID(parts[1])) if len(parts) == 3 else None
            except ValueError:
                sample = None
            in_flight = sample is not None and sample.state in ("pending_upload", "uploaded", "upload_failed")
            current = sample is not None and sample.state == "verified" and sample.verified_object_key == key
            if not (in_flight or current):
                store.delete(key)
                counts["orphan_verified_removed"] += 1


def _ids_in(path: Path, key: str | None) -> set[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(x) for x in data[key]} if key else {str(x["sampleId"]) for x in data}


def purge_derived(factory: sessionmaker, settings: Settings, counts: Counter) -> list[str]:
    """Remove copies of deleted drawings outside the object store; returns datasets that still contain some."""
    with factory() as db:
        deleted = {str(i) for i in _ids(db, select(DrawingSample.sample_id).where(
            DrawingSample.state.in_(repository.DELETION_STATES)))}
    if not deleted:
        return []
    root = Path(settings.artifact_root)
    for pattern, key, name in (("data/collected/review/*/batch.json", "sampleIds", "review_batches_removed"),
                               ("data/collected/exports/*/manifest.json", "sampleIds", "exports_removed")):
        for path in root.glob(pattern):
            if _ids_in(path, key) & deleted:
                shutil.rmtree(path.parent)
                counts[name] += 1
    flagged = []
    datasets = root / "data/datasets"
    for path in datasets.glob("*/samples.json"):
        if not _ids_in(path, None) & deleted:
            continue
        version = path.parent.name
        if settings.collection.derived_datasets == "delete":
            for manifest in datasets.glob("*/manifest.public.json"):  # composites built on this dataset
                parts = json.loads(manifest.read_text(encoding="utf-8")).get("parts", [])
                if any(p["version"] == version for p in parts):
                    shutil.rmtree(manifest.parent)
                    counts["composites_removed"] += 1
            shutil.rmtree(path.parent)
            counts["datasets_removed"] += 1
        else:
            flagged.append(version)
    return flagged


def run(factory: sessionmaker, settings: Settings, store: ObjectStore, now: dt.datetime) -> dict:
    counts: Counter = Counter()
    expire_uploads(factory, now, store, counts)
    apply_retention(factory, settings, now, counts)
    delete_pending(factory, now, store, counts)
    remove_orphans(factory, store, counts)
    flagged = purge_derived(factory, settings, counts)
    return dict(counts) | ({"datasets_with_deleted_drawings": flagged} if flagged else {})
