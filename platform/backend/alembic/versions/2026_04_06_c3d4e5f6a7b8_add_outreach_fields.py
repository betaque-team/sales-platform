"""Add outreach fields to company_contacts.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-04-06
"""

from alembic import op
import sqlalchemy as sa

revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "company_contacts",
        sa.Column("outreach_status", sa.String(50), nullable=False, server_default="not_contacted"),
    )
    op.add_column(
        "company_contacts",
        sa.Column("outreach_note", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "company_contacts",
        sa.Column("last_outreach_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("company_contacts", "last_outreach_at")
    op.drop_column("company_contacts", "outreach_note")
    op.drop_column("company_contacts", "outreach_status")
