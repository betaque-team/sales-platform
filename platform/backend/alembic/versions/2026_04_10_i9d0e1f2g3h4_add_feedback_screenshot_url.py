"""Add screenshot_url to feedback.

Revision ID: i9d0e1f2g3h4
Revises: h8c9d0e1f2g3
Create Date: 2026-04-10

"""
from alembic import op
import sqlalchemy as sa

revision = "i9d0e1f2g3h4"
down_revision = "h8c9d0e1f2g3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("feedback", sa.Column("screenshot_url", sa.String(1000), nullable=True))


def downgrade() -> None:
    op.drop_column("feedback", "screenshot_url")
