"""Add user routine preferences + routine_targets manual queue/exclude.

Revision ID: c9d0e1f2g3h4
Revises: b8c9d0e1f2g3
Create Date: 2026-04-27

F257 — give the operator real control over what the Apply Routine
targets next. Two changes:

(1) ``users.routine_preferences`` JSONB
    Per-user filter preferences for the routine's "next jobs" picker.
    JSONB so the schema can evolve (new toggles, sliders) without a
    migration per change. Defaults to an empty object; ``top-to-apply``
    treats any missing key as "don't filter on this".

    Documented shape (kept in sync with
    ``app.schemas.routine.RoutinePreferences``):
      {
        "only_global_remote":     bool,
        "allowed_geographies":    list[str],
        "min_relevance_score":    int (0-100),
        "min_resume_score":       int (0-100),
        "allowed_role_clusters":  list[str],
        "extra_excluded_platforms": list[str]
      }

(2) ``routine_targets`` table — manual per-job include/exclude list.
    Pre-fix the only way to influence what the routine applied to was
    the implicit relevance + cooldown logic. Now the user can:
      * "Apply to this job specifically" (intent='queued')
      * "Never queue this job for me" (intent='excluded')

    UNIQUE(user_id, job_id) means one row per (user, job) pair —
    re-pinning a job updates the existing row in place. Soft semantics
    (no FK ondelete cascade beyond the FKs already needed) so removing
    a job from the queue is just a row delete; no audit trail kept
    here (the audit_logs table already captures the action).

Idempotent via inspector ``IF NOT EXISTS`` checks so re-runs are safe.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "c9d0e1f2g3h4"
down_revision = "b8c9d0e1f2g3"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns(table)}
    return column in cols


def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table in set(inspector.get_table_names())


def upgrade() -> None:
    # 1. users.routine_preferences JSONB — empty object default.
    if not _column_exists("users", "routine_preferences"):
        op.add_column(
            "users",
            sa.Column(
                "routine_preferences",
                postgresql.JSONB(),
                server_default=sa.text("'{}'::jsonb"),
                nullable=False,
            ),
        )

    # 2. routine_targets table — manual queue / exclude list.
    if not _table_exists("routine_targets"):
        op.create_table(
            "routine_targets",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "user_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "job_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("jobs.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("intent", sa.String(20), nullable=False),
            sa.Column("note", sa.Text(), server_default="", nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.UniqueConstraint(
                "user_id", "job_id", name="uq_routine_targets_user_job"
            ),
        )
        # Index for the hot lookup: "give me all routine_targets for
        # this user so I can apply boost / exclude during top-to-apply".
        op.create_index(
            "ix_routine_targets_user_intent",
            "routine_targets",
            ["user_id", "intent"],
        )


def downgrade() -> None:
    if _table_exists("routine_targets"):
        op.drop_index(
            "ix_routine_targets_user_intent", table_name="routine_targets"
        )
        op.drop_table("routine_targets")
    if _column_exists("users", "routine_preferences"):
        op.drop_column("users", "routine_preferences")
