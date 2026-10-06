"""Collection operating settings (config/collection/collection.json, docs/mlops-v1.md §3).

Sampling rates, upload limits, retention, storage and review display are operational values: changing them needs a
server restart, never a code change. Past submissions keep the selection they were given.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DISABLED_POLICY = "collection-disabled-v0"


@dataclass(frozen=True)
class Sampling:
    version: str
    success_rate: float
    failure_rate: float
    deferred_rate: float


@dataclass(frozen=True)
class UploadLimits:
    grant_ttl_seconds: int
    max_bytes: int
    max_strokes: int
    max_points_per_stroke: int
    max_points: int
    coordinate_max: int


@dataclass(frozen=True)
class CollectionConfig:
    version: str
    enabled: bool
    notice_version: str
    training_notice_versions: tuple[str, ...]
    sampling: Sampling
    upload: UploadLimits
    verified_days: int          # 0 = no age limit
    temp_hours: int
    derived_datasets: str       # "report" or "delete" user datasets that contain deleted drawings
    storage_backend: str
    storage_root: str           # relative to the artifact root
    review_show_prediction: bool
    review_show_answer: bool
    export_group_salt: str

    @property
    def selection_policy(self) -> str:
        """Recorded on every submission: which sampling rule decided its selection."""
        return self.sampling.version if self.enabled else DISABLED_POLICY

    @classmethod
    def from_dict(cls, d: dict) -> "CollectionConfig":
        s, u, r = d["sampling"], d["upload"], d["retention"]
        cfg = cls(
            version=d["version"], enabled=bool(d["enabled"]), notice_version=d["notice_version"],
            training_notice_versions=tuple(d["training_notice_versions"]),
            sampling=Sampling(s["version"], float(s["success_rate"]), float(s["failure_rate"]),
                              float(s["deferred_rate"])),
            upload=UploadLimits(*(int(u[k]) for k in ("grant_ttl_seconds", "max_bytes", "max_strokes",
                                                      "max_points_per_stroke", "max_points", "coordinate_max"))),
            verified_days=int(r["verified_days"]), temp_hours=int(r["temp_hours"]),
            derived_datasets=r.get("derived_datasets", "report"),
            storage_backend=d["storage"]["backend"], storage_root=d["storage"]["root"],
            review_show_prediction=bool(d["review"]["show_model_prediction"]),
            review_show_answer=bool(d["review"]["show_puzzle_answer"]),
            export_group_salt=d["export"]["group_salt"])
        cfg.check()
        return cfg

    @classmethod
    def load(cls, path: Path) -> "CollectionConfig":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8-sig")))

    def check(self) -> None:
        rates = (self.sampling.success_rate, self.sampling.failure_rate, self.sampling.deferred_rate)
        if not all(0.0 <= r <= 1.0 for r in rates):
            raise ValueError("collection sampling rates must be between 0 and 1")
        if self.sampling.version == DISABLED_POLICY or not self.notice_version:
            raise ValueError("collection needs a sampling version and a notice version")
        if min(self.upload.grant_ttl_seconds, self.upload.max_bytes, self.upload.max_strokes,
               self.upload.max_points_per_stroke, self.upload.max_points, self.upload.coordinate_max) <= 0:
            raise ValueError("collection upload limits must be positive")
        if self.verified_days < 0 or self.temp_hours <= 0:
            raise ValueError("collection retention must be >= 0 days and > 0 temp hours")
        if self.derived_datasets not in ("report", "delete"):
            raise ValueError("retention.derived_datasets must be report or delete")
        if self.storage_backend != "local":
            raise ValueError(f"unsupported collection storage backend: {self.storage_backend}")
