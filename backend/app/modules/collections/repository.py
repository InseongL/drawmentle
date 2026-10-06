"""Consent history, samples and uploads. Never commits; the collections service owns the transaction.

Lock order everywhere: anonymous session -> game -> sample -> upload.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import CollectionConsent, DrawingSample, DrawingUpload, LabelReview

DELETION_STATES = ("delete_pending", "deleted")


def ensure_consent_row(db: Session, session_id: uuid.UUID, revision: int, enabled: bool, policy: str | None,
                       changed_at) -> None:
    """Sessions created before the history table get their current revision as a row (idempotent)."""
    db.execute(insert(CollectionConsent).values(session_id=session_id, revision=revision, enabled=enabled,
                                                policy_version=policy, changed_at=changed_at)
               .on_conflict_do_nothing())


def add_consent(db: Session, row: CollectionConsent) -> None:
    db.add(row)


def get_consent(db: Session, session_id: uuid.UUID, revision: int) -> CollectionConsent | None:
    return db.get(CollectionConsent, (session_id, revision))


def _locked(stmt):
    return stmt.with_for_update().execution_options(populate_existing=True)


def get_sample_for_submission(db: Session, submission_id: uuid.UUID) -> DrawingSample | None:
    return db.execute(select(DrawingSample).where(DrawingSample.submission_id == submission_id)).scalar_one_or_none()


def lock_sample_for_submission(db: Session, submission_id: uuid.UUID) -> DrawingSample | None:
    return db.execute(_locked(select(DrawingSample).where(DrawingSample.submission_id == submission_id))
                      ).scalar_one_or_none()


def lock_sample(db: Session, sample_id: uuid.UUID) -> DrawingSample | None:
    return db.execute(_locked(select(DrawingSample).where(DrawingSample.sample_id == sample_id))).scalar_one_or_none()


def lock_upload(db: Session, upload_id: uuid.UUID) -> DrawingUpload | None:
    return db.execute(_locked(select(DrawingUpload).where(DrawingUpload.upload_id == upload_id))).scalar_one_or_none()


def lock_samples_of_session(db: Session, session_id: uuid.UUID, states: Iterable[str]) -> list[DrawingSample]:
    stmt = select(DrawingSample).where(DrawingSample.session_id == session_id, DrawingSample.state.in_(tuple(states)))
    return list(db.execute(_locked(stmt.order_by(DrawingSample.sample_id))).scalars())


def open_uploads_of(db: Session, sample_ids: list[uuid.UUID]) -> list[DrawingUpload]:
    if not sample_ids:
        return []
    stmt = select(DrawingUpload).where(DrawingUpload.sample_id.in_(sample_ids),
                                       DrawingUpload.state.in_(("issued", "received")))
    return list(db.execute(_locked(stmt.order_by(DrawingUpload.upload_id))).scalars())


def latest_review(db: Session, sample_id: uuid.UUID) -> LabelReview | None:
    stmt = (select(LabelReview).where(LabelReview.sample_id == sample_id)
            .order_by(LabelReview.revision.desc()).limit(1))
    return db.execute(stmt).scalar_one_or_none()


def next_review_revision(db: Session, sample_id: uuid.UUID) -> int:
    """Caller holds the sample lock."""
    current = db.execute(select(func.max(LabelReview.revision)).where(LabelReview.sample_id == sample_id)).scalar()
    return (current or 0) + 1
