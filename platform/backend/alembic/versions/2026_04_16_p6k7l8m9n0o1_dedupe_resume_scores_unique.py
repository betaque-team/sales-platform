"""Dedupe resume_scores + add UNIQUE(resume_id, job_id).

Revision ID: p6k7l8m9n0o1
Revises: o5j6k7l8m9n0
Create Date: 2026-04-16

Companion to the handler hotfix: `resume_scores` was accumulating
duplicate rows per (resume_id, job_id) because the score-write
path does plain INSERT instead of ON CONFLICT DO UPDATE, and
several scoring entry points fire concurrently (post-upload task,
manual rescore, `rescore_all_active_resumes` beat job). On a
test-admin resume that's been in play long enough, the table
had 10,414 rows for ~13k jobs — well above the 1 row per pair
invariant the read-side handlers assumed.

The handler fix (`jobs.py`, `resume.py`, `applications.py`) uses
`ORDER BY scored_at DESC LIMIT 1` so it tolerates duplicates in
place. That's a last-write-wins workaround; this migration is
the real cleanup. Two steps:

1. Dedupe in place using a `row_number()` CTE that ranks rows
   within each (resume_id, job_id) pair by scored_at DESC. Keep
   the most recent row, delete the rest.

2. Add a UNIQUE constraint on (resume_id, job_id) so any future
   write that bypasses the ON CONFLICT path fails loudly at the
   DB instead of silently creating drift again.

The write-side fix (make the worker use `ON CONFLICT (resume_id,
job_id) DO UPDATE ...`) is a separate commit — migration first
so the constraint exists before the ON CONFLICT clause can
reference it.

Order matters: dedupe BEFORE the constraint, otherwise the
ALTER TABLE fails against the existing duplicates.

This migration is idempotent: re-running after manual dedupe
does nothing for step 1 (the ranked delete is a no-op when
every rank is 1), and step 2 is guarded by an IF NOT EXISTS-
equivalent via `CREATE UNIQUE INDEX IF NOT EXISTS`.
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "p6k7l8m9n0o1"
down_revision = "o5j6k7l8m9n0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Dedupe. Keep the most recently-scored row per (resume_id,
    #    job_id) pair; delete the rest. `row_number()` on a window
    #    partitioned by the target pair + ordered by scored_at DESC
    #    puts the survivor at rank 1; ranks >= 2 get dropped. Ties
    #    on scored_at break by `id` DESC just for determinism —
    #    matters when two parallel writes landed within the same
    #    millisecond and both wrote `NOW()`.
    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY resume_id, job_id
                       ORDER BY scored_at DESC, id DESC
                   ) AS rn
            FROM resume_scores
        )
        DELETE FROM resume_scores
        WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
        """
    )

    # 2. UNIQUE index on (resume_id, job_id). Using `CREATE UNIQUE
    #    INDEX IF NOT EXISTS` so reruns are safe. The index name
    #    matches what SQLAlchemy would auto-generate for a
    #    `UniqueConstraint`, so if we later add the constraint at
    #    the model level, alembic's autogenerate won't want to
    #    create a second one.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_resume_scores_resume_job "
        "ON resume_scores (resume_id, job_id)"
    )


def downgrade() -> None:
    # Drop the unique index. The dedupe is not reversible — we
    # can't reconstruct rows we deleted, and downgrade is a
    # rollback path, not a restore path.
    op.execute("DROP INDEX IF EXISTS uq_resume_scores_resume_job")
