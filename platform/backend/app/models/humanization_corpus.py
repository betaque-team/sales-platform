"""Humanization corpus — draft→final answer pairs for style-matching.

When the routine generates an answer and the user approves it (with
or without edits), we store (draft_text, final_text) so the next
generation pass can few-shot from these examples. The goal is for
the model's output to converge on the user's own voice over time.

Only `source="generated"` answers populate this table — `learned` and
`manual_required` answers are either already in the answer book or
are identity facts the model should never regenerate.

Style-match loader pulls the last N rows where edit_distance>10
(small edits are noise; we want examples where the user meaningfully
rewrote the draft).
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Text, Integer, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class HumanizationCorpus(Base):
    __tablename__ = "humanization_corpus"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("applications.id", ondelete="SET NULL"),
        nullable=True,
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    draft_text: Mapped[str] = mapped_column(Text, nullable=False)
    final_text: Mapped[str] = mapped_column(Text, nullable=False)
    edit_distance: Mapped[int] = mapped_column(Integer, nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    promoted_to_answer_book: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
