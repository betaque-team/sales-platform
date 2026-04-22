"""Routine kill-switch — per-user feature halt flag.

Trivial table, one row per user, holds the poll-target for the
"stop the routine now" action. The routine polls this at the start
of every app iteration; if ``disabled=TRUE``, the run aborts within
~60 seconds regardless of what it was doing.

Why a separate table rather than a column on ``users``:
- ``users`` is hot (every request auth-checks against it). Writes
  to this flag happen during a routine run — we don't want to
  invalidate the user-row cache every toggle.
- Keeps auth queries narrow: user-row SELECT doesn't pull the
  kill-switch state unless explicitly joined.
- Easy to add admin-wide kill switches later (platform table or
  role-level) without reshaping the user model.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Boolean, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class RoutineKillSwitch(Base):
    __tablename__ = "routine_kill_switches"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    disabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
