"""Pydantic schemas for Discovery endpoints."""

from pydantic import BaseModel
from datetime import datetime
from uuid import UUID


class DiscoveryRunOut(BaseModel):
    id: UUID
    source: str
    status: str
    started_at: datetime
    completed_at: datetime | None
    companies_found: int
    new_companies: int

    model_config = {"from_attributes": True}


class DiscoveredCompanyOut(BaseModel):
    id: UUID
    discovery_run_id: UUID
    name: str
    platform: str
    slug: str
    careers_url: str
    status: str
    relevance_hint: str
    created_at: datetime

    model_config = {"from_attributes": True}


class DiscoveredCompanyUpdate(BaseModel):
    status: str  # added | ignored
