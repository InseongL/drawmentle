"""Top-3 mixing, display score and relation rank on a precomputed ScoreTable.

Recognition checks (deferral, success) belong to judge.py; this module assumes candidates already passed them.
"""
from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal
from typing import Sequence

import numpy as np

from .types import CandidateScore, MixResult, ScoreTable, UnsupportedCandidateError


def display(mixed: float, scale: float, decimals: int) -> tuple[float, str]:
    """Half-up rounding so the server string is the single source of truth for the UI."""
    text = str(Decimal(repr(mixed * scale)).quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP))
    return float(text), text


def relation_rank(table: ScoreTable, answer_id: str, candidate_id: str) -> int:
    """Answer is rank 1; others 2 + count of strictly higher relation scores (shared ranks for ties)."""
    a, c = table.index(answer_id), table.index(candidate_id)
    if a == c:
        return 1
    row = np.round(table.relation[a], table.rank_decimals)
    others = np.delete(row, a)
    return 2 + int((others > row[c]).sum())


def mix_top3(table: ScoreTable, answer_id: str, top3: Sequence[tuple[str, float]]) -> MixResult:
    """mixed = sum(q_i * R(c_i, answer)) with q_i = p_i / sum(p). p must keep full-catalog normalisation."""
    if len(top3) != 3 or len({c for c, _ in top3}) != 3:
        raise ValueError("top3 must contain three distinct candidates")
    ps = [float(p) for _, p in top3]
    if any(not math.isfinite(p) or p < 0 or p > 1 for p in ps):
        raise ValueError("candidate p must be finite and within [0, 1]")
    total = sum(ps)
    if total <= 0:
        raise ValueError("top3 probabilities sum to zero; defer instead of mixing")
    a = table.index(answer_id)
    for c, _ in top3:
        if not table.supports(c):
            raise UnsupportedCandidateError(c)
    scores = []
    mixed = 0.0
    for (c, p) in top3:
        i = table.index(c)
        q = p / total
        r = float(table.relation[a, i])
        mixed += q * r
        mods = {m: (None if np.isnan(s[a, i]) else float(s[a, i])) for m, s in table.modules.items()}
        scores.append(CandidateScore(c, p, q, r, mods, relation_rank(table, answer_id, c)))
    score, text = display(mixed, table.display_scale, table.display_decimals)
    return MixResult(answer_id, mixed, score, text, tuple(scores))
