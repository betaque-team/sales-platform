"""Pydantic schemas for Company and ATS Board endpoints."""

from pydantic import BaseModel, computed_field
from datetime import datetime
from uuid import UUID

# ATS board URL patterns
ATS_URL_PATTERNS = {
    "greenhouse": "https://boards.greenhouse.io/{slug}",
    "lever": "https://jobs.lever.co/{slug}",
    "ashby": "https://jobs.ashbyhq.com/{slug}",
    "workable": "https://apply.workable.com/{slug}",
    "bamboohr": "https://{slug}.bamboohr.com/careers",
    "himalayas": "https://himalayas.app/companies/{slug}/jobs",
    "wellfound": "https://wellfound.com/company/{slug}/jobs",
    "jobvite": "https://jobs.jobvite.com/{slug}",
    "smartrecruiters": "https://jobs.smartrecruiters.com/{slug}",
    "recruitee": "https://{slug}.recruitee.com",
    "linkedin": "https://www.linkedin.com/company/{slug}/jobs",
}


class ATSBoardOut(BaseModel):
    id: UUID
    company_id: UUID
    platform: str
    slug: str
    is_active: bool
    last_scanned_at: datetime | None = None

    model_config = {"from_attributes": True}

    @computed_field
    @property
    def board_url(self) -> str:
        pattern = ATS_URL_PATTERNS.get(self.platform, "")
        return pattern.format(slug=self.slug) if pattern else ""


class ATSBoardCreate(BaseModel):
    platform: str
    slug: str
    is_active: bool = True


class CompanyOut(BaseModel):
    id: UUID
    name: str
    slug: str
    website: str | None = ""
    logo_url: str = ""
    industry: str = ""
    employee_count: str = ""
    funding_stage: str = ""
    headquarters: str = ""
    description: str = ""
    is_target: bool = False
    tags: list[str] = []
    metadata_json: dict = {}
    domain: str = ""
    founded_year: int | None = None
    total_funding: str = ""
    linkedin_url: str = ""
    twitter_url: str = ""
    tech_stack: list[str] = []
    enrichment_status: str = "pending"
    enriched_at: datetime | None = None
    funded_at: datetime | None = None
    funding_news_url: str = ""
    created_at: datetime
    updated_at: datetime
    ats_boards: list[ATSBoardOut] = []
    job_count: int = 0
    # Regression finding 98: `relevant_job_count` was referenced on the
    # frontend (CompaniesPage renders `{company.relevant_job_count ?? "?"}`)
    # but was never populated or declared in the schema — so the list
    # endpoint returned undefined for every row and the UI showed "?"
    # across the table. Populated in `companies.py::list_companies` via
    # a correlated subquery over `Job.role_cluster IN relevant_clusters`.
    relevant_job_count: int = 0
    accepted_count: int = 0
    contact_count: int = 0

    model_config = {"from_attributes": True}


from app.schemas.company_contact import CompanyContactOut, CompanyOfficeOut


class CompanyDetailOut(CompanyOut):
    """Extended company schema with contacts and offices."""
    contacts: list[CompanyContactOut] = []
    offices: list[CompanyOfficeOut] = []
    actively_hiring: bool = False
    hiring_velocity: str = ""
    total_open_roles: int = 0
    enrichment_error: str = ""


class CompanyCreate(BaseModel):
    name: str
    slug: str
    website: str = ""
    logo_url: str = ""
    industry: str = ""
    employee_count: str = ""
    funding_stage: str = ""
    headquarters: str = ""
    description: str = ""
    is_target: bool = False
    tags: list[str] = []
    metadata_json: dict = {}


class CompanyUpdate(BaseModel):
    name: str | None = None
    slug: str | None = None
    website: str | None = None
    logo_url: str | None = None
    industry: str | None = None
    employee_count: str | None = None
    funding_stage: str | None = None
    headquarters: str | None = None
    description: str | None = None
    is_target: bool | None = None
    tags: list[str] | None = None
    metadata_json: dict | None = None
