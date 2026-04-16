from typing import Literal
from pydantic import BaseModel
from datetime import datetime
from uuid import UUID


class ReviewCreate(BaseModel):
    job_id: UUID
    # Regression finding 110: constrain to the three values the frontend
    # actually sends. The endpoint normalizes accept→accepted etc., so
    # accept any garbage string allowed arbitrary data into Review.decision.
    decision: Literal["accept", "reject", "skip"]
    comment: str = ""
    tags: list[str] = []


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
