"""Anonymous session rows. Only the token hash is stored."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AnonymousSession


def get_by_token_hash(db: Session, token_hash: str) -> AnonymousSession | None:
    return db.execute(select(AnonymousSession).where(AnonymousSession.token_hash == token_hash)).scalar_one_or_none()


def lock(db: Session, session_id: uuid.UUID) -> AnonymousSession | None:
    stmt = (select(AnonymousSession).where(AnonymousSession.session_id == session_id)
            .with_for_update().execution_options(populate_existing=True))
    return db.execute(stmt).scalar_one_or_none()


def add(db: Session, row: AnonymousSession) -> None:
    db.add(row)
