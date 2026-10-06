"""Game tables (docs/database-schema-v1.md §2) and collection/review tables (§3, docs/mlops-v1.md)."""
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


# Collection and review (docs/database-schema-v1.md §3). Drawings themselves live in the object store, never in rows.
SAMPLE_STATES = "('pending_upload', 'uploaded', 'verified', 'upload_failed', 'delete_pending', 'deleted')"
UPLOAD_STATES = "('issued', 'received', 'verified', 'rejected', 'expired')"


class CollectionConsent(Base):
    """Append-only consent history. The session row caches the latest revision."""
    __tablename__ = "collection_consents"
    __table_args__ = (
        CheckConstraint("revision >= 0", name="ck_collection_consents_revision"),
        CheckConstraint("NOT enabled OR policy_version IS NOT NULL", name="ck_collection_consents_policy"),
    )
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("anonymous_sessions.session_id"),
                                                  primary_key=True)
    revision: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean)
    policy_version: Mapped[str | None] = mapped_column(Text)
    changed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))


class DrawingSample(Base):
    """One consented, selected submission's drawing. `verified` means the file was checked, not label-reviewed."""
    __tablename__ = "drawing_samples"
    __table_args__ = (
        ForeignKeyConstraint(["session_id", "consent_revision"],
                             ["collection_consents.session_id", "collection_consents.revision"],
                             name="fk_drawing_samples_consent"),
        ForeignKeyConstraint(["active_upload_id", "sample_id"],
                             ["drawing_uploads.upload_id", "drawing_uploads.sample_id"],
                             name="fk_drawing_samples_active_upload", use_alter=True),
        CheckConstraint(f"state IN {SAMPLE_STATES}", name="ck_drawing_samples_state"),
        CheckConstraint("selection IN ('success_sample', 'failure_sample')", name="ck_drawing_samples_selection"),
        CheckConstraint("state <> 'verified' OR (verified_at IS NOT NULL AND verified_object_key IS NOT NULL "
                        "AND file_sha256 IS NOT NULL AND byte_size IS NOT NULL)", name="ck_drawing_samples_verified"),
        CheckConstraint("state <> 'deleted' OR deleted_at IS NOT NULL", name="ck_drawing_samples_deleted"),
        Index("ix_drawing_samples_session_state", "session_id", "state"),
        Index("ix_drawing_samples_state_updated", "state", "updated_at"),
    )
    sample_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    submission_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("submissions.submission_id"),
                                                     unique=True)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    consent_revision: Mapped[int] = mapped_column(BigInteger)
    selection: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(Text)
    active_upload_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    verified_object_key: Mapped[str | None] = mapped_column(Text)
    verified_object_version: Mapped[str | None] = mapped_column(Text)
    file_sha256: Mapped[str | None] = mapped_column(Text)
    byte_size: Mapped[int | None] = mapped_column(BigInteger)
    stroke_count: Mapped[int | None] = mapped_column(Integer)
    point_count: Mapped[int | None] = mapped_column(Integer)
    verified_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    deletion_requested_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))


class DrawingUpload(Base):
    """One upload grant. A new grant gets a new ID and temporary key; late files to old keys are never verified."""
    __tablename__ = "drawing_uploads"
    __table_args__ = (
        UniqueConstraint("upload_id", "sample_id", name="uq_drawing_uploads_id_sample"),
        CheckConstraint(f"state IN {UPLOAD_STATES}", name="ck_drawing_uploads_state"),
        Index("ix_drawing_uploads_state_expires", "state", "expires_at"),
    )
    upload_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    sample_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("drawing_samples.sample_id"))
    object_key: Mapped[str] = mapped_column(Text, unique=True)
    consent_revision: Mapped[int] = mapped_column(BigInteger)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(Text)
    last_error_code: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))


class LabelReview(Base):
    """Append-only human label decisions. No row means unreviewed; nothing is filled from the model or the answer."""
    __tablename__ = "label_reviews"
    __table_args__ = (
        UniqueConstraint("sample_id", "revision", name="uq_label_reviews_sample_revision"),
        CheckConstraint("decision IN ('accepted', 'rejected', 'uncertain')", name="ck_label_reviews_decision"),
        CheckConstraint("decision <> 'accepted' OR reviewed_category_id IS NOT NULL", name="ck_label_reviews_label"),
        CheckConstraint("revision > 0", name="ck_label_reviews_revision"),
    )
    review_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    sample_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("drawing_samples.sample_id"))
    revision: Mapped[int] = mapped_column(Integer)
    decision: Mapped[str] = mapped_column(Text)
    reviewed_category_id: Mapped[str | None] = mapped_column(Text)
    catalog_version: Mapped[str] = mapped_column(Text)
    reviewer_ref: Mapped[str] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
