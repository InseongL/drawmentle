"""Anonymous cookie sessions: issue, reuse while valid, authenticate. Consent changes belong to collections."""
from __future__ import annotations

import datetime as dt
import hashlib
import secrets
import uuid

from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.settings import Settings
from app.db.models import AnonymousSession

from . import repository
from .schemas import CollectionOut, SessionContext, SessionOut


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _valid(row: AnonymousSession | None, now: dt.datetime) -> bool:
    return row is not None and row.expires_at > now


def ensure(db: Session, settings: Settings, token: str | None, now: dt.datetime) -> tuple[AnonymousSession, str | None]:
    """Return (session, new_token). new_token is None when the presented cookie is still valid."""
    if token:
        row = repository.get_by_token_hash(db, hash_token(token))
        if _valid(row, now):
            return row, None
    token = secrets.token_urlsafe(32)
    row = AnonymousSession(session_id=uuid.uuid4(), token_hash=hash_token(token), created_at=now,
                           expires_at=now + dt.timedelta(days=settings.session_ttl_days),
                           consent_revision=0, collection_enabled=False)
    repository.add(db, row)
    db.commit()
    return row, token


def authenticate(db: Session, token: str | None, now: dt.datetime) -> SessionContext:
    if not token:
        raise ApiError(401, "SESSION_REQUIRED", "세션이 필요해요. 페이지를 새로고침해주세요.")
    row = repository.get_by_token_hash(db, hash_token(token))
    if row is None:
        raise ApiError(401, "SESSION_REQUIRED", "세션이 필요해요. 페이지를 새로고침해주세요.")
    if not _valid(row, now):
        raise ApiError(401, "SESSION_EXPIRED", "세션이 만료됐어요. 페이지를 새로고침해주세요.")
    return SessionContext(row.session_id, row.expires_at, row.consent_revision)


def collection_view(consent_revision: int) -> CollectionOut:
    # Collection is disabled (collection-disabled-v0): nobody can consent yet.
    return CollectionOut(state="not_consented", consentRevision=consent_revision)


def session_view(row: AnonymousSession) -> SessionOut:
    return SessionOut(expiresAt=row.expires_at.astimezone(dt.timezone.utc),
                      collection=collection_view(row.consent_revision))
