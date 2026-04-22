"""Application submission — what actually got sent to the ATS.

Solves a visibility gap noted during v6 planning: the platform
previously recorded Applications ("I applied to job X with resume Y")
but never the *content* of what was sent — the answers filled in,
the cover letter text, the confirmation string the ATS returned.

One row per successful apply (1:1 with ``applications.id``,
enforced by a UNIQUE at the DB). Dry-run flows also write this row,
with ``detected_issues=["dry_run"]`` and the routine handler
intentionally skipping the Application.status flip.

The UI reads this via ``GET /applications/{id}/submission`` and
renders the Submission Detail tab — answers, screenshots, cover
letter, confirmation text.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ApplicationSubmission(Base):
    __tablename__ = "application_submissions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,  # 1:1 with applications
    )
    routine_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("routine_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    job_url: Mapped[str] = mapped_column(Text, nullable=False)
    ats_platform: Mapped[str] = mapped_column(String(50), nullable=False)
    form_fingerprint_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # The raw field-name → value map as submitted to the ATS. PII is
    # redacted at write time (email/phone stored as {type, len}) — the
    # handler rejects SSN/DOB before reaching here, so we don't need
    # a column-level policy for those.
    payload_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    # list[{question, answer, source, source_ref_id, edit_distance}].
    # `source` values: 'manual_required' | 'learned' | 'generated'.
    # `source_ref_id` points to answer_book_entries.id when source is
    # 'manual_required' or 'learned'; None for 'generated'.
    answers_json: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    resume_version_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cover_letter_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    screenshot_keys: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    confirmation_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    detected_issues: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    # Frozen manual_required answer-book values as-sent. Lets the UI
    # show "140k was sent" even if the user later raises the stored
    # salary to 160k. {question_key: answer} shape.
    profile_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
