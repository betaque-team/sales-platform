"""Add feedback attachments column.

Revision ID: j0e1f2g3h4i5
Revises: i9d0e1f2g3h4
Create Date: 2026-04-13

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "j0e1f2g3h4i5"
down_revision = "i9d0e1f2g3h4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("feedback", sa.Column("attachments", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("feedback", "attachments")
