import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey, JSON, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (
        UniqueConstraint("user_id", "job_id", name="uq_application_user_job"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    resume_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="prepared")  # prepared, submitted, applied, interview, offer, rejected, withdrawn
    # apply_method values:
    #   api_submit | manual_copy | career_page : existing pre-routine lanes
    #   claude_routine                         : submitted by the MCP-Chrome
    #                                            routine (v6 "Claude Routine
    #                                            Apply" feature). Keeps the
    #                                            Applications page filterable
    #                                            by "how did we get here".
    apply_method: Mapped[str] = mapped_column(String(50), default="manual_copy")
    prepared_answers: Mapped[dict] = mapped_column(JSON, default=list)  # Snapshot of Q&A
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    platform_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Feature C — apply-time snapshot. Captures what was actually used
    # at submit-time so the Applications page can show "what we sent"
    # even after the underlying resume is edited or re-scored. Three
    # columns, all nullable (legacy rows won't have snapshots):
    #   * applied_resume_text — resume body used (raw or AI-customized).
    #   * applied_resume_score_snapshot — frozen ResumeScore components.
    #   * ai_customization_log_id — link to the Claude run, if any.
    applied_resume_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    applied_resume_score_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Soft reference to ai_customization_logs.id — intentionally NOT a
    # DB-level ForeignKey. The `ai_customization_logs` table has no
    # create-migration in this repo (declared in the model / env.py but
    # provisioned outside alembic), so a FK here would break CI's
    # `alembic upgrade head` on a fresh database. The app-level code
    # still validates the reference at write time in reviews.apply.
    ai_customization_log_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    # Provenance — mirrors Job.submission_source (Feature A) so the
    # Applications page can show how each app was created. Values:
    #   manual_prepare : via POST /applications/prepare
    #   review_queue   : via POST /reviews/apply
    #   routine        : via the Claude Routine Apply flow (v6 —
    #                    POST /applications/{id}/confirm-submitted).
    submission_source: Mapped[str] = mapped_column(String(30), default="manual_prepare", nullable=False)
    # Links the application to its originating routine run when
    # submission_source="routine". Nullable + ON DELETE SET NULL so
    # cleaning up a run doesn't cascade-delete the applications.
    routine_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("routine_runs.id", ondelete="SET NULL"),
        nullable=True,
    )

    job: Mapped["Job"] = relationship()
    resume: Mapped["Resume"] = relationship()


# Forward references
from app.models.job import Job
from app.models.resume import Resume
