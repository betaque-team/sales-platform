from __future__ import annotations

import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Boolean, DateTime, ForeignKey, JSON, ARRAY, Integer, BigInteger, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    slug: Mapped[str] = mapped_column(String(300), unique=True, nullable=False)
    website: Mapped[str] = mapped_column(String(500), default="")
    logo_url: Mapped[str] = mapped_column(String(500), default="")
    industry: Mapped[str] = mapped_column(String(200), default="")
    employee_count: Mapped[str] = mapped_column(String(50), default="")
    funding_stage: Mapped[str] = mapped_column(String(100), default="")
    headquarters: Mapped[str] = mapped_column(String(300), default="")
    description: Mapped[str] = mapped_column(default="")
    is_target: Mapped[bool] = mapped_column(Boolean, default=False)
    tags: Mapped[list] = mapped_column(ARRAY(String), default=list)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)

    # Enrichment fields
    domain: Mapped[str] = mapped_column(String(255), default="")
    founded_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_funding: Mapped[str] = mapped_column(String(100), default="")
    total_funding_usd: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    linkedin_url: Mapped[str] = mapped_column(String(500), default="")
    twitter_url: Mapped[str] = mapped_column(String(500), default="")
    tech_stack: Mapped[list] = mapped_column(ARRAY(String), default=list)
    enrichment_status: Mapped[str] = mapped_column(String(50), default="pending")
    enriched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    enrichment_error: Mapped[str] = mapped_column(Text, default="")

    # Funding signal
    funded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    funding_news_url: Mapped[str] = mapped_column(String(1000), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    ats_boards: Mapped[list["CompanyATSBoard"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    contacts: Mapped[list["CompanyContact"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    offices: Mapped[list["CompanyOffice"]] = relationship(back_populates="company", cascade="all, delete-orphan")


class CompanyATSBoard(Base):
    __tablename__ = "company_ats_boards"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    slug: Mapped[str] = mapped_column(String(300), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Regression finding 7 (stale-slug auto-deactivation half): these two
    # columns drive the "after N consecutive clean-zero scans, flip
    # is_active=False" behavior in `workers/tasks/scan_task.py`. The
    # finding reported BambooHR/Jobvite/Recruitee boards that return 0
    # jobs but stay marked active, inflating the "active boards" count
    # on the Monitoring dashboard and wasting per-scan HTTP budget.
    #
    # Semantics:
    #   - `consecutive_zero_scans` is reset to 0 on any scan that
    #     returns >=1 job. It is left unchanged on a scan that raised
    #     (fetcher error / Cloudflare 403 / transient network) so a
    #     blip doesn't reset a genuinely-dead board's progress toward
    #     deactivation. It is incremented only on clean empty returns.
    #   - `deactivated_reason` is set when `is_active` flips to False
    #     via this path (vs. manual admin toggle) so ops can
    #     distinguish auto-deactivated stale slugs from manually-
    #     paused ones. Empty string means "never auto-deactivated".
    consecutive_zero_scans: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    deactivated_reason: Mapped[str] = mapped_column(String(200), default="", nullable=False)

    company: Mapped["Company"] = relationship(back_populates="ats_boards")
