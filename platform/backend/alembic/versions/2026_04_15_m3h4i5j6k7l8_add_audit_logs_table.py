"""Add audit_logs table for security-sensitive actions.

Revision ID: m3h4i5j6k7l8
Revises: l2g3h4i5j6k7
Create Date: 2026-04-15

Regression finding 61 (audit-log half): forensic record of bulk-export
and other security-sensitive actions. The role-gate for exports landed
in an earlier commit; this migration lands the table + indexes that
the helper `app.utils.audit.log_action` writes into.

Indexes match the access patterns enumerated in `models/audit_log.py`:
single-column on `user_id` and `action`, plus a compound on
`created_at` to support "most-recent-first" scans efficiently.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "m3h4i5j6k7l8"
down_revision = "l2g3h4i5j6k7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("resource", sa.String(length=50), nullable=False),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=500), nullable=True),
        # `metadata_json` matches the existing Company.metadata_json
        # column convention; avoids clashing with `Base.metadata`.
        sa.Column(
            "metadata_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Single-column indexes matching mapped_column(..., index=True)
    # directives on the model so Alembic autogenerate runs are quiet.
    op.create_index(
        "ix_audit_logs_user_id",
        "audit_logs",
        ["user_id"],
    )
    op.create_index(
        "ix_audit_logs_action",
        "audit_logs",
        ["action"],
    )
    # Supports the "recent events" view which is the dominant read
    # path from the admin UI and any incident-response query.
    op.create_index(
        "ix_audit_logs_created_at_desc",
        "audit_logs",
        ["created_at"],
        postgresql_using="btree",
    )


def downgrade() -> None:
    op.drop_index("ix_audit_logs_created_at_desc", table_name="audit_logs")
    op.drop_index("ix_audit_logs_action", table_name="audit_logs")
    op.drop_index("ix_audit_logs_user_id", table_name="audit_logs")
    op.drop_table("audit_logs")
