"""Pydantic schemas for answer-book CRUD.

Regression finding 80: `POST /api/v1/answer-book` and
`PATCH /api/v1/answer-book/{entry_id}` declared `body: dict`, so:
  - `question` and `answer` were both unbounded `Text` columns
    (see `models/answer_book.py`). A multi-megabyte POST succeeded
    and inflated every subsequent `GET /answer-book` response
    (paginated at 50, each row shipped in full).
  - `source` accepted any ≤50-char string, so a client could spoof
    `source="admin_default"` or `source="resume_extracted"` and the
    UI would render a badge claiming that provenance.
  - Same failure-mode class as Finding #25 (feedback 1 MB description)
    and the recent #79 credentials fix.

This schema closes the gap. `source` is removed from the input shape
entirely — the frontend never sends it and the server controls it
based on the endpoint (`"manual"` for POST, `"resume_extracted"` for
the import-from-resume endpoint, `"archived"` for the soft-delete).
Keeping it server-controlled eliminates the spoofing surface without
needing an allowlist.
"""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


# Keep in lockstep with `api/v1/answer_book.py::VALID_CATEGORIES`.
ANSWER_CATEGORY_LITERALS = Literal[
    "personal_info", "work_auth", "experience", "skills", "preferences", "custom",
]

# Cap the free-text fields. 2 KB question handles "What is the most
# challenging bug you've solved — please describe the context, the
# investigation, the fix, and the outcome (up to 5 paragraphs)?" with
# headroom. 8 KB answer matches the `_LONG_TEXT_MAX` used in
# `schemas/feedback.py` for equivalent long-form prose fields.
_QUESTION_MAX = 2000
_ANSWER_MAX = 8000


class AnswerCreate(BaseModel):
    """Body of POST /api/v1/answer-book."""

    category: ANSWER_CATEGORY_LITERALS
    question: str = Field(..., min_length=1, max_length=_QUESTION_MAX)
    answer: str = Field(default="", max_length=_ANSWER_MAX)
    # `null` / omitted → base entry (shared across resumes); a UUID →
    # resume-specific override.
    resume_id: UUID | None = None


class AnswerUpdate(BaseModel):
    """Body of PATCH /api/v1/answer-book/{entry_id}.

    All fields optional so the caller can update one attribute in
    isolation. When `question` is updated, the endpoint also
    recomputes `question_key` via `normalize_question_key`.
    """

    category: ANSWER_CATEGORY_LITERALS | None = None
    question: str | None = Field(default=None, min_length=1, max_length=_QUESTION_MAX)
    answer: str | None = Field(default=None, max_length=_ANSWER_MAX)
