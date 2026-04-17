"""ORM models for the AI Intelligence feature (F237).

Two tables, distinct audiences:

- ``UserInsight``: per-user actionable insights produced twice a week.
  Surfaced via ``GET /api/v1/insights/me`` (latest run for current
  user) and the new Insights sidebar page. Each row is one user's
  full insight set for one beat-task run.

- ``ProductInsight``: admin-facing platform-wide observations.
  Surfaced via ``GET /api/v1/insights/product`` and a new Monitoring
  tile. Each row is ONE insight (not one bundle); the action-tracking
  columns let admins mark items actioned/dismissed and feed those
  decisions back into the next prompt run.

Schema mirrored exactly from migration ``t0o1p2q3r4s5``.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class UserInsight(Base):
    __tablename__ = "user_insights"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Run-grouping UUID — every per-user row from one beat task shares
    # this so ops can rollback or diff a single run.
    generation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    # Array of {title, body, severity, action_link?}. JSONB so the
    # output schema can iterate without a migration per change.
    insights: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # Snapshot of inputs the LLM saw — kept for debugging and for
    # comparing prompt-version output on the same input set.
    input_signals: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class ProductInsight(Base):
    __tablename__ = "product_insights"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    generation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # Coarse bucket so the admin tile can group / filter.
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="other")
    # low / medium / high — drives sort priority on the admin tile.
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="medium")
    input_signals: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    # Action-tracking columns. NULL = pending review.
    actioned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    actioned_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # actioned | dismissed | duplicate. NULL = pending.
    actioned_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Free-text note. Fed back into the next prompt run as context so
    # the LLM can score "did the metric move after we shipped X?".
    actioned_note: Mapped[str | None] = mapped_column(Text, nullable=True)
