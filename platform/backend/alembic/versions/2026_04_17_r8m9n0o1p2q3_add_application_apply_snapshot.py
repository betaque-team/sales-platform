"""Add apply-time snapshot columns + submission_source to applications.

Revision ID: r8m9n0o1p2q3
Revises: q7l8m9n0o1p2
Create Date: 2026-04-17

Feature C — "Applied" action from the review queue. A reviewer hits the
Applied button (new fourth button alongside Skip/Reject/Accept) and the
server atomically upserts an ``Application`` row in ``status='applied'``,
flips ``Job.status='accepted'``, and creates/updates the company's
``PotentialClient`` pipeline row — Applied implies Accept.

To satisfy "all the data used while applying" on the Applications page,
we snapshot three pieces of state **at apply time** so they survive
future edits to the underlying resume:

- ``applied_resume_text`` (TEXT) — the resume body that was submitted.
  Either the raw resume text or the AI-customized text, whichever the
  reviewer chose. Nullable because this feature shipped after many
  prepared/submitted rows already existed — backfilling `NULL` is the
  honest signal of "no snapshot was captured for this legacy row".
- ``applied_resume_score_snapshot`` (JSONB) — ``{overall, keyword,
  role_match, format}`` score components at submit-time. Frozen so the
  Applications detail view can show "scored 82 when submitted" even
  after the resume is edited and re-scored.
- ``ai_customization_log_id`` (FK nullable) — links to
  ``ai_customization_logs`` so audit trails can reconstruct which
  Claude run produced the snapshot. ``ON DELETE SET NULL`` — purging
  AI logs (e.g. on retention rotation) must not cascade-delete the
  Application row it references.

Plus ``submission_source`` (TEXT enum, default ``'manual_prepare'``)
mirroring the column we added to ``jobs`` in ``q7l8m9n0o1p2``. Values:
``manual_prepare`` (created via ``/applications/prepare``),
``review_queue`` (created via the new ``/reviews/apply`` endpoint).
Kept as a plain string to match the existing ``status`` convention
and keep future additions to a single constant change.

Existing rows get ``submission_source='manual_prepare'`` via the server
default — every historical Application was created by the prepare
handler, so that's the correct backfill.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "r8m9n0o1p2q3"
down_revision = "q7l8m9n0o1p2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "applications",
        sa.Column("applied_resume_text", sa.Text(), nullable=True),
    )
    op.add_column(
        "applications",
        sa.Column(
            "applied_resume_score_snapshot",
            sa.JSON(),
            nullable=True,
        ),
    )
    op.add_column(
        "applications",
        sa.Column("ai_customization_log_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_applications_ai_customization_log",
        "applications",
        "ai_customization_logs",
        ["ai_customization_log_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "applications",
        sa.Column(
            "submission_source",
            sa.String(length=30),
            nullable=False,
            server_default="manual_prepare",
        ),
    )
    op.create_index(
        "ix_applications_submission_source",
        "applications",
        ["submission_source"],
    )


def downgrade() -> None:
    op.drop_index("ix_applications_submission_source", table_name="applications")
    op.drop_column("applications", "submission_source")
    op.drop_constraint(
        "fk_applications_ai_customization_log",
        "applications",
        type_="foreignkey",
    )
    op.drop_column("applications", "ai_customization_log_id")
    op.drop_column("applications", "applied_resume_score_snapshot")
    op.drop_column("applications", "applied_resume_text")
