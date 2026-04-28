"""Add Application.company_id (denormalised) + stage_key for team pipeline.

Revision ID: d0e1f2g3h4i5
Revises: c9d0e1f2g3h4
Create Date: 2026-04-28

F261 — Team Pipeline Tracker. The Pipeline (PotentialClient) feature
already tracks one row per company. The user wants per-application
visibility: when did each user apply, with which resume, to which job
at which company, and where is each application now in the funnel.

Two columns on ``applications``:

(1) ``company_id`` (UUID FK, nullable, indexed)
    Denormalised from ``jobs.company_id``. The team feed lists
    applications across users + filters/groups by company; running that
    through ``Application JOIN Job`` on every page-load is wasteful when
    the value is immutable post-apply. Backfilled from the existing
    ``jobs`` row at migration time. Nullable because:
      * legacy applications might point at a job that was hard-deleted
        before this migration ran (the FK on ``job_id`` is
        ``ON DELETE CASCADE``, so the row vanishes — but if any survived
        a different code path, the column is forgiving).
      * keeps the migration zero-downtime: we don't need to wrap the
        backfill in a transaction that locks the whole table.

    ``ON DELETE SET NULL`` because deleting a Company is rare-but-
    possible (admin action) and we'd rather keep the application
    history than cascade-delete it.

(2) ``stage_key`` (String(50), nullable)
    Funnel position separate from ``status``. ``status`` is the apply-
    state machine (prepared → submitted → applied → interview → offer
    / rejected / withdrawn) — fine for "did we send it yet". ``stage``
    is the configurable pipeline stage (``pipeline_stages.key``) so
    admins can have "Interview 1", "Interview 2", "Final round",
    "Offer extended" etc. without code changes.

    Soft reference (no DB-level FK) because ``pipeline_stages`` rows
    can be soft-deleted (``is_active=false``) and we don't want a stale
    reference on an Application to block that. App-level validation
    in the PATCH endpoint checks the key exists + is active.

    Indexed for the hot query: "show me everything currently in the
    'interview' stage across the team."

Idempotent via ``_column_exists`` so re-runs are safe.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "d0e1f2g3h4i5"
down_revision = "c9d0e1f2g3h4"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns(table)}
    return column in cols


def _index_exists(table: str, name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return name in {ix["name"] for ix in inspector.get_indexes(table)}


def upgrade() -> None:
    # 1. applications.company_id — denormalised FK. Add nullable, then
    #    backfill from jobs.company_id, then add the index.
    if not _column_exists("applications", "company_id"):
        op.add_column(
            "applications",
            sa.Column(
                "company_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("companies.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        # Backfill in a single UPDATE — applications table is small
        # (low thousands), no need to chunk.
        op.execute(
            """
            UPDATE applications a
               SET company_id = j.company_id
              FROM jobs j
             WHERE a.job_id = j.id
               AND a.company_id IS NULL
            """
        )

    # Index after the backfill so we don't pay write amplification
    # during the UPDATE above.
    if not _index_exists("applications", "ix_applications_company_id"):
        op.create_index(
            "ix_applications_company_id",
            "applications",
            ["company_id"],
        )

    # 2. applications.stage_key — soft reference to pipeline_stages.key.
    if not _column_exists("applications", "stage_key"):
        op.add_column(
            "applications",
            sa.Column("stage_key", sa.String(50), nullable=True),
        )

    if not _index_exists("applications", "ix_applications_stage_key"):
        op.create_index(
            "ix_applications_stage_key",
            "applications",
            ["stage_key"],
        )


def downgrade() -> None:
    if _index_exists("applications", "ix_applications_stage_key"):
        op.drop_index(
            "ix_applications_stage_key", table_name="applications"
        )
    if _column_exists("applications", "stage_key"):
        op.drop_column("applications", "stage_key")
    if _index_exists("applications", "ix_applications_company_id"):
        op.drop_index(
            "ix_applications_company_id", table_name="applications"
        )
    if _column_exists("applications", "company_id"):
        op.drop_column("applications", "company_id")
