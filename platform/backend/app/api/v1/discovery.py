"""Company discovery API endpoints."""

from uuid import UUID
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from pydantic import BaseModel

from app.database import get_db
from app.models.discovery import DiscoveryRun, DiscoveredCompany
from app.models.company import Company, CompanyATSBoard
from app.models.user import User
from app.api.deps import get_current_user, require_role
from app.schemas.discovery import DiscoveryRunOut, DiscoveredCompanyOut, DiscoveredCompanyUpdate


class BulkIdsRequest(BaseModel):
    ids: list[str]

router = APIRouter(prefix="/discovery", tags=["discovery"])


@router.get("/runs")
async def list_runs(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(DiscoveryRun)

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    query = query.order_by(DiscoveryRun.started_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)

    result = await db.execute(query)
    runs = result.scalars().all()
    items = [DiscoveryRunOut.model_validate(r) for r in runs]

    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    }


@router.post("/runs", response_model=DiscoveryRunOut, status_code=201)
async def trigger_discovery_run(
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Create a new discovery run record. The actual discovery is executed
    by the background worker that picks up runs with status='pending'."""
    run = DiscoveryRun(
        source="manual",
        status="pending",
        started_at=datetime.now(timezone.utc),
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return DiscoveryRunOut.model_validate(run)


@router.get("/companies")
async def list_discovered_companies(
    status: str | None = None,
    run_id: UUID | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(DiscoveredCompany)

    if status:
        query = query.where(DiscoveredCompany.status == status)
    if run_id:
        query = query.where(DiscoveredCompany.discovery_run_id == run_id)

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    query = query.order_by(DiscoveredCompany.created_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)

    result = await db.execute(query)
    companies = result.scalars().all()
    items = [DiscoveredCompanyOut.model_validate(c) for c in companies]

    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    }


@router.patch("/companies/{company_id}", response_model=DiscoveredCompanyOut)
async def update_discovered_company(
    company_id: UUID,
    body: DiscoveredCompanyUpdate,
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    if body.status not in ("added", "ignored"):
        raise HTTPException(status_code=400, detail="Status must be 'added' or 'ignored'")

    result = await db.execute(select(DiscoveredCompany).where(DiscoveredCompany.id == company_id))
    dc = result.scalar_one_or_none()
    if not dc:
        raise HTTPException(status_code=404, detail="Discovered company not found")

    dc.status = body.status
    await db.commit()
    await db.refresh(dc)
    return DiscoveredCompanyOut.model_validate(dc)


@router.post("/companies/{company_id}/import", status_code=201)
async def import_discovered_company(
    company_id: UUID,
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Import a discovered company into the main companies table."""
    result = await db.execute(select(DiscoveredCompany).where(DiscoveredCompany.id == company_id))
    dc = result.scalar_one_or_none()
    if not dc:
        raise HTTPException(status_code=404, detail="Discovered company not found")

    if dc.status == "added":
        raise HTTPException(status_code=409, detail="Company has already been imported")

    # Check if a company with the same slug already exists
    slug = dc.slug or dc.name.lower().replace(" ", "-")
    existing = await db.execute(select(Company).where(Company.slug == slug))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="A company with this slug already exists")

    company = Company(
        name=dc.name,
        slug=slug,
        website=dc.careers_url,
        is_target=False,
    )
    db.add(company)

    # If the discovered company came from an ATS platform, create the ATS board link
    if dc.platform and dc.slug:
        from app.models.company import CompanyATSBoard
        board = CompanyATSBoard(
            company_id=company.id,
            platform=dc.platform,
            slug=dc.slug,
            is_active=True,
        )
        db.add(board)

    dc.status = "added"
    await db.commit()
    await db.refresh(company)

    return {
        "ok": True,
        "company_id": str(company.id),
        "name": company.name,
        "slug": company.slug,
    }


@router.post("/companies/bulk-import")
async def bulk_import_discovered(
    body: BulkIdsRequest,
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Bulk import discovered companies into the main companies table."""
    imported = 0
    skipped = 0
    for dc_id in body.ids:
        result = await db.execute(select(DiscoveredCompany).where(DiscoveredCompany.id == dc_id))
        dc = result.scalar_one_or_none()
        if not dc or dc.status == "added":
            skipped += 1
            continue

        slug = dc.slug or dc.name.lower().replace(" ", "-")
        existing = await db.execute(select(Company).where(Company.slug == slug))
        if existing.scalar_one_or_none():
            dc.status = "added"
            skipped += 1
            continue

        company = Company(name=dc.name, slug=slug, website=dc.careers_url, is_target=False)
        db.add(company)

        if dc.platform and dc.slug:
            board = CompanyATSBoard(company_id=company.id, platform=dc.platform, slug=dc.slug, is_active=True)
            db.add(board)

        dc.status = "added"
        imported += 1

    await db.commit()
    return {"imported": imported, "skipped": skipped}


@router.post("/companies/bulk-ignore")
async def bulk_ignore_discovered(
    body: BulkIdsRequest,
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Bulk ignore discovered companies."""
    updated = 0
    for dc_id in body.ids:
        result = await db.execute(select(DiscoveredCompany).where(DiscoveredCompany.id == dc_id))
        dc = result.scalar_one_or_none()
        if dc and dc.status != "ignored":
            dc.status = "ignored"
            updated += 1
    await db.commit()
    return {"updated": updated}
