"""Release selection for a puzzle: public manifest for the browser, verified judging context for the server."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.db.models import ReleaseBundle

from . import repository
from .artifact_loader import ArtifactLoader, ReleaseCatalog, ReleaseContext, ReleaseUnavailable, canonical_sha256
from .schemas import PrivateManifest, PublicManifest


def unavailable() -> ApiError:
    return ApiError(503, "RELEASE_UNAVAILABLE", "판정 준비가 끝나지 않았어요. 그림은 그대로 두고 잠시 후 다시 시도해주세요.",
                    retryable=True)


class ReleaseService:
    def __init__(self, loader: ArtifactLoader):
        self.loader = loader

    def _bundle(self, db: Session, release_id: str) -> ReleaseBundle:
        bundle = repository.get_bundle(db, release_id)
        if bundle is None:
            raise unavailable()
        return bundle

    def catalog(self, db: Session, release_id: str) -> ReleaseCatalog:
        try:
            return self.loader.catalog(self._bundle(db, release_id))
        except ReleaseUnavailable as exc:
            raise unavailable() from exc

    def context(self, db: Session, release_id: str) -> ReleaseContext:
        try:
            return self.loader.context(self._bundle(db, release_id))
        except ReleaseUnavailable as exc:
            raise unavailable() from exc


def register(db: Session, root: Path, public: dict, private_key: str, published_at: dt.datetime) -> ReleaseBundle:
    """Insert a release row after checking that its files load. Refuses to change an existing release."""
    manifest = PublicManifest.model_validate(public)
    private_path = Path(root) / private_key
    private_raw = json.loads(private_path.read_text(encoding="utf-8"))
    PrivateManifest.model_validate(private_raw)
    bundle = ReleaseBundle(
        release_id=manifest.releaseId, model_version=manifest.modelVersion,
        preprocessing_version=manifest.preprocessingVersion, catalog_version=manifest.catalogVersion,
        output_calibration_version=manifest.outputCalibrationVersion,
        scoring_version=private_raw["scoreTable"]["version"], recognition_version=private_raw["recognition"]["version"],
        public_manifest=public, public_manifest_sha256=canonical_sha256(public),
        private_manifest_key=private_key, private_manifest_sha256=canonical_sha256(private_raw),
        published_at=published_at)
    existing = repository.get_bundle(db, manifest.releaseId)
    if existing is not None:
        same = (existing.public_manifest_sha256, existing.private_manifest_sha256) == (
            bundle.public_manifest_sha256, bundle.private_manifest_sha256)
        if not same:
            raise ValueError(f"release {manifest.releaseId} already exists with different content")
        return existing
    ArtifactLoader(root).context(bundle)  # full verification before the row becomes visible
    repository.add_bundle(db, bundle)
    return bundle
