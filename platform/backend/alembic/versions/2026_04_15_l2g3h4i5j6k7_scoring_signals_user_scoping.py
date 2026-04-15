"""Add user_id to scoring_signals and composite uniqueness.

Revision ID: l2g3h4i5j6k7
Revises: k1f2g3h4i5j6
Create Date: 2026-04-15

Regression finding 89: per-user isolation for feedback signals.

Adds a nullable `user_id` FK column to `scoring_signals` so that each
reviewer's feedback stays in its own row per signal_key. Drops the
old `signal_key`-only unique constraint (or unique index, depending
on how the original `unique=True` was materialized) and replaces it
with a composite `(user_id, signal_key)` unique constraint so the
same key can co-exist across users.

Pre-existing rows keep `user_id = NULL`, which participates in the
shared legacy pool — nightly `rescore_jobs` continues to sum over
everything for backward compatibility. Per-user query-time scoring
(layer 2) is a follow-up that builds on this column.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "l2g3h4i5j6k7"
down_revision = "k1f2g3h4i5j6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add the nullable user_id column with FK cascade on user delete.
    op.add_column(
        "scoring_signals",
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_scoring_signals_user_id",
        "scoring_signals",
        ["user_id"],
    )

    # 2. Drop the old single-column unique constraint/index on signal_key.
    # SQLAlchemy's `unique=True` + `index=True` on `signal_key` produced
    # the index name `ix_scoring_signals_signal_key` (with UNIQUE). We
    # drop and recreate as a non-unique index so lookups by key still
    # work; uniqueness moves to the composite below.
    op.drop_index(
        "ix_scoring_signals_signal_key",
        table_name="scoring_signals",
    )
    op.create_index(
        "ix_scoring_signals_signal_key",
        "scoring_signals",
        ["signal_key"],
        unique=False,
    )

    # 3. Add the composite uniqueness. Postgres treats NULL as distinct
    # in unique constraints, so legacy rows with user_id = NULL don't
    # collide with new per-user rows sharing a signal_key.
    op.create_unique_constraint(
        "uq_scoring_signals_user_key",
        "scoring_signals",
        ["user_id", "signal_key"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_scoring_signals_user_key",
        "scoring_signals",
        type_="unique",
    )
    op.drop_index(
        "ix_scoring_signals_signal_key",
        table_name="scoring_signals",
    )
    op.create_index(
        "ix_scoring_signals_signal_key",
        "scoring_signals",
        ["signal_key"],
        unique=True,
    )
    op.drop_index(
        "ix_scoring_signals_user_id",
        table_name="scoring_signals",
    )
    op.drop_column("scoring_signals", "user_id")
