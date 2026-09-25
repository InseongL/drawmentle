"""Today's puzzle by Korean date, visibility of past puzzles, and the public view."""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.settings import Settings
from app.db.models import Puzzle
from app.modules.releases.service import ReleaseService

from . import repository
from .schemas import CollectionPolicyOut, PuzzleOut


def not_found() -> ApiError:
    return ApiError(404, "PUZZLE_NOT_FOUND", "문제를 찾을 수 없어요.")


def service_date(now: dt.datetime, timezone: str) -> dt.date:
    return now.astimezone(ZoneInfo(timezone)).date()


def is_visible(puzzle: Puzzle, now: dt.datetime) -> bool:
    return puzzle.state != "scheduled" and puzzle.opens_at <= now


def is_closed(puzzle: Puzzle, now: dt.datetime) -> bool:
    return puzzle.state == "closed" or (puzzle.closes_at is not None and puzzle.closes_at <= now)


def today(db: Session, settings: Settings, now: dt.datetime) -> Puzzle:
    puzzle = repository.get_by_date(db, service_date(now, settings.service_timezone))
    if puzzle is None or not is_visible(puzzle, now):
        raise not_found()
    return puzzle


def get_visible(db: Session, puzzle_id: str, now: dt.datetime) -> Puzzle:
    """Future and unknown puzzles are indistinguishable (404)."""
    puzzle = repository.get(db, puzzle_id)
    if puzzle is None or not is_visible(puzzle, now):
        raise not_found()
    return puzzle


def public_view(db: Session, releases: ReleaseService, settings: Settings, puzzle: Puzzle) -> PuzzleOut:
    catalog = releases.catalog(db, puzzle.release_id)
    return PuzzleOut(puzzleId=puzzle.puzzle_id, serviceDate=puzzle.service_date,
                     puzzleNumber=repository.number(db, puzzle.service_date), release=catalog.manifest,
                     collectionPolicy=CollectionPolicyOut(version=settings.collection_policy_version, enabled=False))
