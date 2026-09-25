"""Per-axis similarity and relation-score maths shared by the online judge and offline score-table tools.

Pure numpy functions: no FastAPI, DB, environment or file access. Rules are described in docs/scoring-v1.md.
"""
from __future__ import annotations

import math
from collections import Counter
from typing import Mapping, Sequence

import numpy as np

TagLists = Sequence[Sequence[str] | None]  # None = axis not known (uncertain / not_applicable)


def idf_weights(tag_lists: TagLists, min_df: int = 2) -> dict[str, float]:
    """ln((N+1)/(max(df, min_df)+1)) + 1 over the categories being compared.

    min_df caps the weight of tags used by fewer categories; a unique tag can never match anything,
    so it must not dominate its own vector.
    """
    n = len(tag_lists)
    df = Counter(t for tags in tag_lists if tags for t in set(tags))
    return {t: math.log((n + 1) / (max(c, min_df) + 1)) + 1 for t, c in df.items()}


def family_matrix(vocab: Sequence[str], families: Mapping[str, Sequence[str]], partial: float) -> np.ndarray:
    """Tag-to-tag similarity: 1 on the diagonal, `partial` inside a family, 0 otherwise."""
    if not 0 <= partial < 1:
        raise ValueError("family partial credit must be in [0, 1)")
    family_of: dict[str, str] = {}
    for name, tags in families.items():
        for t in tags:
            if t in family_of:
                raise ValueError(f"tag {t} is in two families")
            family_of[t] = name
    pos = {t: i for i, t in enumerate(vocab)}
    unknown = set(family_of) - set(pos)
    if unknown:
        raise ValueError(f"family tags not in vocabulary: {sorted(unknown)}")
    s = np.eye(len(vocab))
    members: dict[str, list[int]] = {}
    for t, name in family_of.items():
        members.setdefault(name, []).append(pos[t])
    for idx in members.values():
        for i in idx:
            for j in idx:
                if i != j:
                    s[i, j] = partial
    return s


def tag_similarity(tag_lists: TagLists, vocab: Sequence[str], weights: Mapping[str, float],
                   tag_matrix: np.ndarray | None = None) -> np.ndarray:
    """Weighted (soft) cosine between every pair of tag sets. NaN where either side is unknown."""
    pos = {t: i for i, t in enumerate(vocab)}
    n = len(tag_lists)
    v = np.zeros((n, len(vocab)))
    known = np.zeros(n, bool)
    for i, tags in enumerate(tag_lists):
        if not tags:
            continue
        known[i] = True
        for t in tags:
            v[i, pos[t]] = weights[t]
    s = np.eye(len(vocab)) if tag_matrix is None else tag_matrix
    sv = v @ s
    norm = np.sqrt(np.einsum("ij,ij->i", sv, v))
    with np.errstate(invalid="ignore", divide="ignore"):
        out = (sv @ v.T) / np.outer(norm, norm)
    out = np.clip(out, 0.0, 1.0)
    out[~known, :] = np.nan
    out[:, ~known] = np.nan
    idx = np.flatnonzero(known)
    out[idx, idx] = 1.0
    return out


def cosine_matrix(vectors: np.ndarray) -> np.ndarray:
    unit = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
    return unit @ unit.T


def linear_calibration(values: np.ndarray, zero_at: float, one_at: float) -> np.ndarray:
    """Order-preserving map: values <= zero_at -> 0, >= one_at -> 1, linear in between."""
    if not one_at > zero_at:
        raise ValueError("calibration needs one_at > zero_at")
    return np.clip((values - zero_at) / (one_at - zero_at), 0.0, 1.0)


def off_diagonal(matrix: np.ndarray) -> np.ndarray:
    """Upper-triangle values of distinct pairs, ignoring NaN (used to derive calibration constants)."""
    x = matrix[np.triu_indices(matrix.shape[0], 1)]
    return x[~np.isnan(x)]


def combine(modules: Mapping[str, np.ndarray], weights: Mapping[str, float]) -> np.ndarray:
    """R = sum(w_m * s_m) / sum(w_m) over axes known for the pair (exclude-and-renormalise). R(a, a) = 1."""
    if set(modules) != set(weights):
        raise ValueError("module scores and weights must name the same axes")
    if any(w < 0 for w in weights.values()) or not math.isclose(sum(weights.values()), 1.0, abs_tol=1e-9):
        raise ValueError("axis weights must be non-negative and sum to 1")
    first = next(iter(modules.values()))
    num = np.zeros_like(first, dtype=float)
    den = np.zeros_like(first, dtype=float)
    for m, s in modules.items():
        ok = ~np.isnan(s)
        num += np.where(ok, weights[m] * np.nan_to_num(s), 0.0)
        den += np.where(ok, weights[m], 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        r = num / den
    np.fill_diagonal(r, 1.0)
    return r
