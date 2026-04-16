"""Alert configuration model for job notifications."""

import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey, Boolean, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class AlertConfig(Base):
    __tablename__ = "alert_configs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    channel: Mapped[str] = mapped_column(String(50), default="google_chat")  # google_chat | slack | email
    webhook_url: Mapped[str] = mapped_column(Text, nullable=False)
    min_relevance_score: Mapped[int] = mapped_column(Integer, default=70)
    role_clusters: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array, null = all
    geography_filter: Mapped[str | None] = mapped_column(String(50), nullable=True)  # null = all
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
