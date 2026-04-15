"""Pydantic schemas for feedback / tickets."""

import json
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field, field_validator


VALID_CATEGORIES = {"bug", "feature_request", "improvement", "question"}
VALID_PRIORITIES = {"low", "medium", "high", "critical"}
VALID_STATUSES = {"open", "in_progress", "resolved", "closed"}

# Upper bound on long free-text fields. Bug reports with call stacks or
# feature requests with product requirements can run long, but prod was
# accepting a 1 MB `description` (see regression finding 25) — this caps
# each field at 8 KB, which is plenty of prose while blocking DB bloat.
_LONG_TEXT_MAX = 8000

# URL schemes allowed on screenshot_url. `javascript:` was accepted prior —
# that field is rendered as a link, so an unrestricted scheme is an XSS
# vector once someone clicks it.
_URL_SAFE_SCHEMES = ("http://", "https://", "/")


def _validate_optional_url(v: str | None) -> str | None:
    if v is None or v == "":
        return v
    stripped = v.strip()
    if len(stripped) > 2048:
        raise ValueError("URL too long (max 2048 chars)")
    low = stripped.lower()
    if not low.startswith(_URL_SAFE_SCHEMES):
        raise ValueError("URL must start with http://, https://, or / (relative)")
    return stripped


class FeedbackCreate(BaseModel):
    category: str = Field(..., description="bug | feature_request | improvement | question")
    priority: str = Field("medium", description="low | medium | high | critical")
    title: str = Field(..., min_length=5, max_length=200)
    description: str = Field(..., min_length=20, max_length=_LONG_TEXT_MAX)
    steps_to_reproduce: str | None = Field(default=None, max_length=_LONG_TEXT_MAX)
    expected_behavior: str | None = Field(default=None, max_length=_LONG_TEXT_MAX)
    actual_behavior: str | None = Field(default=None, max_length=_LONG_TEXT_MAX)
    use_case: str | None = Field(default=None, max_length=_LONG_TEXT_MAX)
    proposed_solution: str | None = Field(default=None, max_length=_LONG_TEXT_MAX)
    impact: str | None = Field(default=None, max_length=_LONG_TEXT_MAX)
    screenshot_url: str | None = Field(default=None, max_length=2048)

    @field_validator("screenshot_url")
    @classmethod
    def _check_screenshot_url(cls, v):
        return _validate_optional_url(v)


class FeedbackUpdate(BaseModel):
    status: str | None = None
    priority: str | None = None
    admin_notes: str | None = Field(default=None, max_length=_LONG_TEXT_MAX)


class FeedbackUserOut(BaseModel):
    id: UUID
    email: str
    name: str
    avatar_url: str

    class Config:
        from_attributes = True


class FeedbackOut(BaseModel):
    id: UUID
    user_id: UUID
    category: str
    priority: str
    status: str
    title: str
    description: str
    steps_to_reproduce: str | None
    expected_behavior: str | None
    actual_behavior: str | None
    use_case: str | None
    proposed_solution: str | None
    impact: str | None
    screenshot_url: str | None
    attachments: list | None = None
    admin_notes: str | None
    resolved_by: UUID | None
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None
    user: FeedbackUserOut | None = None
    resolver: FeedbackUserOut | None = None

    class Config:
        from_attributes = True

    @field_validator("attachments", mode="before")
    @classmethod
    def parse_attachments(cls, v):
        # DB stores attachments as a JSON-encoded string; coerce to list before validation.
        if v is None or v == "":
            return []
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                return parsed if isinstance(parsed, list) else []
            except (json.JSONDecodeError, TypeError):
                return []
        return []
