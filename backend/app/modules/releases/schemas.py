"""Public/private release manifests. The public one is served as-is in puzzle responses; the private one never is."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

HASH = r"^[0-9a-f]{64}$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RawClass(_Strict):
    classIndex: int = Field(ge=0)
    categoryId: str
    candidateId: str


class Candidate(_Strict):
    categoryId: str
    candidateIndex: int = Field(ge=0)
    displayNameKo: str


class Inference(_Strict):
    mode: Literal["dev_manual_top3", "browser_onnx"]
    probability: str
    outputCalibration: str
    note: str | None = None


class PublicManifest(_Strict):
    """Everything the browser needs to produce a valid Top-3. No answer, thresholds, attributes or score table."""
    manifestVersion: Literal["release-public-v1"]
    releaseId: str
    status: Literal["dev-only", "production"]
    modelVersion: str
    preprocessingVersion: str
    catalogVersion: str
    outputCalibrationVersion: str
    drawingVersions: list[str] = Field(min_length=1)
    brushVersions: list[str] = Field(min_length=1)
    model: dict | None
    inference: Inference
    rawClasses: list[RawClass]
    rawClassesSha256: str = Field(pattern=HASH)
    candidates: list[Candidate]
    candidatesSha256: str = Field(pattern=HASH)


class ScoreTableRef(_Strict):
    file: str
    manifestFile: str
    version: str
    contentSha256: str = Field(pattern=HASH)


class AnswerEntry(_Strict):
    displayNameKo: str
    daily: bool


class PrivateManifest(_Strict):
    manifestVersion: Literal["release-private-v1"]
    releaseId: str
    publicManifestSha256: str = Field(pattern=HASH)
    scoreTable: ScoreTableRef
    recognition: dict
    answers: dict[str, AnswerEntry]
