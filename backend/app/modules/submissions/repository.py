"""Game/submission queries and row locks. Never commits; the submissions service owns the transaction."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import GameSession, Puzzle, Submission, SubmissionRequest, SubmissionScoreDetails


def lock_or_create_game(db: Session, session_id: uuid.UUID, puzzle: Puzzle) -> GameSession:
    """Caller must already hold the anonymous-session lock (lock order: session -> game)."""
    db.execute(insert(GameSession)
               .values(game_session_id=uuid.uuid4(), session_id=session_id, puzzle_id=puzzle.puzzle_id,
                       release_id=puzzle.release_id)
               .on_conflict_do_nothing(constraint="uq_game_sessions_session_puzzle"))
    stmt = (select(GameSession).where(GameSession.session_id == session_id, GameSession.puzzle_id == puzzle.puzzle_id)
            .with_for_update().execution_options(populate_existing=True))
    return db.execute(stmt).scalar_one()


def get_game(db: Session, session_id: uuid.UUID, puzzle_id: str) -> GameSession | None:
    stmt = select(GameSession).where(GameSession.session_id == session_id, GameSession.puzzle_id == puzzle_id)
    return db.execute(stmt).scalar_one_or_none()


def get_request(db: Session, game_session_id: uuid.UUID, request_id: uuid.UUID) -> SubmissionRequest | None:
    return db.get(SubmissionRequest, (game_session_id, request_id))


def get_submission(db: Session, submission_id: uuid.UUID) -> Submission | None:
    return db.get(Submission, submission_id)


def get_by_drawing_key(db: Session, game_session_id: uuid.UUID, drawing_version: str, brush_version: str,
                       drawing_hash: str) -> Submission | None:
    stmt = select(Submission).where(Submission.game_session_id == game_session_id,
                                    Submission.drawing_version == drawing_version,
                                    Submission.brush_version == brush_version,
                                    Submission.drawing_hash == drawing_hash)
    return db.execute(stmt).scalar_one_or_none()


def add_submission(db: Session, submission: Submission, details: SubmissionScoreDetails) -> None:
    db.add(submission)
    db.flush()  # the game row's best/solved FKs point at this row
    db.add(details)


def add_request(db: Session, game_session_id: uuid.UUID, request_id: uuid.UUID, submission_id: uuid.UUID,
                fingerprint: str) -> None:
    db.add(SubmissionRequest(game_session_id=game_session_id, request_id=request_id, submission_id=submission_id,
                             judgement_fingerprint=fingerprint))


def list_attempts(db: Session, game_session_id: uuid.UUID, before: int | None, limit: int) -> list[Submission]:
    """Counted attempts, newest first. `before` is an exclusive attempt-number cursor."""
    stmt = select(Submission).where(Submission.game_session_id == game_session_id,
                                    Submission.attempt_number.is_not(None))
    if before is not None:
        stmt = stmt.where(Submission.attempt_number < before)
    return list(db.execute(stmt.order_by(Submission.attempt_number.desc()).limit(limit)).scalars())
