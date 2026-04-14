import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey, JSON, Float, Integer, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    external_id: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    title_normalized: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    location_raw: Mapped[str] = mapped_column(String(500), default="")
    remote_scope: Mapped[str] = mapped_column(String(500), default="")
    department: Mapped[str] = mapped_column(String(300), default="")
    employment_type: Mapped[str] = mapped_column(String(100), default="")
    salary_range: Mapped[str] = mapped_column(String(200), default="")

    # Classification
    geography_bucket: Mapped[str] = mapped_column(String(50), default="")  # global_remote | usa_only | uae_only
    matched_role: Mapped[str] = mapped_column(String(200), default="")
    role_cluster: Mapped[str] = mapped_column(String(50), default="")  # infra | security

    # Scoring
    relevance_score: Mapped[float] = mapped_column(Float, default=0.0)

    # Workflow status
    status: Mapped[str] = mapped_column(String(50), default="new")  # new | under_review | accepted | rejected | expired | archived

    # Dates
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Raw data
    raw_json: Mapped[dict] = mapped_column(JSON, default=dict)

    # Relationships
    company: Mapped["Company"] = relationship()
    description: Mapped["JobDescription | None"] = relationship(back_populates="job", uselist=False, cascade="all, delete-orphan")
    reviews: Mapped[list["Review"]] = relationship(back_populates="job", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_jobs_status", "status"),
        Index("idx_jobs_company", "company_id"),
        Index("idx_jobs_platform", "platform"),
        Index("idx_jobs_geography", "geography_bucket"),
        Index("idx_jobs_score", relevance_score.desc()),
        Index("idx_jobs_first_seen", "first_seen_at"),
    )


class JobDescription(Base):
    __tablename__ = "job_descriptions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), unique=True, nullable=False)
    html_content: Mapped[str] = mapped_column(default="")
    text_content: Mapped[str] = mapped_column(default="")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    word_count: Mapped[int] = mapped_column(Integer, default=0)

    job: Mapped["Job"] = relationship(back_populates="description")


# Forward references
from app.models.company import Company
from app.models.review import Review
