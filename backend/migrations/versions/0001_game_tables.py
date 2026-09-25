"""game tables (docs/database-schema-v1.md §2)

Revision ID: 0001
Revises: 
Create Date: 2026-09-25 20:16:58.049330
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('anonymous_sessions',
    sa.Column('session_id', sa.UUID(), nullable=False),
    sa.Column('token_hash', sa.Text(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('consent_revision', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('collection_enabled', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('collection_policy_version', sa.Text(), nullable=True),
    sa.CheckConstraint('NOT collection_enabled OR collection_policy_version IS NOT NULL', name='ck_sessions_policy_when_enabled'),
    sa.CheckConstraint('consent_revision >= 0', name='ck_sessions_consent_revision'),
    sa.PrimaryKeyConstraint('session_id'),
    sa.UniqueConstraint('token_hash')
    )
    op.create_index('ix_anonymous_sessions_expires_at', 'anonymous_sessions', ['expires_at'], unique=False)
    op.create_table('release_bundles',
    sa.Column('release_id', sa.Text(), nullable=False),
    sa.Column('model_version', sa.Text(), nullable=False),
    sa.Column('preprocessing_version', sa.Text(), nullable=False),
    sa.Column('catalog_version', sa.Text(), nullable=False),
    sa.Column('output_calibration_version', sa.Text(), nullable=False),
    sa.Column('scoring_version', sa.Text(), nullable=False),
    sa.Column('recognition_version', sa.Text(), nullable=False),
    sa.Column('public_manifest', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('public_manifest_sha256', sa.Text(), nullable=False),
    sa.Column('private_manifest_key', sa.Text(), nullable=False),
    sa.Column('private_manifest_sha256', sa.Text(), nullable=False),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('release_id')
    )
    op.create_table('puzzles',
    sa.Column('puzzle_id', sa.Text(), nullable=False),
    sa.Column('service_date', sa.Date(), nullable=False),
    sa.Column('release_id', sa.Text(), nullable=False),
    sa.Column('answer_category_id', sa.Text(), nullable=False),
    sa.Column('answer_display_name_ko', sa.Text(), nullable=False),
    sa.Column('opens_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('closes_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('state', sa.Text(), nullable=False),
    sa.CheckConstraint("state IN ('scheduled', 'published', 'closed')", name='ck_puzzles_state'),
    sa.ForeignKeyConstraint(['release_id'], ['release_bundles.release_id'], ),
    sa.PrimaryKeyConstraint('puzzle_id'),
    sa.UniqueConstraint('puzzle_id', 'release_id', name='uq_puzzles_id_release'),
    sa.UniqueConstraint('service_date')
    )
    op.create_table('game_sessions',
    sa.Column('game_session_id', sa.UUID(), nullable=False),
    sa.Column('session_id', sa.UUID(), nullable=False),
    sa.Column('puzzle_id', sa.Text(), nullable=False),
    sa.Column('release_id', sa.Text(), nullable=False),
    sa.Column('state', sa.Text(), server_default=sa.text("'playing'"), nullable=False),
    sa.Column('attempt_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('best_submission_id', sa.UUID(), nullable=True),
    sa.Column('solved_submission_id', sa.UUID(), nullable=True),
    sa.Column('solved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(state = 'playing' AND solved_submission_id IS NULL AND solved_at IS NULL) OR (state = 'solved' AND solved_submission_id IS NOT NULL AND solved_at IS NOT NULL)", name='ck_game_sessions_solved_fields'),
    sa.CheckConstraint("state IN ('playing', 'solved')", name='ck_game_sessions_state'),
    sa.CheckConstraint('attempt_count >= 0', name='ck_game_sessions_attempt_count'),
    sa.ForeignKeyConstraint(['puzzle_id', 'release_id'], ['puzzles.puzzle_id', 'puzzles.release_id'], name='fk_game_sessions_puzzle_release'),
    sa.ForeignKeyConstraint(['session_id'], ['anonymous_sessions.session_id'], ),
    sa.PrimaryKeyConstraint('game_session_id'),
    sa.UniqueConstraint('game_session_id', 'release_id', name='uq_game_sessions_id_release'),
    sa.UniqueConstraint('session_id', 'puzzle_id', name='uq_game_sessions_session_puzzle')
    )
    op.create_table('submissions',
    sa.Column('submission_id', sa.UUID(), nullable=False),
    sa.Column('game_session_id', sa.UUID(), nullable=False),
    sa.Column('release_id', sa.Text(), nullable=False),
    sa.Column('drawing_version', sa.Text(), nullable=False),
    sa.Column('brush_version', sa.Text(), nullable=False),
    sa.Column('drawing_hash', sa.Text(), nullable=False),
    sa.Column('top3', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('top3_sum', sa.Float(precision=53), nullable=False),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('attempt_number', sa.Integer(), nullable=True),
    sa.Column('comparison_score', sa.Float(precision=53), nullable=True),
    sa.Column('display_score', sa.Numeric(), nullable=True),
    sa.Column('display_text', sa.Text(), nullable=True),
    sa.Column('judged_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('collection_policy_version', sa.Text(), nullable=False),
    sa.Column('collection_selection', sa.Text(), nullable=False),
    sa.CheckConstraint("(status = 'deferred' AND reason IS NOT NULL AND attempt_number IS NULL AND comparison_score IS NULL AND display_score IS NULL AND display_text IS NULL) OR (status IN ('recognized', 'solved') AND reason IS NULL AND attempt_number > 0 AND comparison_score IS NOT NULL AND display_score IS NOT NULL AND display_text IS NOT NULL)", name='ck_submissions_status_fields'),
    sa.CheckConstraint("collection_selection IN ('not_selected', 'success_sample', 'failure_sample')", name='ck_submissions_collection_selection'),
    sa.CheckConstraint("drawing_hash ~ '^[0-9a-f]{64}$'", name='ck_submissions_drawing_hash'),
    sa.CheckConstraint("jsonb_typeof(top3) = 'array' AND jsonb_array_length(top3) = 3", name='ck_submissions_top3'),
    sa.CheckConstraint("status IN ('recognized', 'deferred', 'solved')", name='ck_submissions_status'),
    sa.ForeignKeyConstraint(['game_session_id', 'release_id'], ['game_sessions.game_session_id', 'game_sessions.release_id'], name='fk_submissions_game_release'),
    sa.PrimaryKeyConstraint('submission_id'),
    sa.UniqueConstraint('game_session_id', 'attempt_number', name='uq_submissions_attempt'),
    sa.UniqueConstraint('game_session_id', 'drawing_version', 'brush_version', 'drawing_hash', name='uq_submissions_drawing_key'),
    sa.UniqueConstraint('submission_id', 'game_session_id', name='uq_submissions_id_game')
    )
    # Circular references: a game points at its best/solved submission of the same game.
    op.create_foreign_key('fk_game_sessions_best', 'game_sessions', 'submissions',
                          ['best_submission_id', 'game_session_id'], ['submission_id', 'game_session_id'])
    op.create_foreign_key('fk_game_sessions_solved', 'game_sessions', 'submissions',
                          ['solved_submission_id', 'game_session_id'], ['submission_id', 'game_session_id'])
    op.create_index('ix_submissions_attempt_desc', 'submissions', ['game_session_id', sa.literal_column('attempt_number DESC')], unique=False, postgresql_where=sa.text('attempt_number IS NOT NULL'))
    op.create_index('uq_submissions_one_solved', 'submissions', ['game_session_id'], unique=True, postgresql_where=sa.text("status = 'solved'"))
    op.create_table('submission_requests',
    sa.Column('game_session_id', sa.UUID(), nullable=False),
    sa.Column('request_id', sa.UUID(), nullable=False),
    sa.Column('submission_id', sa.UUID(), nullable=False),
    sa.Column('judgement_fingerprint', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("judgement_fingerprint ~ '^[0-9a-f]{64}$'", name='ck_submission_requests_fingerprint'),
    sa.ForeignKeyConstraint(['submission_id', 'game_session_id'], ['submissions.submission_id', 'submissions.game_session_id'], name='fk_submission_requests_submission'),
    sa.PrimaryKeyConstraint('game_session_id', 'request_id')
    )
    op.create_table('submission_score_details',
    sa.Column('submission_id', sa.UUID(), nullable=False),
    sa.Column('details_version', sa.Text(), nullable=False),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.ForeignKeyConstraint(['submission_id'], ['submissions.submission_id'], ),
    sa.PrimaryKeyConstraint('submission_id')
    )


def downgrade() -> None:
    op.drop_table('submission_score_details')
    op.drop_table('submission_requests')
    op.drop_constraint('fk_game_sessions_solved', 'game_sessions', type_='foreignkey')
    op.drop_constraint('fk_game_sessions_best', 'game_sessions', type_='foreignkey')
    op.drop_index('uq_submissions_one_solved', table_name='submissions', postgresql_where=sa.text("status = 'solved'"))
    op.drop_index('ix_submissions_attempt_desc', table_name='submissions', postgresql_where=sa.text('attempt_number IS NOT NULL'))
    op.drop_table('submissions')
    op.drop_table('game_sessions')
    op.drop_table('puzzles')
    op.drop_table('release_bundles')
    op.drop_index('ix_anonymous_sessions_expires_at', table_name='anonymous_sessions')
    op.drop_table('anonymous_sessions')
