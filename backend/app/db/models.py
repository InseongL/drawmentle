"""Game tables (docs/database-schema-v1.md §2). Collection/review tables are added with those features."""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import (BigInteger, Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, ForeignKeyConstraint,
                        Index, Integer, Numeric, Text, UniqueConstraint, func, text)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

HASH_CHECK = "~ '^[0-9a-f]{64}$'"


class Base(DeclarativeBase):
    pass


class ReleaseBundle(Base):
    """Immutable release. Only rows that passed the release checks are inserted."""
    __tablename__ = "release_bundles"
    release_id: Mapped[str] = mapped_column(Text, primary_key=True)
    model_version: Mapped[str] = mapped_column(Text)
    preprocessing_version: Mapped[str] = mapped_column(Text)
    catalog_version: Mapped[str] = mapped_column(Text)
    output_calibration_version: Mapped[str] = mapped_column(Text)
    scoring_version: Mapped[str] = mapped_column(Text)
    recognition_version: Mapped[str] = mapped_column(Text)
    public_manifest: Mapped[dict] = mapped_column(JSONB)
    public_manifest_sha256: Mapped[str] = mapped_column(Text)
    private_manifest_key: Mapped[str] = mapped_column(Text)
    private_manifest_sha256: Mapped[str] = mapped_column(Text)
    published_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))


class Puzzle(Base):
    __tablename__ = "puzzles"
    __table_args__ = (
        UniqueConstraint("puzzle_id", "release_id", name="uq_puzzles_id_release"),
        CheckConstraint("state IN ('scheduled', 'published', 'closed')", name="ck_puzzles_state"),
    )
    puzzle_id: Mapped[str] = mapped_column(Text, primary_key=True)
    service_date: Mapped[dt.date] = mapped_column(Date, unique=True)
    release_id: Mapped[str] = mapped_column(Text, ForeignKey("release_bundles.release_id"))
    answer_category_id: Mapped[str] = mapped_column(Text)
    answer_display_name_ko: Mapped[str] = mapped_column(Text)
    opens_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    closes_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(Text)


class AnonymousSession(Base):
    __tablename__ = "anonymous_sessions"
    __table_args__ = (
        CheckConstraint("consent_revision >= 0", name="ck_sessions_consent_revision"),
        CheckConstraint("NOT collection_enabled OR collection_policy_version IS NOT NULL",
                        name="ck_sessions_policy_when_enabled"),
        Index("ix_anonymous_sessions_expires_at", "expires_at"),
    )
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    token_hash: Mapped[str] = mapped_column(Text, unique=True)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    consent_revision: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    collection_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    collection_policy_version: Mapped[str | None] = mapped_column(Text)


