"""Submission use cases in one DB transaction each (docs/database-schema-v1.md §4).

Lock order: anonymous session -> game. Repositories never commit; this module commits once per request.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import math
import struct
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable

from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.settings import Settings
from app.db.models import AnonymousSession, GameSession, Puzzle, Submission, SubmissionScoreDetails
from app.modules.judging.judge import DETAILS_VERSION, Judgement, judge, score_details
from app.modules.puzzles import service as puzzles
from app.modules.releases.artifact_loader import ReleaseCatalog
from app.modules.releases.service import ReleaseService
from app.modules.sessions import repository as sessions_repo
from app.modules.sessions.schemas import SessionContext
from app.modules.sessions.service import collection_view

from . import repository
from .schemas import AnswerOut, HistoryItem, ProgressOut, ProgressPage, ResultOut, SubmissionIn, SubmissionOut

FINGERPRINT_VERSION = "judgement-fp-v1"
TOP3_SUM_TOLERANCE = 1e-6  # float input check, not a success threshold
JudgeFn = Callable[..., Judgement]


def invalid_top3() -> ApiError:
    return ApiError(422, "INVALID_TOP3", "인식 결과 형식이 올바르지 않아요.")


def validate_top3(catalog: ReleaseCatalog, req: SubmissionIn) -> list[tuple[str, float]]:
    """Known candidates, distinct, sum <= 1, ordered by p desc then candidate_index asc. Never reorders."""
    top3 = [(item.categoryId, item.p + 0.0) for item in req.top3]  # + 0.0 turns -0.0 into 0.0
    ids = [c for c, _ in top3]
    if len(set(ids)) != 3 or any(c not in catalog.candidate_index for c in ids):
        raise invalid_top3()
    if not all(math.isfinite(p) and 0 <= p <= 1 for _, p in top3) or sum(p for _, p in top3) > 1 + TOP3_SUM_TOLERANCE:
        raise invalid_top3()
    for (c1, p1), (c2, p2) in zip(top3, top3[1:]):
        if p1 < p2 or (p1 == p2 and catalog.candidate_index[c1] > catalog.candidate_index[c2]):
            raise invalid_top3()
    return top3


def judgement_fingerprint(puzzle_id: str, req: SubmissionIn, top3: list[tuple[str, float]]) -> str:
    """Typed, length-prefixed serialisation; p as big-endian binary64. Excludes request ID and consent revision."""
    h = hashlib.sha256()

    def text(value: str) -> None:
        raw = value.encode("utf-8")
        h.update(struct.pack(">I", len(raw)))
        h.update(raw)

    for value in (FINGERPRINT_VERSION, puzzle_id, req.releaseId, req.modelVersion, req.preprocessingVersion,
                  req.catalogVersion, req.outputCalibrationVersion, req.drawingVersion, req.brushVersion,
                  req.drawingHash):
        text(value)
    h.update(struct.pack(">I", len(top3)))
    for category_id, p in top3:
        text(category_id)
        h.update(struct.pack(">d", p))
    return h.hexdigest()


def _answer(puzzle: Puzzle) -> AnswerOut:
    return AnswerOut(categoryId=puzzle.answer_category_id, displayNameKo=puzzle.answer_display_name_ko)


def result_view(sub: Submission, puzzle: Puzzle) -> ResultOut:
    return ResultOut(status=sub.status, reason=sub.reason, attemptNumber=sub.attempt_number,
                     displayScore=None if sub.display_score is None else float(sub.display_score),
                     displayText=sub.display_text, solved=sub.status == "solved",
                     judgedAt=sub.judged_at.astimezone(dt.timezone.utc),
                     answer=_answer(puzzle) if sub.status == "solved" else None)


def progress_view(db: Session, game: GameSession | None, puzzle: Puzzle) -> ProgressOut:
    if game is None:
        return ProgressOut(state="playing", attemptCount=0, bestSubmissionId=None, bestDisplayScore=None,
                           bestDisplayText=None)
    best = repository.get_submission(db, game.best_submission_id) if game.best_submission_id else None
    solved = game.state == "solved"
    return ProgressOut(state=game.state, attemptCount=game.attempt_count,
                       bestSubmissionId=best.submission_id if best else None,
                       bestDisplayScore=float(best.display_score) if best else None,
                       bestDisplayText=best.display_text if best else None,
                       solvedSubmissionId=game.solved_submission_id if solved else None,
                       answer=_answer(puzzle) if solved else None)


def _response(db: Session, request_id: uuid.UUID, sub: Submission, game: GameSession, puzzle: Puzzle,
              session: AnonymousSession | SessionContext, reuse: str) -> SubmissionOut:
    # result is the stored outcome; progress and collection are read now (not cached from the first response).
    return SubmissionOut(requestSubmissionId=request_id, submissionId=sub.submission_id, puzzleId=puzzle.puzzle_id,
                         releaseId=puzzle.release_id, reuse=reuse, result=result_view(sub, puzzle),
                         progress=progress_view(db, game, puzzle),
                         collection=collection_view(session.consent_revision))


@dataclass(frozen=True)
class Outcome:
    http_status: int
    body: SubmissionOut


def submit(db: Session, releases: ReleaseService, settings: Settings, auth: SessionContext, puzzle_id: str,
           req: SubmissionIn, now: dt.datetime, judge_fn: JudgeFn = judge) -> Outcome:
    # 1. Input checks and artifact preparation, before taking any lock.
    puzzle = puzzles.get_visible(db, puzzle_id, now)
    catalog = releases.catalog(db, puzzle.release_id)
    top3 = validate_top3(catalog, req)
    fingerprint = judgement_fingerprint(puzzle.puzzle_id, req, top3)
    try:
        context, context_error = releases.context(db, puzzle.release_id), None
    except ApiError as exc:  # only fatal if a new judgement is needed
        context, context_error = None, exc

    # 2-3. Lock session, then create/lock the game.
    session = sessions_repo.lock(db, auth.session_id)
    if session is None or session.expires_at <= now:
        raise ApiError(401, "SESSION_EXPIRED", "세션이 만료됐어요. 페이지를 새로고침해주세요.")
    game = repository.lock_or_create_game(db, session.session_id, puzzle)
    if game.release_id != puzzle.release_id:
        raise ApiError(409, "VERSION_MISMATCH", "문제 정보가 바뀌었어요. 새로고침해주세요.")

    # 4. Known request ID: same body -> stored result, different body -> conflict. No game-over checks.
    known = repository.get_request(db, game.game_session_id, req.submissionId)
    if known is not None:
        if known.judgement_fingerprint != fingerprint:
            raise ApiError(409, "IDEMPOTENCY_CONFLICT", "같은 제출 ID로 다른 내용을 보냈어요.")
        sub = repository.get_submission(db, known.submission_id)
        body = _response(db, req.submissionId, sub, game, puzzle, session, "request_retry")
        db.commit()
        return Outcome(200, body)

    # 5. New request ID: versions must match the puzzle's release; same drawing reuses the stored result.
    if req.releaseId != puzzle.release_id or not catalog.versions_match(
            req.modelVersion, req.preprocessingVersion, req.catalogVersion, req.outputCalibrationVersion,
            req.drawingVersion, req.brushVersion):
        raise ApiError(409, "VERSION_MISMATCH", "모델 버전이 문제와 달라요. 그림은 그대로 두고 새로고침해주세요.")
    duplicate = repository.get_by_drawing_key(db, game.game_session_id, req.drawingVersion, req.brushVersion,
                                              req.drawingHash)
    if duplicate is not None:
        repository.add_request(db, game.game_session_id, req.submissionId, duplicate.submission_id, fingerprint)
        body = _response(db, req.submissionId, duplicate, game, puzzle, session, "drawing_duplicate")
        db.commit()
        return Outcome(200, body)

    # 6. New drawing: game must still be open.
    if game.state == "solved":
        raise ApiError(409, "GAME_ALREADY_SOLVED", "이미 정답을 맞힌 문제예요.")
    if puzzles.is_closed(puzzle, now):
        raise ApiError(410, "PUZZLE_CLOSED", "이 문제는 더 이상 제출할 수 없어요.")
    if context is None:
        raise context_error
    judgement = judge_fn(context.table, context.rules, puzzle.answer_category_id, top3)

    # 7-8. Store result, details and request mapping; update the game in the same transaction.
    sub = Submission(
        submission_id=uuid.uuid4(), game_session_id=game.game_session_id, release_id=puzzle.release_id,
        drawing_version=req.drawingVersion, brush_version=req.brushVersion, drawing_hash=req.drawingHash,
        top3=[{"categoryId": c, "p": p} for c, p in top3], top3_sum=sum(p for _, p in top3),
        status=judgement.status, reason=judgement.reason,
        attempt_number=game.attempt_count + 1 if judgement.counted else None,
        comparison_score=judgement.mix.mixed if judgement.mix else None,
        display_score=Decimal(judgement.mix.display_text) if judgement.mix else None,
        display_text=judgement.mix.display_text if judgement.mix else None,
        judged_at=now, collection_policy_version=settings.collection_policy_version,
        collection_selection="not_selected")
    details = SubmissionScoreDetails(
        submission_id=sub.submission_id, details_version=DETAILS_VERSION,
        details=score_details(judgement, context.rules, context.table, puzzle.answer_category_id, top3))
    repository.add_submission(db, sub, details)
    repository.add_request(db, game.game_session_id, req.submissionId, sub.submission_id, fingerprint)
    if judgement.counted:
        game.attempt_count = sub.attempt_number
        best = repository.get_submission(db, game.best_submission_id) if game.best_submission_id else None
        if best is None or sub.comparison_score >= best.comparison_score:  # ties -> latest attempt
            game.best_submission_id = sub.submission_id
    if judgement.status == "solved":
        game.state, game.solved_submission_id, game.solved_at = "solved", sub.submission_id, now
    db.flush()
    body = _response(db, req.submissionId, sub, game, puzzle, session, "new")
    db.commit()
    return Outcome(201, body)


def by_request(db: Session, auth: SessionContext, puzzle_id: str, request_id: uuid.UUID,
               now: dt.datetime) -> SubmissionOut:
    """Recover a committed result after a lost response. 404 may mean 'still processing': retry the same ID."""
    puzzle = puzzles.get_visible(db, puzzle_id, now)
    game = repository.get_game(db, auth.session_id, puzzle.puzzle_id)
    known = repository.get_request(db, game.game_session_id, request_id) if game else None
    if known is None:
        raise ApiError(404, "SUBMISSION_NOT_FOUND", "제출 결과를 찾을 수 없어요.", retryable=True)
    sub = repository.get_submission(db, known.submission_id)
    return _response(db, request_id, sub, game, puzzle, auth, "request_retry")


def progress_page(db: Session, auth: SessionContext, puzzle_id: str, limit: int, before: int | None,
                  now: dt.datetime) -> ProgressPage:
    puzzle = puzzles.get_visible(db, puzzle_id, now)
    game = repository.get_game(db, auth.session_id, puzzle.puzzle_id)
    rows = repository.list_attempts(db, game.game_session_id, before, limit + 1) if game else []
    more, rows = len(rows) > limit, rows[:limit]
    return ProgressPage(puzzleId=puzzle.puzzle_id, progress=progress_view(db, game, puzzle),
                        items=[HistoryItem(submissionId=r.submission_id, result=result_view(r, puzzle)) for r in rows],
                        nextBeforeAttemptNumber=rows[-1].attempt_number if more else None)
