"""Refactor alert_configs to admin-managed group notifications with email support.

Revision ID: l2m3n4o5p6q7
Revises: k1f2g3h4i5j6
Create Date: 2026-04-14

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "l2m3n4o5p6q7"
down_revision = "k1f2g3h4i5j6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add new columns
    op.add_column("alert_configs", sa.Column("name", sa.String(100), nullable=True))
    op.add_column("alert_configs", sa.Column("email_recipients", sa.Text(), nullable=True))
    op.add_column("alert_configs", sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True))

    # Make webhook_url nullable (email channel doesn't need it)
    op.alter_column("alert_configs", "webhook_url", existing_type=sa.Text(), nullable=True)

    # Copy user_id to created_by, set default name
    op.execute("UPDATE alert_configs SET created_by = user_id, name = 'Job Alert'")

    # Make name not-null after backfill
    op.alter_column("alert_configs", "name", nullable=False)

    # Drop old user_id column and its index
    op.drop_index("idx_alert_configs_user")
    op.drop_column("alert_configs", "user_id")


def downgrade() -> None:
    op.add_column("alert_configs", sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True))
    op.execute("UPDATE alert_configs SET user_id = created_by")
    op.alter_column("alert_configs", "user_id", nullable=False)
    op.alter_column("alert_configs", "webhook_url", existing_type=sa.Text(), nullable=False)
    op.create_index("idx_alert_configs_user", "alert_configs", ["user_id"])
    op.drop_column("alert_configs", "created_by")
    op.drop_column("alert_configs", "email_recipients")
    op.drop_column("alert_configs", "name")
