"""Add `feature` column to ai_customization_logs for per-feature rate limiting.

Revision ID: s9n0o1p2q3r4
Revises: r8m9n0o1p2q3
Create Date: 2026-04-17

Regression finding 236: rate-limit & audit-log the cover-letter and
interview-prep AI endpoints the same way customize already is. The
existing ``ai_customization_logs`` table is the right home — instead
of creating two parallel tables (which would duplicate the
``user_id`` / ``input_tokens`` / ``output_tokens`` / ``success`` /
``created_at`` shape), we add a single ``feature`` column to
discriminate which AI endpoint produced each row.

Constraints:

- Default value ``'customize'`` so the existing ~N rows that landed
  before this migration are correctly attributed to the only feature
  that was logging at the time. Avoids a backfill round-trip.
- ``NOT NULL`` so the rate-limit query (``WHERE user_id=? AND
  feature=? AND success=True``) doesn't accidentally count rows whose
  feature column is ``NULL`` for any future feature that was added
  but forgot to set it.
- Indexed on ``(user_id, feature, created_at)`` to keep the
  rate-limit lookup O(1)-cardinality even after the table grows
  past ~10k rows. The previous index (``user_id`` only) became a
  scan-heavy bottleneck the moment we added two more discriminator
  values.
- ``resume_id`` and ``job_id`` columns become nullable in this
  migration too — the cover-letter and interview-prep flows write
  rows with a ``job_id`` but no ``resume_id`` (the user's active
  resume is referenced by id, not snapshotted), and the customize
  flow stays as-is. Making both nullable preserves the existing
  customize semantics while letting the new flows write without
  needing dummy values.

Idempotent: re-running ``alembic upgrade head`` on a fresh DB applies
the column with the documented default; on an existing DB it inspects
the table first via ``op.batch_alter_table`` so a second run is a
no-op rather than a duplicate-column error.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "s9n0o1p2q3r4"
down_revision = "r8m9n0o1p2q3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_cols = {c["name"] for c in inspector.get_columns("ai_customization_logs")}

    # Add `feature` column with a default of 'customize' so the rows
    # that were inserted by the customize flow before this column
    # existed get correctly attributed without a separate backfill
    # statement.
    if "feature" not in existing_cols:
        op.add_column(
            "ai_customization_logs",
            sa.Column(
                "feature",
                sa.String(length=32),
                nullable=False,
                server_default="customize",
            ),
        )

    # Make resume_id / job_id nullable so the cover-letter and
    # interview-prep flows can log without a resume-snapshot pointer.
    # The customize flow continues to populate them.
    existing_indexes = {ix["name"] for ix in inspector.get_indexes("ai_customization_logs")}
    with op.batch_alter_table("ai_customization_logs") as batch:
        col_meta = {c["name"]: c for c in inspector.get_columns("ai_customization_logs")}
        if col_meta.get("resume_id", {}).get("nullable") is False:
            batch.alter_column("resume_id", existing_type=sa.dialects.postgresql.UUID(), nullable=True)
        if col_meta.get("job_id", {}).get("nullable") is False:
            batch.alter_column("job_id", existing_type=sa.dialects.postgresql.UUID(), nullable=True)

    # Composite index so the per-user, per-feature, per-day count
    # used by the rate-limit check stays cheap.
    target_index = "ix_ai_customization_logs_user_feature_created"
    if target_index not in existing_indexes:
        op.create_index(
            target_index,
            "ai_customization_logs",
            ["user_id", "feature", "created_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_indexes = {ix["name"] for ix in inspector.get_indexes("ai_customization_logs")}
    if "ix_ai_customization_logs_user_feature_created" in existing_indexes:
        op.drop_index(
            "ix_ai_customization_logs_user_feature_created",
            table_name="ai_customization_logs",
        )
    existing_cols = {c["name"] for c in inspector.get_columns("ai_customization_logs")}
    if "feature" in existing_cols:
        op.drop_column("ai_customization_logs", "feature")
    # Leave resume_id/job_id as nullable on downgrade — flipping back
    # to NOT NULL would fail if any cover-letter/interview-prep rows
    # exist with NULL values in those columns.
