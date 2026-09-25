"""GET /api/puzzles/today and /api/puzzles/{puzzleId}."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.db.session import get_db

from . import service
from .schemas import PuzzleOut

router = APIRouter(prefix="/api/puzzles", tags=["puzzles"])


@router.get("/today", response_model=PuzzleOut)
def get_today(request: Request, db: Annotated[Session, Depends(get_db)]) -> PuzzleOut:
    state = request.app.state
    puzzle = service.today(db, state.settings, state.clock())
    return service.public_view(db, state.releases, state.settings, puzzle)


@router.get("/{puzzle_id}", response_model=PuzzleOut)
def get_puzzle(puzzle_id: str, request: Request, db: Annotated[Session, Depends(get_db)]) -> PuzzleOut:
    state = request.app.state
    puzzle = service.get_visible(db, puzzle_id, state.clock())
    return service.public_view(db, state.releases, state.settings, puzzle)
