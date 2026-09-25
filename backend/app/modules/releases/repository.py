"""Release bundle rows. Rows are immutable once inserted."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import ReleaseBundle


def get_bundle(db: Session, release_id: str) -> ReleaseBundle | None:
    return db.get(ReleaseBundle, release_id)


def add_bundle(db: Session, bundle: ReleaseBundle) -> None:
    db.add(bundle)
