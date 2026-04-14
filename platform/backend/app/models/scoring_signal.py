"""Scoring signal model for feedback-driven relevance adjustments."""

import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Float, Integer, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class ScoringSignal(Base):
    __tablename__ = "scoring_signals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    signal_type: Mapped[str] = mapped_column(String(50), nullable=False)  # tag_penalty, company_boost, etc.
    signal_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    weight: Mapped[float] = mapped_column(Float, default=0.0)
    decay_factor: Mapped[float] = mapped_column(Float, default=0.95)
    source_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
