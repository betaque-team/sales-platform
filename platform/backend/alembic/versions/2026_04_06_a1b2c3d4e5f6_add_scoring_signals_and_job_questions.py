"""Add scoring_signals and job_questions tables.

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2026-04-06

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSON


revision = "a1b2c3d4e5f6"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scoring_signals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("signal_type", sa.String(50), nullable=False),
        sa.Column("signal_key", sa.String(255), nullable=False, unique=True),
        sa.Column("weight", sa.Float, server_default="0.0"),
        sa.Column("decay_factor", sa.Float, server_default="0.95"),
        sa.Column("source_count", sa.Integer, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_scoring_signals_signal_key", "scoring_signals", ["signal_key"])

    op.create_table(
        "job_questions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("job_id", UUID(as_uuid=True), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("field_key", sa.String(255), nullable=False),
        sa.Column("label", sa.Text, server_default=""),
        sa.Column("field_type", sa.String(50), server_default="text"),
        sa.Column("required", sa.Boolean, server_default="false"),
        sa.Column("options", JSON, server_default="[]"),
        sa.Column("description", sa.Text, server_default=""),
        sa.Column("platform", sa.String(50), server_default=""),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_job_questions_job_id", "job_questions", ["job_id"])
    op.create_unique_constraint("uq_job_question_field", "job_questions", ["job_id", "field_key"])


def downgrade() -> None:
    op.drop_table("job_questions")
    op.drop_table("scoring_signals")
