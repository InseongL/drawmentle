"""Verified, cached release artifacts. Incomplete or mismatching files are refused, never partially used."""
from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

import numpy as np
from pydantic import ValidationError

from app.db.models import ReleaseBundle
from app.modules.judging.judge import RecognitionRules
from app.modules.judging.types import ScoreTable, content_sha256

from .schemas import PrivateManifest, PublicManifest


class ReleaseUnavailable(Exception):
    """The release cannot judge new submissions (missing or mismatching artifacts)."""


def canonical_sha256(obj) -> str:
    """SHA-256 of sorted-key compact JSON, so formatting and line endings do not change the hash."""
    text = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


@dataclass(frozen=True)
class ReleaseCatalog:
    """Public part: enough to validate a request's versions and Top-3, even if private artifacts fail to load."""
    manifest: PublicManifest
    candidate_index: Mapping[str, int]

    @property
    def release_id(self) -> str:
        return self.manifest.releaseId

    def versions_match(self, model: str, preprocessing: str, catalog: str, calibration: str,
                       drawing: str, brush: str) -> bool:
        m = self.manifest
        return ((model, preprocessing, catalog, calibration)
                == (m.modelVersion, m.preprocessingVersion, m.catalogVersion, m.outputCalibrationVersion)
                and drawing in m.drawingVersions and brush in m.brushVersions)


@dataclass(frozen=True)
class ReleaseContext:
    """Private part used only by the judge."""
    catalog: ReleaseCatalog
    table: ScoreTable
    rules: RecognitionRules
    answer_names: Mapping[str, str]
    daily_answers: frozenset[str]


def build_catalog(bundle: ReleaseBundle) -> ReleaseCatalog:
    if canonical_sha256(bundle.public_manifest) != bundle.public_manifest_sha256:
        raise ReleaseUnavailable("public manifest hash mismatch")
    try:
        manifest = PublicManifest.model_validate(bundle.public_manifest)
    except ValidationError as exc:
        raise ReleaseUnavailable("invalid public manifest") from exc
    if manifest.releaseId != bundle.release_id:
        raise ReleaseUnavailable("public manifest release id mismatch")
    # Hash the stored lists, not re-serialised models: optional fields added later must not change old hashes.
    raw, cands = bundle.public_manifest["rawClasses"], bundle.public_manifest["candidates"]
    if canonical_sha256(raw) != manifest.rawClassesSha256 or canonical_sha256(cands) != manifest.candidatesSha256:
        raise ReleaseUnavailable("class mapping hash mismatch")
    index = {c.categoryId: c.candidateIndex for c in manifest.candidates}
    if len(index) != len(cands) or len(set(index.values())) != len(cands):
        raise ReleaseUnavailable("duplicate candidates")
    for r in manifest.rawClasses:
        if r.candidateId not in index:
            raise ReleaseUnavailable(f"raw class {r.categoryId} maps to unknown candidate")
    return ReleaseCatalog(manifest, MappingProxyType(index))


def load_context(root: Path, bundle: ReleaseBundle, catalog: ReleaseCatalog) -> ReleaseContext:
    path = root / bundle.private_manifest_key
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReleaseUnavailable("private manifest unreadable") from exc
    if canonical_sha256(raw) != bundle.private_manifest_sha256:
        raise ReleaseUnavailable("private manifest hash mismatch")
    try:
        private = PrivateManifest.model_validate(raw)
    except ValidationError as exc:
        raise ReleaseUnavailable("invalid private manifest") from exc
    if private.releaseId != bundle.release_id or private.publicManifestSha256 != bundle.public_manifest_sha256:
        raise ReleaseUnavailable("private manifest does not belong to this release")

    ref, base = private.scoreTable, path.parent
    try:
        score_manifest = json.loads((base / ref.manifestFile).read_text(encoding="utf-8"))
        with np.load(base / ref.file) as data:
            arrays = {k: data[k] for k in data.files}
    except (OSError, ValueError) as exc:
        raise ReleaseUnavailable("score table unreadable") from exc
    ids = [str(x) for x in arrays.pop("ids", [])]
    if ids != score_manifest.get("ids") or content_sha256(ids, arrays) != ref.contentSha256:
        raise ReleaseUnavailable("score table content mismatch")
    if score_manifest.get("content_sha256") != ref.contentSha256 or score_manifest.get("version") != ref.version:
        raise ReleaseUnavailable("score table manifest mismatch")
    if ref.version != bundle.scoring_version:
        raise ReleaseUnavailable("scoring version mismatch")
    try:
        table = ScoreTable.from_artifact(arrays, score_manifest)
        rules = RecognitionRules.from_config(private.recognition)
    except (KeyError, ValueError) as exc:
        raise ReleaseUnavailable("invalid score table or recognition rules") from exc
    if rules.version != bundle.recognition_version:
        raise ReleaseUnavailable("recognition version mismatch")
    if not set(table.ids) <= set(catalog.candidate_index):
        raise ReleaseUnavailable("score table has ids outside the candidate list")
    if not set(private.answers) <= set(table.ids):
        raise ReleaseUnavailable("answer categories must be score-supported")
    names = MappingProxyType({c: a.displayNameKo for c, a in private.answers.items()})
    return ReleaseContext(catalog, table, rules, names, frozenset(c for c, a in private.answers.items() if a.daily))


class ArtifactLoader:
    """Per-release cache. Failures are not cached so a fixed artifact becomes usable without a restart."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self._catalogs: dict[str, ReleaseCatalog] = {}
        self._contexts: dict[str, ReleaseContext] = {}
        self._lock = threading.Lock()

    def catalog(self, bundle: ReleaseBundle) -> ReleaseCatalog:
        cached = self._catalogs.get(bundle.release_id)
        if cached is None:
            cached = self._catalogs.setdefault(bundle.release_id, build_catalog(bundle))
        return cached

    def context(self, bundle: ReleaseBundle) -> ReleaseContext:
        cached = self._contexts.get(bundle.release_id)
        if cached is not None:
            return cached
        with self._lock:
            if bundle.release_id not in self._contexts:
                self._contexts[bundle.release_id] = load_context(self.root, bundle, self.catalog(bundle))
            return self._contexts[bundle.release_id]