class GameSession(Base):
    __tablename__ = "game_sessions"
    __table_args__ = (
        ForeignKeyConstraint(["puzzle_id", "release_id"], ["puzzles.puzzle_id", "puzzles.release_id"],
                             name="fk_game_sessions_puzzle_release"),
        # Best/solved must reference a submission of this same game. Created after `submissions` (circular FK).
        ForeignKeyConstraint(["best_submission_id", "game_session_id"],
                             ["submissions.submission_id", "submissions.game_session_id"],
                             name="fk_game_sessions_best", use_alter=True),
        ForeignKeyConstraint(["solved_submission_id", "game_session_id"],
                             ["submissions.submission_id", "submissions.game_session_id"],
                             name="fk_game_sessions_solved", use_alter=True),
        UniqueConstraint("session_id", "puzzle_id", name="uq_game_sessions_session_puzzle"),
        UniqueConstraint("game_session_id", "release_id", name="uq_game_sessions_id_release"),
        CheckConstraint("state IN ('playing', 'solved')", name="ck_game_sessions_state"),
        CheckConstraint("attempt_count >= 0", name="ck_game_sessions_attempt_count"),
        CheckConstraint("(state = 'playing' AND solved_submission_id IS NULL AND solved_at IS NULL) OR "
                        "(state = 'solved' AND solved_submission_id IS NOT NULL AND solved_at IS NOT NULL)",
                        name="ck_game_sessions_solved_fields"),
    )
    game_session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("anonymous_sessions.session_id"))
    puzzle_id: Mapped[str] = mapped_column(Text)
    release_id: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(Text, server_default=text("'playing'"))
    attempt_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    best_submission_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    solved_submission_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    solved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Submission(Base):
    """One judged drawing. Immutable after insert."""
    __tablename__ = "submissions"
    __table_args__ = (
        ForeignKeyConstraint(["game_session_id", "release_id"],
                             ["game_sessions.game_session_id", "game_sessions.release_id"],
                             name="fk_submissions_game_release"),
        UniqueConstraint("game_session_id", "drawing_version", "brush_version", "drawing_hash",
                         name="uq_submissions_drawing_key"),
        UniqueConstraint("game_session_id", "attempt_number", name="uq_submissions_attempt"),
        UniqueConstraint("submission_id", "game_session_id", name="uq_submissions_id_game"),
        CheckConstraint(f"drawing_hash {HASH_CHECK}", name="ck_submissions_drawing_hash"),
        CheckConstraint("jsonb_typeof(top3) = 'array' AND jsonb_array_length(top3) = 3", name="ck_submissions_top3"),
        CheckConstraint("status IN ('recognized', 'deferred', 'solved')", name="ck_submissions_status"),
        CheckConstraint("collection_selection IN ('not_selected', 'success_sample', 'failure_sample')",
                        name="ck_submissions_collection_selection"),
        CheckConstraint(
            "(status = 'deferred' AND reason IS NOT NULL AND attempt_number IS NULL AND comparison_score IS NULL "
            "AND display_score IS NULL AND display_text IS NULL) OR "
            "(status IN ('recognized', 'solved') AND reason IS NULL AND attempt_number > 0 "
            "AND comparison_score IS NOT NULL AND display_score IS NOT NULL AND display_text IS NOT NULL)",
            name="ck_submissions_status_fields"),
        Index("uq_submissions_one_solved", "game_session_id", unique=True,
              postgresql_where=text("status = 'solved'")),
        Index("ix_submissions_attempt_desc", "game_session_id", text("attempt_number DESC"),
              postgresql_where=text("attempt_number IS NOT NULL")),
    )
    submission_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    game_session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    release_id: Mapped[str] = mapped_column(Text)
    drawing_version: Mapped[str] = mapped_column(Text)
    brush_version: Mapped[str] = mapped_column(Text)
    drawing_hash: Mapped[str] = mapped_column(Text)
    top3: Mapped[list] = mapped_column(JSONB)
    top3_sum: Mapped[float] = mapped_column(Float(precision=53))
    status: Mapped[str] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    attempt_number: Mapped[int | None] = mapped_column(Integer)
    comparison_score: Mapped[float | None] = mapped_column(Float(precision=53))
    display_score: Mapped[Decimal | None] = mapped_column(Numeric)
    display_text: Mapped[str | None] = mapped_column(Text)
    judged_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    collection_policy_version: Mapped[str] = mapped_column(Text)
    collection_selection: Mapped[str] = mapped_column(Text)


class SubmissionRequest(Base):
    """Client request ID -> canonical result, including alias IDs for the same drawing."""
    __tablename__ = "submission_requests"
    __table_args__ = (
        ForeignKeyConstraint(["submission_id", "game_session_id"],
                             ["submissions.submission_id", "submissions.game_session_id"],
                             name="fk_submission_requests_submission"),
        CheckConstraint(f"judgement_fingerprint {HASH_CHECK}", name="ck_submission_requests_fingerprint"),
    )
    game_session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    submission_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    judgement_fingerprint: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SubmissionScoreDetails(Base):
    """Private calculation record (q, per-axis scores, ranks, rules). Never serialised to public responses."""
    __tablename__ = "submission_score_details"
    submission_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("submissions.submission_id"),
                                                     primary_key=True)
    details_version: Mapped[str] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSONB)
