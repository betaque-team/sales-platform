import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey, Text, Integer, Boolean, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


# Allowed `source` values. Server-controlled — the Pydantic schemas
# don't expose `source` as an input field (see schemas/answer_book.py).
# - 'manual'            : user-typed via POST /answer-book
# - 'resume_extracted'  : pulled from resume text at upload time
# - 'admin_default'     : seeded by an admin for org-wide defaults
# - 'archived'          : soft-deleted via DELETE endpoint
# - 'manual_required'   : routine-apply seeded identity/EEO entries
#                         (salary, notice, work-auth, demographic).
#                         Always created with is_locked=True. Routine
#                         READS these; never regenerates or writes.
# - 'learned'           : captured from a prior application's novel
#                         Q&A (via /applications/{id}/promote-answer
#                         or auto-promotion after positive outcome).
#                         Routine prefers these over LLM generation
#                         but can overwrite them from better captures.
# - 'generated'         : placeholder — we don't actually persist
#                         'generated' answers as answer-book rows; they
#                         live in humanization_corpus until promoted.
ANSWER_SOURCES = (
    "manual", "resume_extracted", "admin_default", "archived",
    "manual_required", "learned", "generated",
)


class AnswerBookEntry(Base):
    __tablename__ = "answer_book_entries"
    __table_args__ = (
        UniqueConstraint("user_id", "resume_id", "question_key", name="uq_answer_user_resume_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    resume_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("resumes.id", ondelete="CASCADE"), nullable=True)  # null = shared/base entry
    category: Mapped[str] = mapped_column(String(50), nullable=False)  # personal_info, work_auth, experience, skills, preferences, custom
    question: Mapped[str] = mapped_column(Text, nullable=False)
    question_key: Mapped[str] = mapped_column(String(255), nullable=False)  # Normalized key for matching
    answer: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(50), default="manual")  # see ANSWER_SOURCES
    # Routine-apply lock. When TRUE:
    #   - PATCH /answer-book/{id} may update `answer` only (not question/category)
    #   - DELETE /answer-book/{id} is rejected
    #   - POST /answer-book with this question_key is rejected
    # Only the /answer-book/seed-required endpoint may create rows with
    # is_locked=True, and that endpoint is idempotent (safe to re-call).
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
