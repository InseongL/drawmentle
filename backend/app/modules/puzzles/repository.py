"""Puzzle lookups by service date and ID."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Puzzle


def get(db: Session, puzzle_id: str) -> Puzzle | None:
    return db.get(Puzzle, puzzle_id)


def get_by_date(db: Session, service_date: dt.date) -> Puzzle | None:
    return db.execute(select(Puzzle).where(Puzzle.service_date == service_date)).scalar_one_or_none()


def number(db: Session, service_date: dt.date) -> int:
    """1-based puzzle number: how many puzzles exist up to and including this date."""
    return db.execute(select(func.count()).select_from(Puzzle).where(Puzzle.service_date <= service_date)).scalar_one()
