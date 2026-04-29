"""Work-time extension request — reviewer-initiated, admin-approved."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class WorkTimeExtensionRequest(Base):
    """One row per "I need N more minutes today" request.

    Lifecycle::

        pending  ─┬─►  approved  (admin sets approved_until + bumps the
                  │                requesting user's
                  │                ``work_window_override_until``)
                  └─►  denied    (admin records optional reason)

    ``approved_until`` is computed at approval time and frozen here so
    a subsequent re-approval (which shouldn't happen but the schema
    permits) can't silently extend the override further than the
    original decision.
    """

    __tablename__ = "work_time_extension_requests"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Capped 15..240 at the schema layer. Bounded so an approval is a
    # bounded decision — no "+8 hours" surprises.
    requested_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", server_default="")
    # 'pending' | 'approved' | 'denied'. String not Enum so a future
    # status (e.g. 'expired') can ship without a migration.
    status: Mapped[str] = mapped_column(
        String(16), default="pending", server_default="pending", nullable=False
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decision_note: Mapped[str] = mapped_column(Text, default="", server_default="")
    approved_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # No back_populates on User to avoid an import cycle — admins query
    # by user_id directly. ``requester`` populates the admin "pending
    # requests" list.
    requester = relationship("User", foreign_keys=[user_id], lazy="joined")
