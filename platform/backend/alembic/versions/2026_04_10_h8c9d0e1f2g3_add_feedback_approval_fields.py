"""Add feedback approval fields.

Revision ID: h8c9d0e1f2g3
Revises: g7b8c9d0e1f2
Create Date: 2026-04-10

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "h8c9d0e1f2g3"
down_revision = "g7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("feedback", sa.Column("approved_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True))
    op.add_column("feedback", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("feedback", sa.Column("approver_role", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("feedback", "approver_role")
    op.drop_column("feedback", "approved_at")
    op.drop_column("feedback", "approved_by")
