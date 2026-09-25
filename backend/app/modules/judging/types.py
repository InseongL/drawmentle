"""Internal judging types. Separate from HTTP schemas; built by the release loader or offline tools."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

import numpy as np


def content_sha256(ids, arrays: Mapping[str, np.ndarray]) -> str:
    """Hash of category order + array values; independent of npz/zip timestamps."""
    h = hashlib.sha256(json.dumps(list(ids)).encode())
    for name in sorted(arrays):
        a = np.ascontiguousarray(arrays[name], dtype=np.float64)
        h.update(name.encode()); h.update(np.nan_to_num(a, nan=-1.0).tobytes())
    return h.hexdigest()


class UnsupportedCandidateError(ValueError):
    """A Top-3 candidate has no score-table entry (e.g. the unsupported `bird`)."""


@dataclass(frozen=True)
class ScoreTable:
    """Precomputed relation scores between score-supported categories of one scoring version.

    `relation[a, c]` is R(c, a) in [0, 1] with R(a, a) = 1. `modules[m][a, c]` is the calibrated
    per-axis score, or NaN when the axis was excluded for that pair.
    """

    version: str
    ids: tuple[str, ...]
    relation: np.ndarray
    modules: Mapping[str, np.ndarray]
    weights: Mapping[str, float]
    display_scale: float = 100.0
    display_decimals: int = 2
    rank_decimals: int = 6
    _index: Mapping[str, int] = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        n = len(self.ids)
        if len(set(self.ids)) != n:
            raise ValueError("duplicate category ids in score table")
        if self.relation.shape != (n, n) or any(m.shape != (n, n) for m in self.modules.values()):
            raise ValueError("score table matrices must be square and match ids")
        object.__setattr__(self, "_index", MappingProxyType({c: i for i, c in enumerate(self.ids)}))

    @classmethod
    def from_artifact(cls, arrays: Mapping[str, np.ndarray], manifest: dict) -> "ScoreTable":
        """Build from score-table.npz arrays and its manifest.json (scripts/scoring/build_score_table.py)."""
        return cls(manifest["version"], tuple(manifest["ids"]), arrays["relation"],
                   {m: arrays[m] for m in manifest["weights"]}, manifest["weights"], manifest["display"]["scale"],
                   manifest["display"]["decimals"], manifest["ranking"]["compare_decimals"])

    def index(self, category_id: str) -> int:
        try:
            return self._index[category_id]
        except KeyError:
            raise UnsupportedCandidateError(category_id) from None

    def supports(self, category_id: str) -> bool:
        return category_id in self._index


@dataclass(frozen=True)
class CandidateScore:
    category_id: str
    p: float
    q: float
    relation: float
    modules: Mapping[str, float | None]
    relation_rank: int


@dataclass(frozen=True)
class MixResult:
    answer_id: str
    mixed: float
    display_score: float
    display_text: str
    candidates: tuple[CandidateScore, ...]
