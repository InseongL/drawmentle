"""Anonymous session responses and the authenticated context passed to other modules."""
from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict

CollectionState = Literal["not_consented", "not_selected", "eligible", "pending_upload", "uploaded", "verified",
                          "upload_failed", "delete_pending", "deleted"]


class _Out(BaseModel):
    model_config = ConfigDict(frozen=True)


class CollectionOut(_Out):
    state: CollectionState
    consentRevision: int


class SessionOut(_Out):
    expiresAt: dt.datetime
    collection: CollectionOut


@dataclass(frozen=True)
class SessionContext:
    session_id: uuid.UUID
    expires_at: dt.datetime
    consent_revision: int
