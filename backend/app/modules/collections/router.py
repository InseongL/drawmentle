"""Consent and drawing-upload endpoints (docs/api-contract-v1.md §8)."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.sessions.router import current_session
from app.modules.sessions.schemas import SessionContext

from . import service
from .schemas import CompleteIn, CompleteOut, ConsentIn, ConsentOut, UploadIn, UploadOut

router = APIRouter(prefix="/api", tags=["collection"])
Db = Annotated[Session, Depends(get_db)]
Auth = Annotated[SessionContext, Depends(current_session)]


@router.put("/collection-consent", response_model=ConsentOut)
def put_consent(body: ConsentIn, request: Request, db: Db, auth: Auth) -> ConsentOut:
    state = request.app.state
    return service.change_consent(db, state.settings, auth, body, state.clock())


@router.post("/submissions/{submission_id}/drawing-upload", response_model=UploadOut)
def post_drawing_upload(submission_id: uuid.UUID, body: UploadIn, request: Request, db: Db, auth: Auth) -> UploadOut:
    state = request.app.state
    return service.request_upload(db, state.settings, auth, submission_id, body, state.clock())


@router.put("/collection-uploads/{upload_id}", status_code=204, response_class=Response)
async def put_collection_upload(upload_id: uuid.UUID, request: Request, db: Db, auth: Auth) -> Response:
    state = request.app.state
    body = await request.body()
    service.receive_upload(db, state.settings, state.store, auth, upload_id, body, state.clock())
    return Response(status_code=204)


@router.post("/submissions/{submission_id}/drawing-complete", response_model=CompleteOut)
def post_drawing_complete(submission_id: uuid.UUID, body: CompleteIn, request: Request, db: Db,
                          auth: Auth) -> CompleteOut:
    state = request.app.state
    return service.complete_upload(db, state.settings, state.store, auth, submission_id, body, state.clock())
