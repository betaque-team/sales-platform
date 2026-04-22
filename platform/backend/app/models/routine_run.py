"""Routine run — one row per invocation of the automated-apply flow.

A run ties together all applications the Claude routine attempts in
one session — whether that's a single manual trial, a scheduled batch,
or a dry-run. The user reads runs back through ``/routine/runs``
to see what happened and why any apps were skipped.

Lifecycle:
  status="running" → submit: applications_submitted++
                   → skip: applications_skipped.append
                   → detection: detection_incidents.append + abort
                   → kill-switch flip: kill_switch_triggered=True + abort
                   → completion: status="complete", ended_at=now()

Ownership: ``user_id`` scopes every query; no cross-user reads.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, ForeignKey, Integer, Boolean, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


# Allowed mode values. Enforced at the Pydantic schema boundary; the
# DB column is String(20) with no CHECK (see migration rationale).
ROUTINE_MODES = ("dry_run", "live", "single_trial")
ROUTINE_STATUSES = ("running", "complete", "aborted")


class RoutineRun(Base):
    __tablename__ = "routine_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    applications_attempted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    applications_submitted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # JSONB list of {job_id: str, reason: str}. Native Postgres JSONB
    # lets us query by reason later if we need "how often did we skip
    # for missing_required?" analytics.
    applications_skipped: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    detection_incidents: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="running", nullable=False)
    kill_switch_triggered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
