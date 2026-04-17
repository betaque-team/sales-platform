"""Add training_examples table for the training-data capture pipeline.

Revision ID: u1p2q3r4s5t6
Revises: t0o1p2q3r4s5
Create Date: 2026-04-17

Regression finding 238: capture (input → label) rows at every key
decision point on the platform so a future custom model has clean
labeled data to train on. Six initial task types, all sharing one
table:

  - resume_match           (resume + job → accept|reject)
  - role_classify          (job title + description → role_cluster)
  - cover_letter_quality   (resume + job + generated letter → kept|regenerated)
  - interview_prep_quality (resume + job + generated prep → applied|not)
  - customize_quality      (resume + job + customized text → applied|discarded)
  - search_intent          (filter state + query → clicked job ids)

Why one table not six: the shapes diverge (different inputs, labels)
but the access patterns are identical (filter by task_type, export
JSONL, count). One table + JSONB inputs/labels keeps schema migrations
to zero when a new task_type is added — just add a constant + start
writing rows.

Privacy:
  - `user_id_hash` (32-char hex) is the SHA-256 of `JWT_SECRET +
    user_id`. Stable per-environment so model training can group by
    user without exposing the real id. Never reversible without the
    JWT secret. Indexed because some training tasks need per-user
    splits (train on 80% of users, eval on the rest).
  - The actual `user_id` is NOT stored. The hook helpers compute the
    hash before writing. If you need to link back to the user for
    debugging, you have to manually compute the hash with the env
    secret and look it up.
  - Free-text fields (resume, JD, cover letter) get scrubbed by
    `app/utils/training_scrub.py` before write — emails / phones /
    full names redacted to placeholder tokens.
  - `created_at` is timezone-aware UTC. No raw IP, no session id,
    no email, no name. Operators can export and ship to a model
    trainer without a privacy review.

Indexes:
  - `(task_type, created_at DESC)` — primary access pattern: "give me
    all resume_match rows from the last 30 days for export".
  - `(task_type, label_class)` — for class-balance checks at training
    time (`SELECT label_class, COUNT(*) WHERE task_type='resume_match'
    GROUP BY label_class`).
  - `user_id_hash` — for per-user train/eval splits.

Idempotent — re-running on a fresh DB creates the table; on an
existing DB the inspector check is a no-op.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "u1p2q3r4s5t6"
down_revision = "t0o1p2q3r4s5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "training_examples" in set(inspector.get_table_names()):
        return

    op.create_table(
        "training_examples",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        # One of: resume_match | role_classify | cover_letter_quality
        # | interview_prep_quality | customize_quality | search_intent.
        # String not Enum so a new task type is a constant change, no
        # migration needed.
        sa.Column("task_type", sa.String(40), nullable=False),
        # Free-text label class (e.g. "accepted" / "rejected" /
        # "infra" / "kept" / "discarded"). Stored as a separate column
        # in addition to being inside `labels` JSONB so class-balance
        # queries don't need JSON path expressions. Optional because
        # some tasks have multi-dimensional labels (search_intent
        # outputs N clicked ids — no single class), in which case it
        # stays NULL and `labels` carries the structure.
        sa.Column("label_class", sa.String(64), nullable=True),
        sa.Column(
            "inputs",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "labels",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        # Optional metadata: model_version of the AI output (for
        # quality-task examples), source job id (for joining back to
        # a Job for analysis), reviewer role (admin/reviewer), etc.
        # Kept JSONB-flexible so additions don't need a migration.
        sa.Column(
            "metadata_json",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        # SHA-256(JWT_SECRET + user_id) hex digest, first 32 chars.
        # Stable per-environment, never reversible without the secret.
        # Indexed for per-user train/eval splits.
        sa.Column("user_id_hash", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    # Primary access pattern: time-windowed export by task type.
    op.create_index(
        "ix_training_examples_task_created",
        "training_examples",
        ["task_type", sa.text("created_at DESC")],
    )
    # Class-balance check.
    op.create_index(
        "ix_training_examples_task_label",
        "training_examples",
        ["task_type", "label_class"],
    )
    # Per-user split.
    op.create_index(
        "ix_training_examples_user_hash",
        "training_examples",
        ["user_id_hash"],
    )


def downgrade() -> None:
    op.drop_index("ix_training_examples_user_hash", table_name="training_examples")
    op.drop_index("ix_training_examples_task_label", table_name="training_examples")
    op.drop_index("ix_training_examples_task_created", table_name="training_examples")
    op.drop_table("training_examples")
