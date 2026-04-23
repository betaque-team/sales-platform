"""Routine run idempotency — add idempotency_key column + unique index.

Context
-------
POST /routine/runs had no idempotency protection before this migration.
A network blip on the routine side (MCP-Chrome browser loses backend
connectivity mid-request, request completes server-side but client
never sees the response, client retries) produces two
``status="running"`` rows for the same logical session — there's no
way to tell them apart after the fact, and the operator ends up with
ghost runs cluttering /routine/runs.

This migration adds an optional client-supplied key. When present,
the handler upserts on ``(user_id, idempotency_key)`` and returns
the existing run_id on retry.

Constraint shape
----------------
- Column ``idempotency_key`` is ``VARCHAR(64)`` NULL. Absent key =
  no idempotency protection (old behavior). 64 chars accommodates a
  hex-encoded UUID4 plus padding.
- UNIQUE constraint on ``(user_id, idempotency_key)`` — scoped to
  user so two users can legitimately use the same key string. NULL
  values are ignored by unique constraints in Postgres so runs
  without a key don't collide.

No backfill. Existing rows get NULL for the new column and are
unaffected by the new constraint.
"""

from alembic import op
import sqlalchemy as sa


revision = "z6u7v8w9x0y1"
down_revision = "y5t6u7v8w9x0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "routine_runs",
        sa.Column("idempotency_key", sa.String(64), nullable=True),
    )
    # Partial-unique via a regular UNIQUE on (user_id, key); Postgres
    # treats NULL distinct from every other NULL, so rows without a
    # key are never considered conflicting. If we ever migrate to a
    # DB that treats NULLs as equal, switch this to a partial index
    # ``WHERE idempotency_key IS NOT NULL``.
    op.create_unique_constraint(
        "uq_routine_runs_user_idempotency_key",
        "routine_runs",
        ["user_id", "idempotency_key"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_routine_runs_user_idempotency_key",
        "routine_runs",
        type_="unique",
    )
    op.drop_column("routine_runs", "idempotency_key")
