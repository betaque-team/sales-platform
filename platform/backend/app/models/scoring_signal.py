"""Scoring signal model for feedback-driven relevance adjustments.

Regression finding 89 — per-user isolation
-------------------------------------------
The original schema had a globally-unique `signal_key` column, so
every reviewer's feedback accumulated into a single shared bucket:
reviewer A's "reject Acme" signal dragged reviewer B's view of Acme
down too, and there was no audit trail of which reviewer contributed
which signal.

Layer 1 (this commit) adds `user_id` (nullable FK to users.id) and
moves the uniqueness constraint from `signal_key` alone to the
composite `(user_id, signal_key)` — so each reviewer owns their own
row per signal_key. Legacy pre-fix rows keep `user_id = NULL` and
participate in the shared pool (the nightly `rescore_jobs` batch
still sums over everything, preserving existing behavior).

Layer 2 (separate commit) will push per-user adjustment to
query-time so the midnight step-change goes away and per-user
scores are truly isolated end-to-end. The column below is the
foundation for that.
"""

import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Float, Integer, DateTime, ForeignKey, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class ScoringSignal(Base):
    __tablename__ = "scoring_signals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Regression finding 89: per-user scoping. NULL = legacy shared
    # pool (pre-fix rows). The upsert path going forward always
    # populates this with the reviewer's user_id so new feedback
    # stays isolated to the reviewer who produced it.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    signal_type: Mapped[str] = mapped_column(String(50), nullable=False)  # tag_penalty, company_boost, etc.
    # `signal_key` is no longer unique on its own — the composite
    # `(user_id, signal_key)` unique constraint below replaces it.
    # Keep the index for fast lookup by key when iterating per-user
    # or over the legacy pool.
    signal_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    weight: Mapped[float] = mapped_column(Float, default=0.0)
    decay_factor: Mapped[float] = mapped_column(Float, default=0.95)
    source_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        # Composite uniqueness: each user has at most one row per
        # signal_key, and there is a single NULL-user legacy row per
        # signal_key for the pre-fix data. Postgres treats NULL as
        # distinct in unique constraints, so in practice there can be
        # multiple legacy rows with the same key — but the migration
        # collapses legacy rows 1:1 with the pre-fix unique constraint
        # so this is consistent.
        UniqueConstraint("user_id", "signal_key", name="uq_scoring_signals_user_key"),
    )
