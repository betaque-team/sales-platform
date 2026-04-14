"""Configurable role clusters for relevant job classification."""

import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Boolean, DateTime, Text, Integer
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class RoleClusterConfig(Base):
    """Admin-configurable role clusters that define what counts as 'relevant'."""
    __tablename__ = "role_cluster_configs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)  # e.g. "infra", "security", "data"
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)  # e.g. "Infrastructure / DevOps"
    is_relevant: Mapped[bool] = mapped_column(Boolean, default=True)  # whether included in "relevant" filter
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    keywords: Mapped[str] = mapped_column(Text, default="")  # comma-separated matching keywords
    approved_roles: Mapped[str] = mapped_column(Text, default="")  # comma-separated approved role titles
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
