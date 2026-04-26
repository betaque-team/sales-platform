import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey, JSON, Float, Integer, Text, Boolean, LargeBinary
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Resume(Base):
    __tablename__ = "resumes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    label: Mapped[str] = mapped_column(String(100), default="")  # Display name in persona switcher
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str] = mapped_column(String(10), nullable=False)  # pdf | docx
    text_content: Mapped[str] = mapped_column(Text, default="")
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    status: Mapped[str] = mapped_column(String(50), default="processing")  # processing | ready | error

    # Original file bytes (PDF or DOCX) for the in-app preview on the
    # Resume Score page. Up to 5 MB per row (enforced by the upload
    # handler). DEFERRED so list/active queries don't pull the bytes —
    # only the dedicated ``GET /resume/{id}/file`` endpoint touches this
    # column, where ``undefer(Resume.file_data)`` is invoked explicitly.
    # Nullable for backward compatibility with rows uploaded before the
    # b8c9d0e1f2g3 migration; those resumes fall back to a text-only
    # preview in the UI.
    file_data: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True, deferred=True
    )

    owner: Mapped["User"] = relationship(foreign_keys=[user_id])
    scores: Mapped[list["ResumeScore"]] = relationship(back_populates="resume", cascade="all, delete-orphan")


class ResumeScore(Base):
    __tablename__ = "resume_scores"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    resume_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)

    overall_score: Mapped[float] = mapped_column(Float, default=0.0)
    keyword_score: Mapped[float] = mapped_column(Float, default=0.0)
    role_match_score: Mapped[float] = mapped_column(Float, default=0.0)
    format_score: Mapped[float] = mapped_column(Float, default=0.0)

    matched_keywords: Mapped[dict] = mapped_column(JSON, default=list)
    missing_keywords: Mapped[dict] = mapped_column(JSON, default=list)
    suggestions: Mapped[dict] = mapped_column(JSON, default=list)

    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    resume: Mapped["Resume"] = relationship(back_populates="scores")
    job: Mapped["Job"] = relationship()


class AICustomizationLog(Base):
    __tablename__ = "ai_customization_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    # F236: cover-letter and interview-prep flows write rows with a
    # `job_id` but no `resume_id` snapshot — the user's active resume
    # is just referenced by id, not preserved. Made nullable in
    # migration s9n0o1p2q3r4 so all three feature flows can use the
    # same audit log + rate-limit table.
    resume_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("resumes.id", ondelete="CASCADE"), nullable=True
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=True
    )
    # F236: discriminator for which AI feature produced this log row.
    # One of `customize` / `cover_letter` / `interview_prep`. Indexed
    # alongside `(user_id, created_at)` so the per-user, per-feature
    # daily count used by the rate-limit check stays cheap. Default
    # `customize` matches the migration's server_default — existing
    # rows that predate the column are correctly attributed.
    feature: Mapped[str] = mapped_column(String(32), nullable=False, default="customize")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    # Regression finding 203: the default used to be `True`, which was a
    # silent foot-gun — any code path that forgot to pass `success=`
    # would accidentally count against the user's daily AI quota even
    # when the API call never happened (no api key, upstream 5xx,
    # timeout). Flipped to `False` so the quota-burning state is only
    # reachable by an explicit `success=True` after the Claude call
    # came back clean. Defense-in-depth alongside the handler-side
    # early-return in `resume.py:customize_resume_for_job`.
    success: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


# F236: feature-name constants used by the rate-limit + audit-log
# pattern across the three AI generation handlers. String, not Enum,
# because the column is `String(32)` for forward compatibility (a new
# feature can ship without a migration to add an enum value); but
# all writes go through these constants so we don't accidentally drift
# on capitalization or pluralization.
AI_FEATURE_CUSTOMIZE = "customize"
AI_FEATURE_COVER_LETTER = "cover_letter"
AI_FEATURE_INTERVIEW_PREP = "interview_prep"
AI_FEATURE_VALUES = (
    AI_FEATURE_CUSTOMIZE,
    AI_FEATURE_COVER_LETTER,
    AI_FEATURE_INTERVIEW_PREP,
)


# Forward references
from app.models.job import Job
from app.models.user import User
