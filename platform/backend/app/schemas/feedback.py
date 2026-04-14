"""Pydantic schemas for feedback / tickets."""

from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field


VALID_CATEGORIES = {"bug", "feature_request", "improvement", "question"}
VALID_PRIORITIES = {"low", "medium", "high", "critical"}
VALID_STATUSES = {"open", "in_progress", "resolved", "closed"}


class FeedbackCreate(BaseModel):
    category: str = Field(..., description="bug | feature_request | improvement | question")
    priority: str = Field("medium", description="low | medium | high | critical")
    title: str = Field(..., min_length=5, max_length=200)
    description: str = Field(..., min_length=20)
    steps_to_reproduce: str | None = None
    expected_behavior: str | None = None
    actual_behavior: str | None = None
    use_case: str | None = None
    proposed_solution: str | None = None
    impact: str | None = None
    screenshot_url: str | None = None


class FeedbackUpdate(BaseModel):
    status: str | None = None
    priority: str | None = None
    admin_notes: str | None = None


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

    @classmethod
    def model_validate(cls, obj, **kwargs):
        # Parse attachments JSON string to list
        import json
        instance = super().model_validate(obj, **kwargs)
        if isinstance(instance.attachments, str):
            try:
                instance.attachments = json.loads(instance.attachments)
            except (json.JSONDecodeError, TypeError):
                instance.attachments = []
        elif instance.attachments is None:
            instance.attachments = []
        return instance
