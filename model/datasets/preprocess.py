"""Stroke -> model input rendering, `qd-strokes-64-v1` (docs/model-architecture-v1.md §4.3).

Defined as arithmetic, not as a graphics library call, so the browser can reproduce it exactly:

1. Normalise: scale the drawing so its longest bounding-box side spans SPAN px (aspect ratio kept) and put the
   box centre at the image centre (continuous coordinate SIZE/2, i.e. pixel index 31.5).
2. Sample a SS x SS grid inside every output pixel (sample centres at (i + (k + 0.5) / SS)).
3. A sample is ink when its distance to any stroke segment (or to a single-point stroke) is <= RADIUS.
4. Pixel value = round(255 * ink_samples / SS^2). Background 0, ink 255, uint8.

Input strokes are lists of (xs, ys) like Quick Draw `drawing`, in any coordinate unit.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class RenderSpec:
    version: str
    size: int
    span: float
    radius: float
    supersample: int


QD_STROKES_64_V1 = RenderSpec(version="qd-strokes-64-v1", size=64, span=48.0, radius=2.0, supersample=4)


def normalise(drawing, spec: RenderSpec) -> list[np.ndarray]:
    """Strokes as float64 (n, 2) arrays in output-pixel coordinates."""
    strokes = [np.asarray(list(zip(xs, ys)), dtype=np.float64) for xs, ys in drawing if len(xs)]
    if not strokes:
        raise ValueError("empty drawing")
    pts = np.concatenate(strokes)
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    scale = spec.span / max(float((hi - lo).max()), 1.0)
    centre = (lo + hi) / 2
    return [(s - centre) * scale + spec.size / 2 for s in strokes]


def _segments(strokes: list[np.ndarray]) -> np.ndarray:
    """(m, 4) segments x0, y0, x1, y1; a single-point stroke becomes a zero-length segment."""
    parts = []
    for s in strokes:
        if len(s) == 1:
            parts.append(np.concatenate([s, s], axis=1))
        else:
            parts.append(np.concatenate([s[:-1], s[1:]], axis=1))
    return np.concatenate(parts)


def render(drawing, spec: RenderSpec = QD_STROKES_64_V1) -> np.ndarray:
    ss, n = spec.supersample, spec.size * spec.supersample
    coords = (np.arange(n, dtype=np.float64) + 0.5) / ss  # sample centres in output-pixel units
    ink = np.zeros((n, n), dtype=bool)  # [row = y, col = x]
    r, r2 = spec.radius, spec.radius * spec.radius
    for x0, y0, x1, y1 in _segments(normalise(drawing, spec)):
        # Only samples inside the segment's bounding box grown by the radius can be ink.
        c0 = max(int(np.floor((min(x0, x1) - r) * ss)), 0)
        c1 = min(int(np.ceil((max(x0, x1) + r) * ss)) + 1, n)
        r0 = max(int(np.floor((min(y0, y1) - r) * ss)), 0)
        r1 = min(int(np.ceil((max(y0, y1) + r) * ss)) + 1, n)
        if c0 >= c1 or r0 >= r1:
            continue
        px = coords[c0:c1][None, :] - x0
        py = coords[r0:r1][:, None] - y0
        dx, dy = x1 - x0, y1 - y0
        length2 = dx * dx + dy * dy
        if length2 > 0:
            t = np.clip((px * dx + py * dy) / length2, 0.0, 1.0)
            ex, ey = px - t * dx, py - t * dy
        else:
            ex, ey = px, py
        ink[r0:r1, c0:c1] |= ex * ex + ey * ey <= r2
    counts = ink.reshape(spec.size, ss, spec.size, ss).sum(axis=(1, 3))
    return np.floor(counts * 255 / (ss * ss) + 0.5).astype(np.uint8)


def to_tensor_array(images: np.ndarray) -> np.ndarray:
    """uint8 [N, H, W] -> float32 [N, 1, H, W] in 0..1 (no ImageNet mean/std)."""
    return (images.astype(np.float32) / 255.0)[:, None]
