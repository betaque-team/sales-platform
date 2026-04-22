"""Claude Routine Apply — tables + column extensions.

Adds the schema substrate for the automated-apply feature:

- ``routine_runs`` — one row per invocation of the apply routine
  (manual trial or scheduled), carrying counters + kill-switch
  state so the UI can show a per-run timeline.
- ``application_submissions`` — 1:1 with ``applications``, captures
  the full submitted payload (answers, screenshots, cover letter,
  profile snapshot, detected issues) so the user can see exactly
  what was sent AFTER the fact — the ATS form itself is ephemeral.
- ``humanization_corpus`` — draft→final pairs the user accepted
  during review; the style-match pass uses these as few-shot
  examples for future content generation.
- ``routine_kill_switches`` — one row per user; a simple boolean
  halt flag the routine polls between iterations. Separate table
  rather than a column on ``users`` so admins can add/remove
  without touching the hot auth table.

Column extensions:

- ``answer_book_entries.is_locked`` — marks the 16 seeded identity
  entries (salary / notice / work-auth / EEO) as "routine reads,
  never regenerates." UI allows editing the `answer` field only.
- ``applications.routine_run_id`` — SET NULL FK so deleting a run
  doesn't cascade-remove its applications (we keep the apps).

No backfill needed — all new tables empty, ``is_locked`` defaults
to FALSE so existing answer-book rows stay unlocked.
"""

