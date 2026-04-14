import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey, Text, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


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
    source: Mapped[str] = mapped_column(String(50), default="manual")  # manual, resume_extracted, admin_default
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
