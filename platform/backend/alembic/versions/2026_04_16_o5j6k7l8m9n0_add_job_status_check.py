"""Normalize Job.status + add CHECK constraint to the allowlist.

Revision ID: o5j6k7l8m9n0
Revises: n4i5j6k7l8m9
Create Date: 2026-04-16

Regression finding 99 (deploy-time invariant): 25 prod rows landed
in an illegal `status="reset"` state because the API layer accepted
any string. The Pydantic `Literal[...]` constraint (same commit)
closes the API half; this migration is the defense-in-depth so
future schema drift or direct-SQL writes can't corrupt the column
again.

Order of operations in upgrade() matters: we reset offending rows
first, THEN add the CHECK constraint. Reversing that order would
fail the ALTER on existing garbage. Using `UPDATE ... WHERE status
NOT IN (...)` so the migration is idempotent — re-runs after manual
cleanup do nothing.

Destination status = 'new'. Rationale: the bogus rows were almost
certainly reviewer-workflow mistakes and pushing them back to the
top of the review queue is the safest landing. Matches
`app/cleanup_job_status.py` (the equivalent out-of-band script
for ad-hoc runs).
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "o5j6k7l8m9n0"
down_revision = "n4i5j6k7l8m9"
branch_labels = None
depends_on = None


# Must stay in lockstep with `app.schemas.job.JOB_STATUS_VALUES`.
# Repeated here because migrations shouldn't import from application
# code that might be mid-refactor at deploy time.
_ALLOWED = ("new", "under_review", "accepted", "rejected", "hidden", "archived")


def upgrade() -> None:
    # 1. Normalize offending rows to "new" BEFORE the constraint lands.
    #    NULL values are left alone — the constraint allows NULL since
    #    we're not making the column NOT NULL (separate concern).
    allowed_sql = ", ".join(f"'{v}'" for v in _ALLOWED)
    op.execute(
        f"UPDATE jobs SET status = 'new' "
        f"WHERE status IS NOT NULL AND status NOT IN ({allowed_sql})"
    )

    # 2. Add the CHECK constraint. Named so downgrade() can drop it by
    #    name (Postgres auto-generates a name otherwise, which is
    #    brittle across deploys).
    op.create_check_constraint(
        "ck_jobs_status_allowlist",
        "jobs",
        f"status IS NULL OR status IN ({allowed_sql})",
    )


def downgrade() -> None:
    # Drop the constraint only. The "reset" rows stay at "new" — we
    # can't reliably un-normalize back to the original garbage
    # string, and downgrade is a rollback path, not a restore path.
    op.drop_constraint("ck_jobs_status_allowlist", "jobs", type_="check")
