"""CSV export API endpoints."""

import csv
import io
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.database import get_db
from app.models.job import Job
from app.models.company import Company
from app.models.company_contact import CompanyContact
from app.models.pipeline import PotentialClient
from app.models.user import User
from app.api.deps import get_current_user, require_role

router = APIRouter(prefix="/export", tags=["export"])

# Regression finding 61: bulk exports are a data-exfiltration surface —
# any logged-in viewer could previously download the full jobs / pipeline /
# contacts table (including internal outreach state and email_status).
# Gate on admin until product decides whether reviewers should also get
# export access; easier to loosen later than to claw data back after a
# compromised viewer account has already dumped it.
_EXPORT_ROLE_GUARD = require_role("admin")

JOB_CSV_COLUMNS = [
    "company", "title", "url", "platform", "remote_scope",
    "location_raw", "employment_type", "salary_range",
    "geography_bucket", "role_cluster", "matched_role",
    "relevance_score", "status", "posted_at", "first_seen_at",
]

PIPELINE_CSV_COLUMNS = [
    "company", "website", "stage", "priority",
    "accepted_jobs_count", "total_open_roles", "hiring_velocity",
    "notes", "created_at",
]


def _iter_csv(rows: list[list[str]], columns: list[str]):
    """Generator that yields CSV content line by line."""
    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow(columns)
    yield output.getvalue()
    output.seek(0)
    output.truncate(0)

    # Data rows
    for row in rows:
        writer.writerow(row)
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)


@router.get("/jobs")
async def export_jobs(
    status: str | None = None,
    platform: str | None = None,
    geography_bucket: str | None = None,
    role_cluster: str | None = None,
    user: User = Depends(_EXPORT_ROLE_GUARD),
    db: AsyncSession = Depends(get_db),
):
    query = select(Job).options(joinedload(Job.company))

    if status:
        query = query.where(Job.status == status)
    if platform:
        query = query.where(Job.platform == platform)
    if geography_bucket:
        query = query.where(Job.geography_bucket == geography_bucket)
    if role_cluster:
        query = query.where(Job.role_cluster == role_cluster)

    query = query.order_by(Job.first_seen_at.desc())

    result = await db.execute(query)
    jobs = result.unique().scalars().all()

    rows = []
    for j in jobs:
        company_name = j.company.name if j.company else ""
        rows.append([
            company_name,
            j.title,
            j.url,
            j.platform,
            j.remote_scope,
            j.location_raw,
            j.employment_type,
            j.salary_range,
            j.geography_bucket,
            j.role_cluster,
            j.matched_role,
            str(j.relevance_score),
            j.status,
            str(j.posted_at or ""),
            str(j.first_seen_at),
        ])

    return StreamingResponse(
        _iter_csv(rows, JOB_CSV_COLUMNS),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=jobs_export.csv"},
    )


@router.get("/pipeline")
async def export_pipeline(
    stage: str | None = None,
    user: User = Depends(_EXPORT_ROLE_GUARD),
    db: AsyncSession = Depends(get_db),
):
    query = select(PotentialClient).options(joinedload(PotentialClient.company))

    if stage:
        query = query.where(PotentialClient.stage == stage)

    query = query.order_by(PotentialClient.priority.desc(), PotentialClient.created_at.desc())

    result = await db.execute(query)
    clients = result.unique().scalars().all()

    rows = []
    for c in clients:
        company_name = c.company.name if c.company else ""
        company_website = c.company.website if c.company else ""
        rows.append([
            company_name,
            company_website,
            c.stage,
            str(c.priority),
            str(c.accepted_jobs_count),
            str(c.total_open_roles),
            c.hiring_velocity,
            c.notes,
            str(c.created_at),
        ])

    return StreamingResponse(
        _iter_csv(rows, PIPELINE_CSV_COLUMNS),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=pipeline_export.csv"},
    )


# Regression finding 62: `phone` and `telegram_id` were listed in the CSV
# but populated for 0/3756 rows — the enrichment pipeline has never written
# to either column on prod. Dropping them from the export (not the model)
# keeps the CSV honest for CRM/spreadsheet consumers. Restore both entries
# here once enrichment starts populating the values so the export matches
# reality again.
CONTACT_CSV_COLUMNS = [
    "company", "first_name", "last_name", "title", "role_category",
    "department", "seniority", "email", "email_status",
    "linkedin_url", "is_decision_maker",
    "outreach_status", "outreach_note", "last_outreach_at",
    "source", "confidence_score", "created_at",
]


@router.get("/contacts")
async def export_contacts(
    role_category: str | None = None,
    outreach_status: str | None = None,
    has_email: bool | None = None,
    is_decision_maker: bool | None = None,
    user: User = Depends(_EXPORT_ROLE_GUARD),
    db: AsyncSession = Depends(get_db),
):
    """Export all contacts as CSV with optional filters."""
    query = (
        select(CompanyContact, Company.name.label("company_name"))
        .join(Company, CompanyContact.company_id == Company.id)
    )

    if role_category:
        query = query.where(CompanyContact.role_category == role_category)
    if outreach_status:
        query = query.where(CompanyContact.outreach_status == outreach_status)
    if has_email is True:
        query = query.where(CompanyContact.email != "")
    elif has_email is False:
        query = query.where(CompanyContact.email == "")
    if is_decision_maker is not None:
        query = query.where(CompanyContact.is_decision_maker == is_decision_maker)

    query = query.order_by(Company.name.asc(), CompanyContact.last_name.asc())

    result = await db.execute(query)
    rows = []
    for contact, company_name in result:
        # Row order must stay in lockstep with CONTACT_CSV_COLUMNS above.
        # `phone` and `telegram_id` are intentionally omitted — see Finding 62.
        rows.append([
            company_name,
            contact.first_name,
            contact.last_name,
            contact.title,
            contact.role_category,
            contact.department,
            contact.seniority,
            contact.email,
            contact.email_status,
            contact.linkedin_url,
            str(contact.is_decision_maker),
            contact.outreach_status,
            contact.outreach_note,
            str(contact.last_outreach_at or ""),
            contact.source,
            str(contact.confidence_score),
            str(contact.created_at),
        ])

    return StreamingResponse(
        _iter_csv(rows, CONTACT_CSV_COLUMNS),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=contacts_export.csv"},
    )
