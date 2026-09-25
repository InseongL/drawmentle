"""Deferral and success checks around mix_top3 (docs/judging-criteria-v1.md §1-3).

Pure function of (score table, rules, answer, validated Top-3). Storing the result is the submissions service's job.
Top-3 order and candidate-ID validity are checked at the API boundary; p here is the original full-catalog p.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Sequence

import numpy as np

from .scorer import mix_top3
from .types import MixResult, ScoreTable

DETAILS_VERSION = "score-details-v1"


@dataclass(frozen=True)
class RecognitionRules:
    version: str
    success_min_p: float
    min_top1_p: float | None = None
    min_top3_sum: float | None = None
    min_known_axes: int = 1
    success_min_margin: float | None = None

    @classmethod
    def from_config(cls, cfg: dict) -> "RecognitionRules":
        rules = cls(version=cfg["version"], success_min_p=cfg["success_min_p"], min_top1_p=cfg.get("min_top1_p"),
                    min_top3_sum=cfg.get("min_top3_sum"), min_known_axes=cfg.get("min_known_axes", 1),
                    success_min_margin=cfg.get("success_min_margin"))
        for name in ("success_min_p", "min_top1_p", "min_top3_sum", "success_min_margin"):
            value = getattr(rules, name)
            if value is not None and not (math.isfinite(value) and 0 <= value <= 1):
                raise ValueError(f"{name} must be within [0, 1]")
        return rules


@dataclass(frozen=True)
class Judgement:
    status: str  # recognized / deferred / solved
    reason: str | None
    mix: MixResult | None

    @property
    def counted(self) -> bool:
        return self.status != "deferred"


def _deferral(table: ScoreTable, rules: RecognitionRules, answer_id: str,
              top3: Sequence[tuple[str, float]]) -> str | None:
    """First matching deferral reason, in the order of judging-criteria §2."""
    total = sum(p for _, p in top3)
    if total <= 0:
        return "low_confidence"
    if not all(table.supports(c) for c, _ in top3):
        return "unsupported_candidate"
    if rules.min_top1_p is not None and top3[0][1] < rules.min_top1_p:
        return "low_confidence"
    if rules.min_top3_sum is not None and total < rules.min_top3_sum:
        return "low_confidence"
    a = table.index(answer_id)
    for c, _ in top3:
        known = sum(not np.isnan(m[a, table.index(c)]) for m in table.modules.values())
        if known < rules.min_known_axes:
            return "insufficient_attributes"
    return None


def judge(table: ScoreTable, rules: RecognitionRules, answer_id: str,
          top3: Sequence[tuple[str, float]]) -> Judgement:
    if not table.supports(answer_id):
        raise ValueError(f"answer {answer_id!r} is not score-supported")  # release/puzzle error, not a user input
    reason = _deferral(table, rules, answer_id, top3)
    if reason:
        return Judgement("deferred", reason, None)
    mix = mix_top3(table, answer_id, top3)
    (top1, p1), (_, p2) = top3[0], top3[1]
    solved = (top1 == answer_id and p1 >= rules.success_min_p
              and (rules.success_min_margin is None or p1 - p2 >= rules.success_min_margin))
    return Judgement("solved" if solved else "recognized", None, mix)


def score_details(judgement: Judgement, rules: RecognitionRules, table: ScoreTable, answer_id: str,
                  top3: Sequence[tuple[str, float]]) -> dict:
    """Private calculation record for submission_score_details. Never part of a public response."""
    details = {
        "detailsVersion": DETAILS_VERSION,
        "scoringVersion": table.version,
        "recognition": asdict(rules),
        "answerId": answer_id,
        "status": judgement.status,
        "reason": judgement.reason,
        "top3": [{"categoryId": c, "p": p} for c, p in top3],
        "mixed": None,
        "candidates": None,
    }
    if judgement.mix:
        details["mixed"] = judgement.mix.mixed
        details["candidates"] = [
            {"categoryId": c.category_id, "p": c.p, "q": c.q, "relation": c.relation,
             "relationRank": c.relation_rank, "modules": dict(c.modules)}
            for c in judgement.mix.candidates]
    return details
