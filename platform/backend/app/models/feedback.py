"""Feedback / ticket model for sales team bug reports, feature requests, etc."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)

    # Type: bug | feature_request | improvement | question
    category: Mapped[str] = mapped_column(String(30), nullable=False)

    # Priority: low | medium | high | critical
    priority: Mapped[str] = mapped_column(String(20), default="medium")

    # Status: open | in_review | in_progress | resolved | closed
    status: Mapped[str] = mapped_column(String(20), default="open")

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # Structured fields from templates
    steps_to_reproduce: Mapped[str | None] = mapped_column(Text)
    expected_behavior: Mapped[str | None] = mapped_column(Text)
    actual_behavior: Mapped[str | None] = mapped_column(Text)
    use_case: Mapped[str | None] = mapped_column(Text)
    proposed_solution: Mapped[str | None] = mapped_column(Text)
    impact: Mapped[str | None] = mapped_column(Text)

    # Attachments (JSON array of {filename, original_name, size, content_type, uploaded_at})
    screenshot_url: Mapped[str | None] = mapped_column(String(1000))
    attachments: Mapped[str | None] = mapped_column(Text)  # JSON array

    # Admin response
    admin_notes: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))

    # Approval tracking
    approved_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approver_role: Mapped[str | None] = mapped_column(String(20))  # "admin" or "super_admin"

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationships
    user = relationship("User", foreign_keys=[user_id], lazy="selectin")
    resolver = relationship("User", foreign_keys=[resolved_by], lazy="selectin")
    approver = relationship("User", foreign_keys=[approved_by], lazy="selectin")
