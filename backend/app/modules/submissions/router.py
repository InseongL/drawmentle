"""Submission, request-ID recovery and progress endpoints under /api/puzzles/{puzzleId}."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.sessions.router import current_session
from app.modules.sessions.schemas import SessionContext

from . import service
from .schemas import ProgressPage, SubmissionIn, SubmissionOut

router = APIRouter(prefix="/api/puzzles/{puzzle_id}", tags=["submissions"])
Db = Annotated[Session, Depends(get_db)]
Auth = Annotated[SessionContext, Depends(current_session)]


@router.post("/submissions", response_model=SubmissionOut, responses={201: {"model": SubmissionOut}})
def create_submission(puzzle_id: str, body: SubmissionIn, request: Request, response: Response, db: Db,
                      auth: Auth) -> SubmissionOut:
    state = request.app.state
    outcome = service.submit(db, state.releases, state.settings, auth, puzzle_id, body, state.clock(), state.judge)
    response.status_code = outcome.http_status
    return outcome.body


@router.get("/submissions/by-request/{submission_id}", response_model=SubmissionOut)
def get_by_request(puzzle_id: str, submission_id: uuid.UUID, request: Request, db: Db, auth: Auth) -> SubmissionOut:
    return service.by_request(db, auth, puzzle_id, submission_id, request.app.state.clock())


@router.get("/progress", response_model=ProgressPage)
def get_progress(puzzle_id: str, request: Request, db: Db, auth: Auth,
                 limit: Annotated[int, Query(ge=1, le=50)] = 10,
                 beforeAttemptNumber: Annotated[int | None, Query(ge=1)] = None) -> ProgressPage:
    return service.progress_page(db, auth, puzzle_id, limit, beforeAttemptNumber, request.app.state.clock())
