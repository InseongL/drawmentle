"""Submission request/response types (docs/api-contract-v1.md §4-7). camelCase JSON, unknown fields rejected."""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_serializer

from app.modules.sessions.schemas import CollectionOut

HASH = r"^[0-9a-f]{64}$"
Version = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._\-]+$")]
CategoryId = Annotated[str, Field(min_length=1, max_length=64)]
Probability = Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]  # strict: no bools or strings


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Top3Item(_In):
    categoryId: CategoryId
    p: Probability


class SubmissionIn(_In):
    submissionId: uuid.UUID
    releaseId: Version
    modelVersion: Version
    preprocessingVersion: Version
    catalogVersion: Version
    outputCalibrationVersion: Version
    drawingVersion: Version
    brushVersion: Version
    drawingHash: str = Field(pattern=HASH)
    top3: list[Top3Item] = Field(min_length=3, max_length=3)
    collectionConsentRevision: int = Field(strict=True, ge=0)


class _Out(BaseModel):
    model_config = ConfigDict(frozen=True)


class AnswerOut(_Out):
    categoryId: str
    displayNameKo: str


class ResultOut(_Out):
    status: Literal["recognized", "deferred", "solved"]
    reason: str | None
    attemptNumber: int | None
    displayScore: float | None
    displayText: str | None
    solved: bool
    judgedAt: dt.datetime
    answer: AnswerOut | None = None  # present only when solved

    @model_serializer(mode="wrap")
    def _omit_answer(self, handler):
        data = handler(self)
        if self.answer is None:
            data.pop("answer", None)
        return data


class ProgressOut(_Out):
    state: Literal["playing", "solved"]
    attemptCount: int
    bestSubmissionId: uuid.UUID | None
    bestDisplayScore: float | None
    bestDisplayText: str | None
    solvedSubmissionId: uuid.UUID | None = None  # both present only when solved
    answer: AnswerOut | None = None

    @model_serializer(mode="wrap")
    def _omit_unsolved(self, handler):
        data = handler(self)
        if self.state != "solved":
            data.pop("solvedSubmissionId", None)
            data.pop("answer", None)
        return data


class SubmissionOut(_Out):
    requestSubmissionId: uuid.UUID
    submissionId: uuid.UUID
    puzzleId: str
    releaseId: str
    reuse: Literal["new", "request_retry", "drawing_duplicate"]
    result: ResultOut
    progress: ProgressOut
    collection: CollectionOut


class HistoryItem(_Out):
    submissionId: uuid.UUID
    result: ResultOut


class ProgressPage(_Out):
    puzzleId: str
    progress: ProgressOut
    items: list[HistoryItem]
    nextBeforeAttemptNumber: int | None
