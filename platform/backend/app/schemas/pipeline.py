from pydantic import BaseModel
from datetime import datetime
from uuid import UUID


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
    priority: int | None = None
    assigned_to: UUID | None = None
    resume_id: UUID | None = None
    applied_by: UUID | None = None
    notes: str | None = None
