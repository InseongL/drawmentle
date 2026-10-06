"""Server settings read from environment variables (no secrets are committed)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from app.core.collection_config import CollectionConfig

REPO_ROOT = Path(__file__).resolve().parents[3]
DEV_DATABASE_URL = "postgresql+psycopg://drawmentle:drawmentle-dev@127.0.0.1:5433/drawmentle"
COLLECTION_CONFIG = REPO_ROOT / "config/collection/collection.json"


def _bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_env: str = "development"
    database_url: str = DEV_DATABASE_URL
    session_cookie_name: str = "dm_session"
    session_ttl_days: int = 30
    cookie_secure: bool = False
    allowed_origins: tuple[str, ...] = ("http://127.0.0.1:5173", "http://localhost:5173")
    artifact_root: Path = REPO_ROOT
    service_timezone: str = "Asia/Seoul"
    collection: CollectionConfig = field(default_factory=lambda: CollectionConfig.load(COLLECTION_CONFIG))

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def collection_policy_version(self) -> str:
        return self.collection.selection_policy

    @classmethod
    def from_env(cls) -> "Settings":
        app_env = os.environ.get("APP_ENV", "development")
        origins = os.environ.get("ALLOWED_ORIGINS")
        settings = cls(
            app_env=app_env,
            database_url=os.environ.get("DATABASE_URL", DEV_DATABASE_URL),
            session_cookie_name=os.environ.get("SESSION_COOKIE_NAME", "dm_session"),
            session_ttl_days=int(os.environ.get("SESSION_TTL_DAYS", "30")),
            cookie_secure=_bool("COOKIE_SECURE", app_env == "production"),
            allowed_origins=tuple(o.strip() for o in origins.split(",") if o.strip()) if origins
            else cls.allowed_origins,
            artifact_root=Path(os.environ.get("ARTIFACT_ROOT", str(REPO_ROOT))),
            collection=CollectionConfig.load(Path(os.environ.get("COLLECTION_CONFIG", str(COLLECTION_CONFIG)))),
        )
        if settings.is_production and (settings.database_url == DEV_DATABASE_URL or not settings.cookie_secure):
            raise RuntimeError("production requires DATABASE_URL and secure cookies")
        return settings