import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "y5t6u7v8w9x0"
down_revision = "x4s5t6u7v8w9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── routine_runs ────────────────────────────────────────────────
    # Parent of application_submissions via routine_run_id FK; created
    # first so the FK target exists at the point of the other tables'
    # CREATE. We use ON DELETE SET NULL on both child FKs — if an
    # admin deletes a run row for cleanup, the submissions + apps
    # lose their link but the records themselves stay.
    op.create_table(
        "routine_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        # 'dry_run' (phase 1 default), 'live' (actual submit),
        # 'single_trial' (one-off manual test before scheduling).
        # String not Enum — we've been burned by postgres enum migrations
        # requiring ALTER TYPE dance in prior findings (F214).
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("applications_attempted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("applications_submitted", sa.Integer(), nullable=False, server_default="0"),
        # JSONB for skipped + incidents — fields like {job_id, reason}
        # / {platform, type, at}. Server-default to empty array so a
        # fresh row is queryable without null checks.
        sa.Column("applications_skipped", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("detection_incidents", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        # 'running' → 'complete' | 'aborted'. 'aborted' covers both
        # kill-switch trips and detection-circuit-breaker aborts.
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("kill_switch_triggered", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index(
        "ix_routine_runs_user_started",
        "routine_runs",
        ["user_id", sa.text("started_at DESC")],
    )

    # ── application_submissions ─────────────────────────────────────
    # 1:1 with applications — UNIQUE constraint on application_id so
    # the routine can't double-write a submission for the same app
    # (defense-in-depth against a retry that slipped past the
    # idempotency check in the handler).
    op.create_table(
        "application_submissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("application_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("applications.id", ondelete="CASCADE"),
                  nullable=False, unique=True),
        sa.Column("routine_run_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("routine_runs.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("job_url", sa.Text(), nullable=False),
        sa.Column("ats_platform", sa.String(50), nullable=False),
        # Stable hash of the ATS form structure (field names + order).
        # Lets us detect form changes between runs — if two submissions
        # to the same company have different fingerprints, the ATS
        # updated its form; routine should re-fetch the question schema.
        sa.Column("form_fingerprint_hash", sa.String(64), nullable=True),
        # Raw field_name → value map. PII redaction happens at write
        # time in the handler (email/phone stored as type+length, not
        # the value itself — already in user profile so no point
        # duplicating; SSN/DOB rejected before reaching here).
        sa.Column("payload_json", postgresql.JSONB(), nullable=False),
        # Per-answer provenance: list[{question, answer, source,
        # source_ref_id, edit_distance}]. `source` is one of
        # 'manual_required' | 'learned' | 'generated'. `source_ref_id`
        # points back to answer_book_entries.id for auditability.
        sa.Column("answers_json", postgresql.JSONB(), nullable=False),
        sa.Column("resume_version_hash", sa.String(64), nullable=True),
        sa.Column("cover_letter_text", sa.Text(), nullable=True),
        # List of local/S3 screenshot keys — typically [pre_submit,
        # post_submit_confirmation]. JSONB so we can extend with
        # per-screenshot metadata later (mime type, dimensions) without
        # a schema change.
        sa.Column("screenshot_keys", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("confirmation_text", sa.Text(), nullable=True),
        # Warnings surfaced from the apply flow — tag-sync failed,
        # captcha encountered, humanizer fell back to draft, etc.
        # Non-fatal; shown in the submission-detail UI as a yellow
        # banner so the user knows to review.
        sa.Column("detected_issues", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        # Frozen copy of the manual_required answer-book values as-sent.
        # If the user later edits their stored salary from 140k → 160k,
        # the app detail page still shows "140k was sent for this
        # application" — critical for interview / negotiation context.
        sa.Column("profile_snapshot", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index(
        "ix_application_submissions_submitted_at",
        "application_submissions",
        [sa.text("submitted_at DESC")],
    )
    op.create_index(
        "ix_application_submissions_run",
        "application_submissions",
        ["routine_run_id"],
    )

    # ── humanization_corpus ─────────────────────────────────────────
    # Training data for the style-match pass. Populated by the sync
    # path when the user approves a generated answer (edit-distance
    # captured from draft vs final) or by auto-promotion after 7 days
    # if the app got a positive outcome. The style-match pass loads
    # the last N rows and feeds them as few-shot examples.
    op.create_table(
        "humanization_corpus",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        # Nullable: if the app is deleted we want to keep the style
        # data — the user's voice doesn't depend on which job the
        # answer was written for.
        sa.Column("application_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("applications.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("draft_text", sa.Text(), nullable=False),
        sa.Column("final_text", sa.Text(), nullable=False),
        sa.Column("edit_distance", sa.Integer(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        # Flipped to TRUE when the answer is promoted into the answer
        # book (either by user click or auto-promotion after 7 days +
        # positive outcome). Lets the style-match loader deprioritize
        # already-canonical pairs so few-shot examples stay diverse.
        sa.Column("promoted_to_answer_book", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
    )
    op.create_index(
        "ix_humanization_corpus_user",
        "humanization_corpus",
        ["user_id", sa.text("accepted_at DESC")],
    )

    # ── routine_kill_switches ───────────────────────────────────────
    # One row per user; serves as a poll target between routine
    # iterations. The routine MUST call GET /routine/kill-switch at
    # the start of each app in a run; if `disabled=TRUE`, abort
    # within the same iteration. 60-second effective latency.
    op.create_table(
        "routine_kill_switches",
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("disabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
    )

    # ── Extend answer_book_entries ──────────────────────────────────
    # `is_locked` marks the 16 seeded manual_required entries as
    # read-for-routine / no-regenerate. Existing rows stay unlocked
    # (default FALSE), so this is a zero-behavior-change migration
    # for pre-routine data. The seed-required endpoint is the only
    # authorized creator of locked rows.
    #
    # We do NOT widen the `source` column's accepted-values set here
    # because it's a String(50) with no CHECK constraint — the
    # application layer owns the allowlist, and answer_book.py will
    # accept 'manual_required' / 'learned' / 'generated' alongside
    # the existing values on next deploy.
    op.add_column(
        "answer_book_entries",
        sa.Column("is_locked", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # Partial index — we only ever query WHERE is_locked=TRUE (for
    # required-coverage). The index covers just the ~16 locked rows
    # per user, not every answer-book entry.
    op.create_index(
        "ix_answer_book_entries_user_locked",
        "answer_book_entries",
        ["user_id"],
        postgresql_where=sa.text("is_locked = TRUE"),
    )

    # ── Extend applications ─────────────────────────────────────────
    # routine_run_id: nullable, SET NULL on run delete. Applications
    # created outside a routine (review-queue path, manual_prepare)
    # stay NULL — same as how existing rows have NULL legacy snapshots.
    op.add_column(
        "applications",
        sa.Column("routine_run_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("routine_runs.id", ondelete="SET NULL"),
                  nullable=True),
    )
    op.create_index(
        "ix_applications_routine_run",
        "applications",
        ["routine_run_id"],
    )


def downgrade() -> None:
    # Reverse order of creation; drop indexes before columns/tables
    # to keep the rollback script clean.
    op.drop_index("ix_applications_routine_run", table_name="applications")
    op.drop_column("applications", "routine_run_id")
    op.drop_index("ix_answer_book_entries_user_locked", table_name="answer_book_entries")
    op.drop_column("answer_book_entries", "is_locked")
    op.drop_table("routine_kill_switches")
    op.drop_index("ix_humanization_corpus_user", table_name="humanization_corpus")
    op.drop_table("humanization_corpus")
    op.drop_index("ix_application_submissions_run", table_name="application_submissions")
    op.drop_index("ix_application_submissions_submitted_at", table_name="application_submissions")
    op.drop_table("application_submissions")
    op.drop_index("ix_routine_runs_user_started", table_name="routine_runs")
    op.drop_table("routine_runs")
