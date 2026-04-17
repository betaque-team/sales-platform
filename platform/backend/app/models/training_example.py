"""ORM model for training_examples (F238).

One table for every captured (input, label) row. Six task types share
the table; the JSONB columns absorb shape divergence so adding a new
task type is a constant change in `app/utils/training_capture.py`,
not a migration.

Privacy: see migration u1p2q3r4s5t6 docstring for the full model.
TL;DR: no raw user_id, no email/phone/name in any text field, just
the per-environment-stable user_id_hash + scrubbed inputs.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


# Task-type constants. Importable from anywhere so writes go through
# one source of truth — typos at the call site (e.g. `"resumematch"`)
# are caught at import time rather than silently producing rows that
# the export endpoint can't query.
TASK_RESUME_MATCH = "resume_match"
TASK_ROLE_CLASSIFY = "role_classify"
TASK_COVER_LETTER_QUALITY = "cover_letter_quality"
TASK_INTERVIEW_PREP_QUALITY = "interview_prep_quality"
TASK_CUSTOMIZE_QUALITY = "customize_quality"
TASK_SEARCH_INTENT = "search_intent"

TASK_TYPE_VALUES = (
    TASK_RESUME_MATCH,
    TASK_ROLE_CLASSIFY,
    TASK_COVER_LETTER_QUALITY,
    TASK_INTERVIEW_PREP_QUALITY,
    TASK_CUSTOMIZE_QUALITY,
    TASK_SEARCH_INTENT,
)


class TrainingExample(Base):
    __tablename__ = "training_examples"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    task_type: Mapped[str] = mapped_column(String(40), nullable=False)
    # Free-text label class. NULL for multi-dimensional labels (e.g.
    # search_intent's clicked-ids array).
    label_class: Mapped[str | None] = mapped_column(String(64), nullable=True)
    inputs: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    labels: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # SHA-256(JWT_SECRET + user_id)[:32] — per-environment stable hash.
    # Never reversible without the JWT secret.
    user_id_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
