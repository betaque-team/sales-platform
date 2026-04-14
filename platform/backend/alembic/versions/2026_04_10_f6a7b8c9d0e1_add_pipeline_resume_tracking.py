"""Add resume_id and applied_by to pipeline.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-04-10
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("potential_clients", sa.Column("resume_id", UUID(as_uuid=True), sa.ForeignKey("resumes.id"), nullable=True))
    op.add_column("potential_clients", sa.Column("applied_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True))


def downgrade() -> None:
    op.drop_column("potential_clients", "applied_by")
    op.drop_column("potential_clients", "resume_id")
