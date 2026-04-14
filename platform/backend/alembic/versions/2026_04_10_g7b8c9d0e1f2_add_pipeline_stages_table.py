"""Add pipeline_stages table for dynamic stage config.

Revision ID: g7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-04-10

"""
from alembic import op
import sqlalchemy as sa
from uuid import uuid4

# revision identifiers, used by Alembic.
revision = "g7b8c9d0e1f2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pipeline_stages",
        sa.Column("id", sa.Uuid(), primary_key=True, default=uuid4),
        sa.Column("key", sa.String(50), unique=True, nullable=False),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("color", sa.String(50), server_default="bg-gray-500"),
        sa.Column("sort_order", sa.Integer(), server_default="0"),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
    )


def downgrade() -> None:
    op.drop_table("pipeline_stages")
