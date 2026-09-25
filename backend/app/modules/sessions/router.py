"""POST /api/sessions and the `current_session` dependency for other routers."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.db.session import get_db

from . import service
from .schemas import SessionContext, SessionOut

router = APIRouter(prefix="/api", tags=["sessions"])


def _token(request: Request) -> str | None:
    return request.cookies.get(request.app.state.settings.session_cookie_name)


def current_session(request: Request, db: Annotated[Session, Depends(get_db)]) -> SessionContext:
    return service.authenticate(db, _token(request), request.app.state.clock())


@router.post("/sessions", response_model=SessionOut, responses={201: {"model": SessionOut}})
def create_session(request: Request, response: Response, db: Annotated[Session, Depends(get_db)]) -> SessionOut:
    settings = request.app.state.settings
    row, new_token = service.ensure(db, settings, _token(request), request.app.state.clock())
    if new_token:
        response.status_code = 201
        response.set_cookie(settings.session_cookie_name, new_token, max_age=settings.session_ttl_days * 86400,
                            expires=row.expires_at, path="/", httponly=True, secure=settings.cookie_secure,
                            samesite="lax")
    return service.session_view(row)
