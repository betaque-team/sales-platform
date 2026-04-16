from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from datetime import datetime
from uuid import UUID


# Regression finding 130: `comment: str = ""` and `tags: list[str] = []`
# had no caps — a reviewer (or a hand-crafted POST) could persist a 100
# KB comment or a 5000-entry tag array on every review, and the
# `reviews` table is on the hot path for `/analytics/rejection-reasons`
# and every dashboard render. Two matching bugs in one finding:
# **comment length** (`Review.comment` is `Text`, no DB cap — one
# reviewer flooding the column degrades all downstream analytics),
# and **tags shape** (`Review.tags` is `ARRAY(String)` unbounded —
# 5000 tags per row multiplies the rejection-reason histogram scan
# cost by 5000×). The third fix is **extra="forbid"** — pre-F130 the
# model silently dropped stale-schema fields like `reviewer_id` /
# `created_at` from clients written against an older version, which
# made "my frontend is broken" bugs hard to diagnose. Forbidding
# unknowns turns silent drops into loud 422s with the offending field
# name in the detail.
_COMMENT_MAX_LEN = 2000
_TAGS_MAX_COUNT = 20
_TAG_MAX_LEN = 40


# Per-tag StringConstraints — length cap + `min_length=1` so empty-
# string tags can't sneak past `list[str]`'s default (empty list is
# fine, empty strings as tags are not). `strip_whitespace=True` makes
# the input forgiving: `"  location  "` → `"location"`.
_ReviewTag = Annotated[
    str,
    StringConstraints(min_length=1, max_length=_TAG_MAX_LEN, strip_whitespace=True),
]


class ReviewCreate(BaseModel):
    # F130: reject stale-schema clients loudly (reviewer_id, created_at,
    # etc.) instead of silently dropping. Easier to diagnose "field X
    # isn't saving" when the server 422s with the field name than when
    # it silently ignores it.
    model_config = ConfigDict(extra="forbid")

    job_id: UUID
    # Regression finding 110: constrain to the three values the frontend
    # actually sends. The endpoint normalizes accept→accepted etc., so
    # accept any garbage string allowed arbitrary data into Review.decision.
    decision: Literal["accept", "reject", "skip"]
    # F130: cap comment at 2KB. Any legitimate review note fits easily;
    # 100KB payloads were purely DoS-shaped. Matches the answer_book.
    # question cap (F80) for cross-endpoint consistency.
    comment: str = Field(default="", max_length=_COMMENT_MAX_LEN)
    # F130: cap tags count + per-tag length. Max 20 tags per review is
    # ample (the UI has 6 preset pills); per-tag 40 chars matches the
    # rejection-vocabulary strings (`not_relevant`, `wrong_location`,
    # etc.) with headroom for future additions.
    tags: list[_ReviewTag] = Field(default_factory=list, max_length=_TAGS_MAX_COUNT)


class ReviewOut(BaseModel):
    id: UUID
    job_id: UUID
    reviewer_id: UUID
    reviewer_name: str | None = None
    decision: str
    comment: str
    tags: list[str]
    created_at: datetime

    model_config = {"from_attributes": True}
