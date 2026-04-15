from pydantic import BaseModel, Field
from datetime import datetime
from uuid import UUID


# Reasonable bounds for priority (UI uses 0..3 today; 100 leaves headroom without
# letting anyone push 10-digit values that break sort comparators) and notes
# (plenty for deal context, cheap to store, blocks a 100 KB+ payload DOS that
# was landing in prod — regression finding 15).
PIPELINE_MAX_PRIORITY = 100
PIPELINE_MAX_NOTES_LENGTH = 4000


class PipelineItemOut(BaseModel):
    id: UUID
    company_name: str | None = None
    company_website: str | None = None
    stage: str
    priority: int
    assigned_to: UUID | None
    resume_id: UUID | None = None
    applied_by: UUID | None = None
    applied_by_name: str | None = None
    resume_label: str | None = None
    enrichment_data: dict
    enriched_at: datetime | None
    accepted_jobs_count: int
    total_open_roles: int
    hiring_velocity: str
    notes: str
    created_at: datetime

    model_config = {"from_attributes": True}


class PipelineUpdate(BaseModel):
    stage: str | None = None
    priority: int | None = Field(default=None, ge=0, le=PIPELINE_MAX_PRIORITY)
    assigned_to: UUID | None = None
    resume_id: UUID | None = None
    applied_by: UUID | None = None
    notes: str | None = Field(default=None, max_length=PIPELINE_MAX_NOTES_LENGTH)
