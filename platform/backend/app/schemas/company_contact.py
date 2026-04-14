"""Pydantic schemas for company contacts and offices."""

from uuid import UUID
from datetime import datetime
from pydantic import BaseModel


class CompanyContactOut(BaseModel):
    id: UUID
    company_id: UUID
    first_name: str = ""
    last_name: str = ""
    title: str = ""
    role_category: str = "other"
    department: str = ""
    seniority: str = "other"
    email: str = ""
    email_status: str = "unverified"
    email_verified_at: datetime | None = None
    phone: str = ""
    linkedin_url: str = ""
    twitter_url: str = ""
    telegram_id: str = ""
    source: str = ""
    confidence_score: float = 0.0
    is_decision_maker: bool = False
    outreach_status: str = "not_contacted"
    outreach_note: str = ""
    last_outreach_at: datetime | None = None
    last_verified_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CompanyContactCreate(BaseModel):
    first_name: str = ""
    last_name: str = ""
    title: str = ""
    role_category: str = "other"
    department: str = ""
    seniority: str = "other"
    email: str = ""
    phone: str = ""
    linkedin_url: str = ""
    twitter_url: str = ""
    telegram_id: str = ""
    is_decision_maker: bool = False


class CompanyContactUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    title: str | None = None
    role_category: str | None = None
    department: str | None = None
    seniority: str | None = None
    email: str | None = None
    phone: str | None = None
    linkedin_url: str | None = None
    twitter_url: str | None = None
    telegram_id: str | None = None
    is_decision_maker: bool | None = None
    outreach_status: str | None = None
    outreach_note: str | None = None


class OutreachUpdate(BaseModel):
    outreach_status: str
    outreach_note: str = ""


class CompanyOfficeOut(BaseModel):
    id: UUID
    company_id: UUID
    label: str = ""
    address: str = ""
    city: str = ""
    state: str = ""
    country: str = ""
    is_headquarters: bool = False
    source: str = ""

    model_config = {"from_attributes": True}


class JobRelevantContact(BaseModel):
    contact: CompanyContactOut
    relevance_reason: str = ""
    relevance_score: float = 0.0
