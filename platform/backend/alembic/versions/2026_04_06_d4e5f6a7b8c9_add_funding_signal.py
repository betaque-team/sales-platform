"""Add funded_at and funding_news_url to companies.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-04-06
"""

from alembic import op
import sqlalchemy as sa

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "companies",
        sa.Column("funded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "companies",
        sa.Column("funding_news_url", sa.String(1000), nullable=False, server_default=""),
    )
    op.create_index("idx_companies_funded_at", "companies", ["funded_at"])


def downgrade() -> None:
    op.drop_index("idx_companies_funded_at", "companies")
    op.drop_column("companies", "funding_news_url")
    op.drop_column("companies", "funded_at")
