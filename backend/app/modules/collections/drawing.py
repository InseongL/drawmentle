"""strokes-v1 drawing files (docs/model-architecture-v1.md §4.1).

The browser hashes `JSON.stringify({drawingVersion, coordinateMax, brushVersion, strokes})` with integer points.
An uploaded file is accepted only if it parses to that document, re-serialises to the exact same bytes, stays within
the configured limits, and its SHA-256 equals the submission's drawing hash. Nothing is truncated silently.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from app.core.collection_config import UploadLimits

DRAWING_VERSION, BRUSH_VERSION = "strokes-v1", "pen-v1"
KEYS = ("drawingVersion", "coordinateMax", "brushVersion", "strokes")


class InvalidDrawing(ValueError):
    pass


@dataclass(frozen=True)
class CheckedDrawing:
    strokes: list[list[list[int]]]
    stroke_count: int
    point_count: int
    sha256: str


def serialise(strokes: list[list[list[int]]], coordinate_max: int) -> bytes:
    doc = {"drawingVersion": DRAWING_VERSION, "coordinateMax": coordinate_max, "brushVersion": BRUSH_VERSION,
           "strokes": strokes}
    return json.dumps(doc, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def check(data: bytes, limits: UploadLimits) -> CheckedDrawing:
    if len(data) > limits.max_bytes:
        raise InvalidDrawing("too_large")
    try:
        doc = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise InvalidDrawing("not_json") from None
    if not isinstance(doc, dict) or tuple(doc) != KEYS:
        raise InvalidDrawing("wrong_fields")
    if doc["drawingVersion"] != DRAWING_VERSION or doc["brushVersion"] != BRUSH_VERSION \
            or doc["coordinateMax"] != limits.coordinate_max:
        raise InvalidDrawing("wrong_version")
    strokes = doc["strokes"]
    if not isinstance(strokes, list) or not 0 < len(strokes) <= limits.max_strokes:
        raise InvalidDrawing("stroke_count")
    points = 0
    for stroke in strokes:
        if not isinstance(stroke, list) or not 0 < len(stroke) <= limits.max_points_per_stroke:
            raise InvalidDrawing("stroke_points")
        for pt in stroke:
            if (not isinstance(pt, list) or len(pt) != 2
                    or not all(type(v) is int and 0 <= v <= limits.coordinate_max for v in pt)):
                raise InvalidDrawing("point")
        points += len(stroke)
    if points > limits.max_points:
        raise InvalidDrawing("point_count")
    if serialise(strokes, limits.coordinate_max) != data:
        raise InvalidDrawing("not_canonical")
    return CheckedDrawing(strokes, len(strokes), points, hashlib.sha256(data).hexdigest())
