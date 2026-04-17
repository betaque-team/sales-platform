"""Add submission_source + submitted_by_user_id to jobs.

Revision ID: q7l8m9n0o1p2
Revises: p6k7l8m9n0o1
Create Date: 2026-04-17

Feature A — Manual job link submission. A sales user pastes an ATS URL
and we run it through the same ingestion pipeline as the scanners
(``_upsert_job``) so classification / scoring / geography behave
identically to scanned jobs. Two new columns capture provenance:

- ``submission_source`` — string enum with documented values
  ``scan`` (default; every row written by the scan pipeline) and
  ``manual_link`` (written by ``POST /jobs/submit-link``). Kept as a
  string (not a PG ENUM) to match the existing convention for
  ``Job.status`` / ``Application.status`` — adding a new value in the
  future is an app-level constant change, not a migration.
- ``submitted_by_user_id`` — nullable FK to ``users.id``. Only
  populated for ``manual_link`` rows; scanned rows leave it NULL.
  ``ON DELETE SET NULL`` so removing a user doesn't cascade-delete
  their imported jobs — the job still exists, we just lose the
  "who added it" attribution.

No backfill is needed: default ``'scan'`` covers every existing row
and the NULL-by-default FK is already the correct state for all
historical jobs.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision = "q7l8m9n0o1p2"
down_revision = "p6k7l8m9n0o1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column(
            "submission_source",
            sa.String(length=30),
            nullable=False,
            server_default="scan",
        ),
    )
    # `postgresql.UUID(as_uuid=True)` matches the convention every other
    # migration in this repo follows (b2c3d4e5f6a7, e5f6a7b8c9d0,
    # f6a7b8c9d0e1, etc.). `sa.UUID()` works on PG 2.0+ but diverges
    # from the shared style and can surprise autogenerate comparisons.
    op.add_column(
        "jobs",
        sa.Column(
            "submitted_by_user_id",
            UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_jobs_submitted_by_user",
        "jobs",
        "users",
        ["submitted_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_jobs_submission_source",
        "jobs",
        ["submission_source"],
    )


def downgrade() -> None:
    op.drop_index("ix_jobs_submission_source", table_name="jobs")
    op.drop_constraint("fk_jobs_submitted_by_user", "jobs", type_="foreignkey")
    op.drop_column("jobs", "submitted_by_user_id")
    op.drop_column("jobs", "submission_source")
