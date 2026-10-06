"""Consent and drawing-upload types (docs/api-contract-v1.md §8). camelCase JSON, unknown fields rejected."""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.sessions.schemas import CollectionOut

Revision = Annotated[int, Field(strict=True, ge=0)]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _Out(BaseModel):
    model_config = ConfigDict(frozen=True)


class ConsentIn(_In):
    expectedRevision: Revision
    enabled: Annotated[bool, Field(strict=True)]
    policyVersion: Annotated[str, Field(min_length=1, max_length=64)] | None = None


class ConsentOut(_Out):
    enabled: bool
    policyVersion: str | None
    collection: CollectionOut


class UploadIn(_In):
    consentRevision: Revision


class UploadGrant(_Out):
    sampleId: uuid.UUID
    uploadId: uuid.UUID
    method: Literal["PUT"]
    url: str
    contentType: Literal["application/json"]
    maxBytes: int
    expiresAt: dt.datetime


class UploadOut(_Out):
    collection: CollectionOut
    grant: UploadGrant | None


class CompleteIn(_In):
    sampleId: uuid.UUID
    uploadId: uuid.UUID
    consentRevision: Revision


class CompleteOut(_Out):
    collection: CollectionOut
