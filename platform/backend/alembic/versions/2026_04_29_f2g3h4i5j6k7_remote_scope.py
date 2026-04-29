"""Remote scope redefinition — replace geography_bucket vocabulary.

Revision ID: f2g3h4i5j6k7
Revises: e1f2g3h4i5j6
Create Date: 2026-04-29

Originally landed as ``d0e1f2g3h4i5`` on 2026-04-27, but two parallel
feature branches (``routine_prefs_and_targets`` and
``application_company_stage``) had picked the same revision IDs in
sequence. Renumbered + re-chained on top of the renumbered work-time
migration (``e1f2g3h4i5j6_work_time_windows``).

The team was confused by the legacy ``geography_bucket`` enum
(``global_remote`` / ``usa_only`` / ``uae_only`` / ``""``):

  * Naming asymmetry — "Global Remote" is positive, "USA Only" is
    exclusive; both describe the same axis but use different verbs.
  * "USA Only" was ambiguous about residency vs. citizenship vs.
    company-side preference. Confirmed semantic: candidate must
    reside in the country, job is remote.
  * Empty string conflated "we haven't classified" with "region-
    locked to somewhere not in our 2-country list".
  * Hardcoded country buckets — adding India required a migration.
  * No on-site / hybrid distinction.

This migration introduces two new columns on ``jobs``:

  * ``remote_policy VARCHAR(32) NOT NULL DEFAULT 'unknown'`` — clean
    enum: ``worldwide`` | ``country_restricted`` | ``region_restricted``
    | ``hybrid`` | ``onsite`` | ``unknown``.
  * ``remote_policy_countries JSONB NOT NULL DEFAULT '[]'`` — ISO-3166
    country codes for the ``country_restricted`` case. Adding a new
    country becomes data, not migration.

Backfill is deterministic from the existing ``geography_bucket``:

  * ``global_remote`` → ``worldwide`` + ``[]``
  * ``usa_only``      → ``country_restricted`` + ``["US"]``
  * ``uae_only``      → ``country_restricted`` + ``["AE"]``
  * ``""`` (empty)    → ``unknown`` + ``[]``

The legacy ``geography_bucket`` column is kept on the model and is
shadow-written for one release so any out-of-tree analytics/exports
keep functioning. A follow-up migration will drop it.

Indexes:
  * ``idx_jobs_remote_policy`` — equivalent of the existing
    ``idx_jobs_geography``.
  * ``idx_jobs_remote_policy_countries`` — GIN, supports the
    ``remote_policy_countries @> ['US']`` containment filter.

Idempotent via inspector checks. Re-running ``alembic upgrade head``
after a partial apply is safe.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision = "f2g3h4i5j6k7"
down_revision = "e1f2g3h4i5j6"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return column in {c["name"] for c in inspector.get_columns(table)}


def _index_exists(table: str, index: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return index in {ix["name"] for ix in inspector.get_indexes(table)}


def upgrade() -> None:
    if not _column_exists("jobs", "remote_policy"):
        op.add_column(
            "jobs",
            sa.Column(
                "remote_policy",
                sa.String(length=32),
                server_default="unknown",
                nullable=False,
            ),
        )
    if not _column_exists("jobs", "remote_policy_countries"):
        op.add_column(
            "jobs",
            sa.Column(
                "remote_policy_countries",
                JSONB,
                server_default="[]",
                nullable=False,
            ),
        )

    # Backfill in a single pass — set remote_policy + remote_policy_countries
    # from the legacy ``geography_bucket``. The CASE expression keeps
    # this transactional + idempotent: re-running the migration just
    # re-writes the same values.
    op.execute(
        """
        UPDATE jobs
        SET
          remote_policy = CASE geography_bucket
            WHEN 'global_remote' THEN 'worldwide'
            WHEN 'usa_only'      THEN 'country_restricted'
            WHEN 'uae_only'      THEN 'country_restricted'
            ELSE 'unknown'
          END,
          remote_policy_countries = CASE geography_bucket
            WHEN 'usa_only' THEN '["US"]'::jsonb
            WHEN 'uae_only' THEN '["AE"]'::jsonb
            ELSE '[]'::jsonb
          END
        WHERE remote_policy = 'unknown' AND remote_policy_countries = '[]'::jsonb;
        """
    )

    if not _index_exists("jobs", "idx_jobs_remote_policy"):
        op.create_index("idx_jobs_remote_policy", "jobs", ["remote_policy"])
    if not _index_exists("jobs", "idx_jobs_remote_policy_countries"):
        # GIN supports the ``@>`` containment operator the API uses
        # for "match jobs that include this country".
        op.create_index(
            "idx_jobs_remote_policy_countries",
            "jobs",
            ["remote_policy_countries"],
            postgresql_using="gin",
        )


def downgrade() -> None:
    if _index_exists("jobs", "idx_jobs_remote_policy_countries"):
        op.drop_index("idx_jobs_remote_policy_countries", table_name="jobs")
    if _index_exists("jobs", "idx_jobs_remote_policy"):
        op.drop_index("idx_jobs_remote_policy", table_name="jobs")
    if _column_exists("jobs", "remote_policy_countries"):
        op.drop_column("jobs", "remote_policy_countries")
    if _column_exists("jobs", "remote_policy"):
        op.drop_column("jobs", "remote_policy")
