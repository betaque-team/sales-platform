from pydantic import BaseModel, computed_field
from datetime import datetime
from uuid import UUID


class JobOut(BaseModel):
    id: UUID
    external_id: str
    company_id: UUID
    company_name: str | None = None
    title: str
    url: str
    platform: str
    location_raw: str
    remote_scope: str
    department: str
    employment_type: str | None = None
    salary_range: str | None = None
    geography_bucket: str
    matched_role: str
    role_cluster: str
    relevance_score: float
    status: str
    posted_at: datetime | None = None
    first_seen_at: datetime
    last_seen_at: datetime

    model_config = {"from_attributes": True}

    # Aliases to match frontend expectations
    @computed_field
    @property
    def source_platform(self) -> str:
        return self.platform

    @computed_field
    @property
    def location_restriction(self) -> str:
        return self.location_raw

    @computed_field
    @property
    def scraped_at(self) -> str:
        return self.first_seen_at.isoformat()

    @computed_field
    @property
    def created_at(self) -> str:
        return self.first_seen_at.isoformat()

    @computed_field
    @property
    def updated_at(self) -> str:
        return self.last_seen_at.isoformat()

    @computed_field
    @property
    def tags(self) -> list[str]:
        """Auto-generate tags from job metadata."""
        t = []
        if self.role_cluster:
            t.append(self.role_cluster)
        if self.geography_bucket:
            t.append(self.geography_bucket.replace("_", " "))
        if self.matched_role and self.matched_role != self.title:
            t.append(self.matched_role)
        return t


class JobDescriptionOut(BaseModel):
    id: UUID | None = None
    job_id: UUID | None = None
    raw_text: str = ""
    parsed_requirements: list[str] = []
    parsed_nice_to_have: list[str] = []
    parsed_tech_stack: list[str] = []

    model_config = {"from_attributes": True}


class JobStatusUpdate(BaseModel):
    status: str


class BulkActionRequest(BaseModel):
    job_ids: list[UUID]
    action: str  # accepted | rejected | archived
