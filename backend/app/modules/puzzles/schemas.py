"""Public puzzle responses. Never contain the answer."""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict

from app.modules.releases.schemas import PublicManifest


class CollectionPolicyOut(BaseModel):
    model_config = ConfigDict(frozen=True)
    version: str
    enabled: bool


class PuzzleOut(BaseModel):
    model_config = ConfigDict(frozen=True)
    puzzleId: str
    serviceDate: dt.date
    puzzleNumber: int
    release: PublicManifest
    collectionPolicy: CollectionPolicyOut
