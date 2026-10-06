"""collection and review tables (docs/database-schema-v1.md §3, docs/mlops-v1.md)

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-06
"""
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None

SAMPLE_STATES = "('pending_upload', 'uploaded', 'verified', 'upload_failed', 'delete_pending', 'deleted')"
UPLOAD_STATES = "('issued', 'received', 'verified', 'rejected', 'expired')"


def upgrade() -> None:
    op.create_table('collection_consents',
    sa.Column('session_id', sa.UUID(), nullable=False),
    sa.Column('revision', sa.BigInteger(), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('policy_version', sa.Text(), nullable=True),
    sa.Column('changed_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('revision >= 0', name='ck_collection_consents_revision'),
    sa.CheckConstraint('NOT enabled OR policy_version IS NOT NULL', name='ck_collection_consents_policy'),
    sa.ForeignKeyConstraint(['session_id'], ['anonymous_sessions.session_id'], ),
    sa.PrimaryKeyConstraint('session_id', 'revision')
    )
    # Existing sessions get their current revision as the first history row (all are revision 0, not consented).
    op.execute("INSERT INTO collection_consents (session_id, revision, enabled, policy_version, changed_at) "
               "SELECT session_id, consent_revision, collection_enabled, collection_policy_version, created_at "
               "FROM anonymous_sessions")
    op.create_table('drawing_samples',
    sa.Column('sample_id', sa.UUID(), nullable=False),
    sa.Column('submission_id', sa.UUID(), nullable=False),
    sa.Column('session_id', sa.UUID(), nullable=False),
    sa.Column('consent_revision', sa.BigInteger(), nullable=False),
    sa.Column('selection', sa.Text(), nullable=False),
    sa.Column('state', sa.Text(), nullable=False),
    sa.Column('active_upload_id', sa.UUID(), nullable=True),
    sa.Column('verified_object_key', sa.Text(), nullable=True),
    sa.Column('verified_object_version', sa.Text(), nullable=True),
    sa.Column('file_sha256', sa.Text(), nullable=True),
    sa.Column('byte_size', sa.BigInteger(), nullable=True),
    sa.Column('stroke_count', sa.Integer(), nullable=True),
    sa.Column('point_count', sa.Integer(), nullable=True),
    sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deletion_requested_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error_code', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint(f'state IN {SAMPLE_STATES}', name='ck_drawing_samples_state'),
    sa.CheckConstraint("selection IN ('success_sample', 'failure_sample')", name='ck_drawing_samples_selection'),
    sa.CheckConstraint("state <> 'verified' OR (verified_at IS NOT NULL AND verified_object_key IS NOT NULL "
                       "AND file_sha256 IS NOT NULL AND byte_size IS NOT NULL)", name='ck_drawing_samples_verified'),
    sa.CheckConstraint("state <> 'deleted' OR deleted_at IS NOT NULL", name='ck_drawing_samples_deleted'),
    sa.ForeignKeyConstraint(['session_id', 'consent_revision'],
                            ['collection_consents.session_id', 'collection_consents.revision'],
                            name='fk_drawing_samples_consent'),
    sa.ForeignKeyConstraint(['submission_id'], ['submissions.submission_id'], ),
    sa.PrimaryKeyConstraint('sample_id'),
    sa.UniqueConstraint('submission_id')
    )
    op.create_index('ix_drawing_samples_session_state', 'drawing_samples', ['session_id', 'state'], unique=False)
    op.create_index('ix_drawing_samples_state_updated', 'drawing_samples', ['state', 'updated_at'], unique=False)
    op.create_table('drawing_uploads',
    sa.Column('upload_id', sa.UUID(), nullable=False),
    sa.Column('sample_id', sa.UUID(), nullable=False),
    sa.Column('object_key', sa.Text(), nullable=False),
    sa.Column('consent_revision', sa.BigInteger(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('state', sa.Text(), nullable=False),
    sa.Column('last_error_code', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint(f'state IN {UPLOAD_STATES}', name='ck_drawing_uploads_state'),
    sa.ForeignKeyConstraint(['sample_id'], ['drawing_samples.sample_id'], ),
    sa.PrimaryKeyConstraint('upload_id'),
    sa.UniqueConstraint('object_key'),
    sa.UniqueConstraint('upload_id', 'sample_id', name='uq_drawing_uploads_id_sample')
    )
    op.create_index('ix_drawing_uploads_state_expires', 'drawing_uploads', ['state', 'expires_at'], unique=False)
    # Circular reference: a sample's active upload must be one of its own uploads.
    op.create_foreign_key('fk_drawing_samples_active_upload', 'drawing_samples', 'drawing_uploads',
                          ['active_upload_id', 'sample_id'], ['upload_id', 'sample_id'])
    op.create_table('label_reviews',
    sa.Column('review_id', sa.UUID(), nullable=False),
    sa.Column('sample_id', sa.UUID(), nullable=False),
    sa.Column('revision', sa.Integer(), nullable=False),
    sa.Column('decision', sa.Text(), nullable=False),
    sa.Column('reviewed_category_id', sa.Text(), nullable=True),
    sa.Column('catalog_version', sa.Text(), nullable=False),
    sa.Column('reviewer_ref', sa.Text(), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("decision IN ('accepted', 'rejected', 'uncertain')", name='ck_label_reviews_decision'),
    sa.CheckConstraint("decision <> 'accepted' OR reviewed_category_id IS NOT NULL", name='ck_label_reviews_label'),
    sa.CheckConstraint('revision > 0', name='ck_label_reviews_revision'),
    sa.ForeignKeyConstraint(['sample_id'], ['drawing_samples.sample_id'], ),
    sa.PrimaryKeyConstraint('review_id'),
    sa.UniqueConstraint('sample_id', 'revision', name='uq_label_reviews_sample_revision')
    )


def downgrade() -> None:
    op.drop_table('label_reviews')
    op.drop_constraint('fk_drawing_samples_active_upload', 'drawing_samples', type_='foreignkey')
    op.drop_index('ix_drawing_uploads_state_expires', table_name='drawing_uploads')
    op.drop_table('drawing_uploads')
    op.drop_index('ix_drawing_samples_state_updated', table_name='drawing_samples')
    op.drop_index('ix_drawing_samples_session_state', table_name='drawing_samples')
    op.drop_table('drawing_samples')
    op.drop_table('collection_consents')
