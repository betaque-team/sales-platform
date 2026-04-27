"""Per-user manual queue / exclude list for the Apply Routine.

Why this exists
---------------
F257 — the routine's automatic ``top-to-apply`` picker uses
relevance + cluster + geography + cooldown filters, but the operator
has zero way to override the choice. Two real workflows need that:

1. **"I want the routine to apply to THIS specific job."**
   The user spots a great fit on the Jobs page, clicks "Add to Apply
   Routine," and the routine surfaces it on the next ``top-to-apply``
   call (boosted above the auto-picked rows).

2. **"Never queue this job for me."**
   The user already has a reason to skip a job (wrong stack, applied
   off-platform, vibes off) but doesn't want to manually un-pin it
   every time the routine re-suggests it. Mark ``intent='excluded'``
   and ``top-to-apply`` filters it out permanently for this user.

Schema decisions
----------------
* ``UNIQUE(user_id, job_id)`` — one row per (user, job). Re-pinning a
  job updates the existing row in place rather than stacking duplicates.
* ``intent`` is a free-string column instead of an enum so we can add
  states ("priority_high", "deferred") later without a migration. The
  Pydantic boundary enforces the allow-list.
* Both FKs are ``ON DELETE CASCADE`` so dropping a user or a job
  cleans up their routine_targets without an orphan-row sweep.
* ``note`` (text, default '') — optional reason the operator can leave
  for themselves ("applied via referral", "follow up next week").
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class RoutineTarget(Base):
    """One user-curated routine target (queued or excluded)."""

    __tablename__ = "routine_targets"
    __table_args__ = (
        UniqueConstraint("user_id", "job_id", name="uq_routine_targets_user_job"),
        # Hot path: ``WHERE user_id = :u AND intent = :i`` during
        # top-to-apply. The composite covers both halves.
        Index("ix_routine_targets_user_intent", "user_id", "intent"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    # Allow-list enforced at the Pydantic boundary (see
    # ``app.schemas.routine.RoutineTargetIntent``):
    #   "queued"   — surface this job on top-to-apply (boosted above auto-picks)
    #   "excluded" — never include this job in top-to-apply
    intent: Mapped[str] = mapped_column(String(20), nullable=False)
    # Free-form note from the operator. Empty string default so the
    # column is NOT NULL (no Python None checks at the API boundary).
    note: Mapped[str] = mapped_column(Text, default="", server_default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


# Allow-list constants — re-exported so the API + tests reference one place.
ROUTINE_TARGET_INTENTS: tuple[str, ...] = ("queued", "excluded")
