from pydantic import BaseModel
from datetime import datetime
from uuid import UUID


class ReviewCreate(BaseModel):
    job_id: UUID
    decision: str  # accepted | rejected | skipped
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
