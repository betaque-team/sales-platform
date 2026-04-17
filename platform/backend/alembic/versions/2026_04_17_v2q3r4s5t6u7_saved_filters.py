"""Add saved_filters table for the saved-filter-presets feature.

Revision ID: v2q3r4s5t6u7
Revises: u1p2q3r4s5t6
Create Date: 2026-04-17

Regression finding 241 (khushi.jain feedback "Problem of Filter
Stickness" ×2): users want to save named filter presets and recall
them later, instead of re-applying the same filter combinations
manually each session.

Schema:

  - `id` UUID PK
  - `user_id` FK users (CASCADE so deleting a user removes their
    presets)
  - `name` VARCHAR(100) — user-chosen label, NOT NULL
  - `filters` JSONB — the JobFilters dict the frontend sends to
    /api/v1/jobs (search, status, platform, geography, role_cluster,
    is_classified, sort_by, sort_dir). JSONB rather than per-column
    so adding a new filter axis (e.g. company_size when F88 lands)
    is a no-op here — the frontend just starts including it in the
    payload.
  - `created_at`, `updated_at` TIMESTAMPTZ

  - UNIQUE (user_id, lower(name)) — preset names must be unique per
    user to avoid silent overwrites in the dropdown UI. Lower-cased
    so "Infra" and "infra" collide.

Idempotent — re-running on a fresh DB creates the table; on an
existing DB the inspector check is a no-op.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "v2q3r4s5t6u7"
down_revision = "u1p2q3r4s5t6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "saved_filters" in set(inspector.get_table_names()):
        return

    op.create_table(
        "saved_filters",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column(
            "filters",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    # Unique on (user_id, lower(name)) so "Infra" and "infra" collide.
    # Postgres-only — uses an expression index. If we ever support
    # SQLite for local dev, this needs a runtime guard.
    op.execute(
        "CREATE UNIQUE INDEX uq_saved_filters_user_name_lower "
        "ON saved_filters (user_id, lower(name))"
    )
    # Sort-listing index: user opens the dropdown, we ORDER BY
    # updated_at DESC. Composite covers the common query.
    op.create_index(
        "ix_saved_filters_user_updated",
        "saved_filters",
        ["user_id", sa.text("updated_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_saved_filters_user_updated", table_name="saved_filters")
    op.execute("DROP INDEX IF EXISTS uq_saved_filters_user_name_lower")
    op.drop_table("saved_filters")
