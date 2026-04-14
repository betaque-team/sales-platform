import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Boolean, DateTime, ARRAY
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class RoleRule(Base):
    __tablename__ = "role_rules"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    cluster: Mapped[str] = mapped_column(String(50), nullable=False)  # infra | security
    base_role: Mapped[str] = mapped_column(String(200), nullable=False)
    keywords: Mapped[list] = mapped_column(ARRAY(String), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
