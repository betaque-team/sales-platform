"""Add user_insights + product_insights tables for the AI Intelligence feature.

Revision ID: t0o1p2q3r4s5
Revises: s9n0o1p2q3r4
Create Date: 2026-04-17

Regression finding 237: a Celery task runs twice a week (Mon + Thu at
04:00 UTC) and produces two kinds of LLM-generated insights:

  (A) Per-user actionable insights — "your acceptance rate on infra
      is 60% vs 25% on security; narrow your filter". Stored in
      `user_insights`. Surfaced via GET /api/v1/insights/me (the
      latest run for the current user) and the new Insights sidebar
      page.

  (B) Product-improvement signals — admin-facing analysis of
      platform-wide patterns ("companies hitting accept rate >70%
      that AREN'T in the targets list — auto-promote candidates").
      Stored in `product_insights`. Surfaced via GET
      /api/v1/insights/product (admin only) and a new Monitoring tile.

Schema rationale:

  - `insights` JSONB on both tables — the LLM output is a structured
    array of `{title, body, action_link, severity}` items, but the
    shape is intentionally flexible so we can iterate the prompt
    output schema without an Alembic migration per change. Indexed
    only by `(user_id, generated_at desc)` / `(generated_at desc)`
    so "latest insight for this user/this run" is O(1).
  - `generation_id` UUID — groups all per-user rows produced by the
    same beat-task run. Lets us answer "show me everyone's insights
    from Monday's run" or "delete the run that had a bad prompt
    version" without joining on a brittle timestamp range.
  - `model_version` String — what we sent to (Sonnet 4 today). Lets
    us A/B prompt or model versions and trace back which run
    produced which insight when we change models.
  - `prompt_version` String — semantic version of the insight-
    generation prompt. Lets the next iteration's `looks-good` /
    `looks-bad` admin marks be filtered by which prompt produced
    them, so we can compare prompt revisions on the same eval set.
  - `actioned_at` / `dismissed_at` / `actioned_by` on
    `product_insights` — admin can mark an insight as "we shipped
    this" or "ignore". The next run's prompt sees the previous run's
    actioned suggestions and can score "did the metric move?". Closes
    the AI-improving-the-product loop the user asked for.

Idempotent — re-running `alembic upgrade head` is a no-op via
`IF NOT EXISTS` semantics on the table create + index create blocks.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "t0o1p2q3r4s5"
down_revision = "s9n0o1p2q3r4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "user_insights" not in existing_tables:
        op.create_table(
            "user_insights",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "user_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "generation_id",
                postgresql.UUID(as_uuid=True),
                nullable=False,
                comment="Run-grouping UUID — every per-user row from one beat task shares this.",
            ),
            sa.Column(
                "insights",
                postgresql.JSONB,
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
                comment="Array of {title, body, severity, action_link?} dicts.",
            ),
            sa.Column(
                "input_signals",
                postgresql.JSONB,
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
                comment="Snapshot of the inputs the LLM saw (acceptance rate, top tags, etc) — kept for debugging + prompt-version comparisons.",
            ),
            sa.Column("model_version", sa.String(64), nullable=False),
            sa.Column("prompt_version", sa.String(32), nullable=False),
            sa.Column("input_tokens", sa.Integer, nullable=False, server_default="0"),
            sa.Column("output_tokens", sa.Integer, nullable=False, server_default="0"),
            sa.Column(
                "generated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("NOW()"),
            ),
        )
        op.create_index(
            "ix_user_insights_user_generated",
            "user_insights",
            ["user_id", sa.text("generated_at DESC")],
        )
        op.create_index(
            "ix_user_insights_generation",
            "user_insights",
            ["generation_id"],
        )

    if "product_insights" not in existing_tables:
        op.create_table(
            "product_insights",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "generation_id",
                postgresql.UUID(as_uuid=True),
                nullable=False,
                comment="UUID of the beat-task run that produced this insight.",
            ),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("body", sa.Text, nullable=False),
            sa.Column(
                "category",
                sa.String(50),
                nullable=False,
                server_default="other",
                comment="Coarse bucket: ux | scoring | data | feature_request | other.",
            ),
            sa.Column(
                "severity",
                sa.String(20),
                nullable=False,
                server_default="medium",
                comment="low | medium | high — drives admin tile sort.",
            ),
            sa.Column(
                "input_signals",
                postgresql.JSONB,
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column("model_version", sa.String(64), nullable=False),
            sa.Column("prompt_version", sa.String(32), nullable=False),
            sa.Column("input_tokens", sa.Integer, nullable=False, server_default="0"),
            sa.Column("output_tokens", sa.Integer, nullable=False, server_default="0"),
            sa.Column(
                "generated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("NOW()"),
            ),
            # Action-tracking — closes the loop on "did the suggestion
            # actually improve things?" Default NULL = pending review.
            sa.Column(
                "actioned_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column(
                "actioned_by",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "actioned_status",
                sa.String(20),
                nullable=True,
                comment="actioned | dismissed | duplicate. NULL = pending.",
            ),
            sa.Column(
                "actioned_note",
                sa.Text,
                nullable=True,
                comment="Admin's note on why they actioned/dismissed — fed back into the next prompt run as context.",
            ),
        )
        op.create_index(
            "ix_product_insights_generation",
            "product_insights",
            ["generation_id"],
        )
        op.create_index(
            "ix_product_insights_pending",
            "product_insights",
            [sa.text("generated_at DESC")],
            postgresql_where=sa.text("actioned_at IS NULL"),
        )


def downgrade() -> None:
    op.drop_index("ix_product_insights_pending", table_name="product_insights")
    op.drop_index("ix_product_insights_generation", table_name="product_insights")
    op.drop_table("product_insights")
    op.drop_index("ix_user_insights_generation", table_name="user_insights")
    op.drop_index("ix_user_insights_user_generated", table_name="user_insights")
    op.drop_table("user_insights")
