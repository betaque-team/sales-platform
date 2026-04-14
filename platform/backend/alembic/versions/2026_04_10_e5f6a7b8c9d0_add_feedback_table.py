"""Add feedback table.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-04-10
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "feedback",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("priority", sa.String(20), server_default="medium", nullable=False),
        sa.Column("status", sa.String(20), server_default="open", nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("steps_to_reproduce", sa.Text),
        sa.Column("expected_behavior", sa.Text),
        sa.Column("actual_behavior", sa.Text),
        sa.Column("use_case", sa.Text),
        sa.Column("proposed_solution", sa.Text),
        sa.Column("impact", sa.Text),
        sa.Column("admin_notes", sa.Text),
        sa.Column("resolved_by", UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_feedback_user_id", "feedback", ["user_id"])
    op.create_index("ix_feedback_status", "feedback", ["status"])
    op.create_index("ix_feedback_category", "feedback", ["category"])


def downgrade() -> None:
    op.drop_index("ix_feedback_category")
    op.drop_index("ix_feedback_status")
    op.drop_index("ix_feedback_user_id")
    op.drop_table("feedback")
