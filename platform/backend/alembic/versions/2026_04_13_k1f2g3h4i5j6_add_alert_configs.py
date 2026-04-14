"""Add alert_configs table.

Revision ID: k1f2g3h4i5j6
Revises: j0e1f2g3h4i5
Create Date: 2026-04-13

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "k1f2g3h4i5j6"
down_revision = "j0e1f2g3h4i5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "alert_configs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("channel", sa.String(50), server_default="google_chat"),
        sa.Column("webhook_url", sa.Text(), nullable=False),
        sa.Column("min_relevance_score", sa.Integer(), server_default="70"),
        sa.Column("role_clusters", sa.Text(), nullable=True),
        sa.Column("geography_filter", sa.String(50), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_alert_configs_user", "alert_configs", ["user_id"])
    op.create_index("idx_alert_configs_active", "alert_configs", ["is_active"])


def downgrade() -> None:
    op.drop_index("idx_alert_configs_active")
    op.drop_index("idx_alert_configs_user")
    op.drop_table("alert_configs")
