"""FastAPI app factory. Run from backend/:  python -m uvicorn app.main:create_app --factory --port 8000"""
from __future__ import annotations

import datetime as dt

from fastapi import FastAPI, Request
from sqlalchemy.engine import Engine

from app.core.errors import error_response, install_error_handlers
from app.core.settings import Settings
from app.db.session import make_engine, make_session_factory
from app.modules.judging.judge import judge
from app.modules.puzzles.router import router as puzzles_router
from app.modules.releases.artifact_loader import ArtifactLoader
from app.modules.releases.service import ReleaseService
from app.modules.sessions.router import router as sessions_router
from app.modules.submissions.router import router as submissions_router

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def install_origin_check(app: FastAPI, settings: Settings) -> None:
    """Cookie-authenticated changes must come from an allowed Origin. Non-browser clients omit it (dev only)."""
    @app.middleware("http")
    async def check_origin(request: Request, call_next):
        if request.method in MUTATING and request.url.path.startswith("/api/"):
            origin = request.headers.get("origin")
            if (origin is None and settings.is_production) or (origin is not None
                                                                 and origin not in settings.allowed_origins):
                return error_response(request, 403, "ORIGIN_NOT_ALLOWED", "허용되지 않은 요청이에요.", False)
        return await call_next(request)


def create_app(settings: Settings | None = None, *, engine: Engine | None = None, judge_fn=judge,
               clock=utc_now) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(title="Drawmentle API", version="0.1.0",
                  docs_url=None if settings.is_production else "/api/docs", openapi_url="/api/openapi.json")
    app.state.settings = settings
    app.state.session_factory = make_session_factory(engine or make_engine(settings.database_url))
    app.state.releases = ReleaseService(ArtifactLoader(settings.artifact_root))
    app.state.judge = judge_fn
    app.state.clock = clock
    install_origin_check(app, settings)
    install_error_handlers(app)
    for router in (sessions_router, puzzles_router, submissions_router):
        app.include_router(router)

    @app.get("/api/health", tags=["health"])
    def health() -> dict:
        return {"status": "ok"}

    return app
