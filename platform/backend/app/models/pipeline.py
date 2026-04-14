import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Integer, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class PotentialClient(Base):
    __tablename__ = "potential_clients"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), unique=True, nullable=False)
    stage: Mapped[str] = mapped_column(String(50), default="new_lead")  # new_lead | researching | qualified | outreach | engaged | disqualified
    priority: Mapped[int] = mapped_column(Integer, default=0)
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    resume_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("resumes.id"), nullable=True)
    applied_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    # Enrichment
    enrichment_data: Mapped[dict] = mapped_column(JSON, default=dict)
    enriched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Metrics
    accepted_jobs_count: Mapped[int] = mapped_column(Integer, default=0)
    total_open_roles: Mapped[int] = mapped_column(Integer, default=0)
    hiring_velocity: Mapped[str] = mapped_column(String(50), default="")

    notes: Mapped[str] = mapped_column(default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    company: Mapped["Company"] = relationship()
    assignee: Mapped["User | None"] = relationship(foreign_keys=[assigned_to])
    applicant: Mapped["User | None"] = relationship(foreign_keys=[applied_by])
    resume: Mapped["Resume | None"] = relationship()


from app.models.company import Company
from app.models.user import User
from app.models.resume import Resume
