"""Company management API endpoints."""

from uuid import UUID
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select, func, or_, case
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.database import get_db
from app.models.company import Company, CompanyATSBoard
from app.models.company_contact import CompanyContact, JobContactRelevance
from app.models.company_office import CompanyOffice
from app.models.job import Job
from app.models.user import User
from app.api.deps import get_current_user, require_role
from app.schemas.company import (
    CompanyOut, CompanyCreate, CompanyUpdate, CompanyDetailOut,
    ATSBoardOut, ATSBoardCreate,
)
from app.schemas.company_contact import (
    CompanyContactOut, CompanyContactCreate, CompanyContactUpdate,
    CompanyOfficeOut, JobRelevantContact, OutreachUpdate,
)
from app.schemas.job import JobOut
from app.utils.sql import escape_like

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("/scores")
async def company_scores(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get company scores for filtering — based on relevant job count, remote coverage, avg relevance."""
    from sqlalchemy import Float as SAFloat
    from sqlalchemy.sql.expression import cast

    # Subquery: for each company, count relevant jobs, global remote jobs, avg score
    scores_q = (
        select(
            Job.company_id,
            func.count(Job.id).label("total_jobs"),
            func.sum(case((Job.role_cluster.in_(["infra", "security"]), 1), else_=0)).label("relevant_jobs"),
            func.sum(case((Job.geography_bucket == "global_remote", 1), else_=0)).label("remote_jobs"),
            func.avg(case((Job.relevance_score > 0, Job.relevance_score), else_=None)).label("avg_score"),
        )
        .group_by(Job.company_id)
        .subquery()
    )

    result = await db.execute(
        select(
            Company.id, Company.name, Company.is_target,
            scores_q.c.total_jobs,
            scores_q.c.relevant_jobs,
            scores_q.c.remote_jobs,
            scores_q.c.avg_score,
        )
        .outerjoin(scores_q, Company.id == scores_q.c.company_id)
        .where(scores_q.c.relevant_jobs > 0)
        .order_by(scores_q.c.relevant_jobs.desc())
        .limit(100)
    )

    items = []
    for row in result:
        relevant = int(row.relevant_jobs or 0)
        remote = int(row.remote_jobs or 0)
        avg_score = float(row.avg_score or 0)
        is_target = row.is_target

        # Company score: weighted combination
        # 40% relevant job count (capped at 20), 25% avg relevance, 20% remote ratio, 15% target bonus
        job_component = min(relevant / 20, 1.0) * 40
        score_component = (avg_score / 100) * 25
        remote_ratio = (remote / max(relevant, 1)) * 20
        target_bonus = 15 if is_target else 0
        company_score = round(job_component + score_component + remote_ratio + target_bonus, 1)

        items.append({
            "company_id": str(row.id),
            "company_name": row.name,
            "is_target": is_target,
            "total_jobs": int(row.total_jobs or 0),
            "relevant_jobs": relevant,
            "remote_jobs": remote,
            "avg_relevance_score": round(avg_score, 1),
            "company_score": company_score,
        })

    items.sort(key=lambda x: x["company_score"], reverse=True)
    return {"items": items}


@router.get("")
async def list_companies(
    search: str | None = None,
    is_target: bool | None = None,
    has_contacts: bool | None = None,
    actively_hiring: bool | None = None,
    funding_stage: str | None = None,
    recently_funded: bool | None = None,
    sort_by: str = "name",
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Build subqueries for filters
    contact_sub = (
        select(CompanyContact.company_id)
        .group_by(CompanyContact.company_id)
        .having(func.count(CompanyContact.id) > 0)
        .subquery()
    )

    cutoff_30d = datetime.now(timezone.utc) - timedelta(days=30)
    hiring_sub = (
        select(Job.company_id)
        .where(Job.first_seen_at >= cutoff_30d)
        .group_by(Job.company_id)
        .subquery()
    )

    def apply_filters(q):
        if search and search.strip():
            # Findings 84+85: escape `%`/`_`/`\\` so user-legal characters
            # ("100%", "dev_ops") match literally, and guard against
            # whitespace-only input that previously wildcarded rows with
            # triple-spaces in their name/industry/headquarters.
            needle = f"%{escape_like(search.strip())}%"
            q = q.where(
                or_(
                    Company.name.ilike(needle, escape="\\"),
                    Company.industry.ilike(needle, escape="\\"),
                    Company.headquarters.ilike(needle, escape="\\"),
                )
            )
        if is_target is not None:
            q = q.where(Company.is_target == is_target)
        if funding_stage:
            q = q.where(Company.funding_stage == funding_stage)
        if has_contacts is True:
            q = q.where(Company.id.in_(select(contact_sub.c.company_id)))
        elif has_contacts is False:
            q = q.where(Company.id.notin_(select(contact_sub.c.company_id)))
        if actively_hiring is True:
            q = q.where(Company.id.in_(select(hiring_sub.c.company_id)))
        elif actively_hiring is False:
            q = q.where(Company.id.notin_(select(hiring_sub.c.company_id)))
        if recently_funded is True:
            funded_cutoff = datetime.now(timezone.utc) - timedelta(days=180)
            q = q.where(Company.funded_at >= funded_cutoff)
        return q

    query = apply_filters(select(Company).options(joinedload(Company.ats_boards)))
    count_base = apply_filters(select(Company.id))
    total = (await db.execute(select(func.count()).select_from(count_base.subquery()))).scalar() or 0

    if sort_by == "funded_at":
        query = query.order_by(Company.funded_at.desc().nulls_last(), Company.name.asc())
    elif sort_by == "total_funding":
        query = query.order_by(Company.total_funding_usd.desc().nulls_last(), Company.name.asc())
    else:
        query = query.order_by(Company.name.asc())
    query = query.offset((page - 1) * per_page).limit(per_page)

    result = await db.execute(query)
    companies = result.unique().scalars().all()

    # Get job counts and contact counts per company
    company_ids = [c.id for c in companies]
    job_counts = {}
    accepted_counts = {}
    contact_counts = {}
    if company_ids:
        counts_q = (
            select(
                Job.company_id,
                func.count(Job.id).label("total"),
                func.sum(case((Job.status == "accepted", 1), else_=0)).label("accepted"),
            )
            .where(Job.company_id.in_(company_ids))
            .group_by(Job.company_id)
        )
        counts_result = await db.execute(counts_q)
        for row in counts_result:
            job_counts[row.company_id] = row.total
            accepted_counts[row.company_id] = int(row.accepted or 0)

        contact_q = (
            select(CompanyContact.company_id, func.count(CompanyContact.id).label("cnt"))
            .where(CompanyContact.company_id.in_(company_ids))
            .group_by(CompanyContact.company_id)
        )
        for row in await db.execute(contact_q):
            contact_counts[row.company_id] = int(row.cnt or 0)

    items = []
    for c in companies:
        item = CompanyOut.model_validate(c)
        item.job_count = job_counts.get(c.id, 0)
        item.accepted_count = accepted_counts.get(c.id, 0)
        item.contact_count = contact_counts.get(c.id, 0)
        items.append(item)

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": per_page,
        "total_pages": (total + per_page - 1) // per_page,
    }


@router.get("/{company_id}", response_model=CompanyOut)
async def get_company(
    company_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Company).options(joinedload(Company.ats_boards)).where(Company.id == company_id)
    )
    company = result.unique().scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    item = CompanyOut.model_validate(company)
    item.contact_count = (await db.execute(
        select(func.count(CompanyContact.id)).where(CompanyContact.company_id == company_id)
    )).scalar() or 0
    return item


@router.post("", response_model=CompanyOut, status_code=201)
async def create_company(
    body: CompanyCreate,
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    # Check slug uniqueness
    existing = await db.execute(select(Company).where(Company.slug == body.slug))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Company with this slug already exists")

    company = Company(**body.model_dump())
    db.add(company)
    await db.commit()
    await db.refresh(company)

    # Reload with ats_boards relationship
    result = await db.execute(
        select(Company).options(joinedload(Company.ats_boards)).where(Company.id == company.id)
    )
    company = result.unique().scalar_one()
    return CompanyOut.model_validate(company)


@router.patch("/{company_id}", response_model=CompanyOut)
async def update_company(
    company_id: UUID,
    body: CompanyUpdate,
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Company).options(joinedload(Company.ats_boards)).where(Company.id == company_id)
    )
    company = result.unique().scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(company, field, value)

    await db.commit()
    await db.refresh(company)

    # Reload with relationship
    result = await db.execute(
        select(Company).options(joinedload(Company.ats_boards)).where(Company.id == company.id)
    )
    company = result.unique().scalar_one()
    return CompanyOut.model_validate(company)


@router.get("/{company_id}/jobs")
async def company_jobs(
    company_id: UUID,
    status: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Verify company exists
    company_result = await db.execute(select(Company).where(Company.id == company_id))
    if not company_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Company not found")

    query = select(Job).where(Job.company_id == company_id)
    if status:
        query = query.where(Job.status == status)

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    query = query.order_by(Job.first_seen_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)

    result = await db.execute(query)
    jobs = result.scalars().all()
    items = [JobOut.model_validate(j) for j in jobs]

    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    }


@router.post("/{company_id}/ats-boards", response_model=ATSBoardOut, status_code=201)
async def add_ats_board(
    company_id: UUID,
    body: ATSBoardCreate,
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    # Verify company exists
    company_result = await db.execute(select(Company).where(Company.id == company_id))
    if not company_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Company not found")

    board = CompanyATSBoard(company_id=company_id, **body.model_dump())
    db.add(board)
    await db.commit()
    await db.refresh(board)
    return ATSBoardOut.model_validate(board)


@router.delete("/{company_id}/ats-boards/{board_id}", status_code=204)
async def remove_ats_board(
    company_id: UUID,
    board_id: UUID,
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(CompanyATSBoard).where(
            CompanyATSBoard.id == board_id,
            CompanyATSBoard.company_id == company_id,
        )
    )
    board = result.scalar_one_or_none()
    if not board:
        raise HTTPException(status_code=404, detail="ATS board not found")

    await db.delete(board)
    await db.commit()


# ── Company detail with enrichment ──────────────────────────────────────

@router.get("/{company_id}/detail")
async def get_company_detail(
    company_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get full company detail with contacts, offices, and hiring metrics."""
    result = await db.execute(
        select(Company)
        .options(
            joinedload(Company.ats_boards),
            joinedload(Company.contacts),
            joinedload(Company.offices),
        )
        .where(Company.id == company_id)
    )
    company = result.unique().scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    # Compute hiring metrics
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    active_statuses = ["new", "under_review", "accepted"]

    jobs_30d = (await db.execute(
        select(func.count(Job.id)).where(
            Job.company_id == company_id,
            Job.first_seen_at >= cutoff,
        )
    )).scalar() or 0

    open_roles = (await db.execute(
        select(func.count(Job.id)).where(
            Job.company_id == company_id,
            Job.status.in_(active_statuses),
        )
    )).scalar() or 0

    job_count = (await db.execute(
        select(func.count(Job.id)).where(Job.company_id == company_id)
    )).scalar() or 0

    accepted_count = (await db.execute(
        select(func.count(Job.id)).where(
            Job.company_id == company_id, Job.status == "accepted"
        )
    )).scalar() or 0

    velocity = "high" if jobs_30d > 5 else "medium" if jobs_30d >= 2 else "low"

    out = CompanyDetailOut.model_validate(company)
    out.job_count = job_count
    out.accepted_count = accepted_count
    out.actively_hiring = jobs_30d > 0
    out.hiring_velocity = velocity
    out.total_open_roles = open_roles
    return out


@router.post("/{company_id}/enrich")
async def trigger_enrichment(
    company_id: UUID,
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Trigger company enrichment (admin only)."""
    result = await db.execute(select(Company).where(Company.id == company_id))
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    from app.workers.tasks.enrichment_task import enrich_company
    task = enrich_company.delay(str(company_id))
    return {"task_id": task.id, "status": "queued", "company_id": str(company_id)}


@router.get("/{company_id}/enrichment-status")
async def enrichment_status(
    company_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Check enrichment status for a company."""
    result = await db.execute(select(Company).where(Company.id == company_id))
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    contact_count = (await db.execute(
        select(func.count(CompanyContact.id)).where(CompanyContact.company_id == company_id)
    )).scalar() or 0

    return {
        "status": company.enrichment_status,
        "enriched_at": company.enriched_at,
        "error": company.enrichment_error,
        "contacts_count": contact_count,
        "has_website": bool(company.website),
        "has_domain": bool(company.domain),
    }


# ── Contacts CRUD ───────────────────────────────────────────────────────

@router.get("/{company_id}/contacts")
async def list_contacts(
    company_id: UUID,
    role_category: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(CompanyContact).where(CompanyContact.company_id == company_id)
    if role_category:
        query = query.where(CompanyContact.role_category == role_category)
    query = query.order_by(CompanyContact.seniority.asc(), CompanyContact.last_name.asc())

    result = await db.execute(query)
    contacts = result.scalars().all()
    return {"items": [CompanyContactOut.model_validate(c) for c in contacts]}


@router.post("/{company_id}/contacts", response_model=CompanyContactOut, status_code=201)
async def create_contact(
    company_id: UUID,
    body: CompanyContactCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Company).where(Company.id == company_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Company not found")

    contact = CompanyContact(
        company_id=company_id,
        source="manual",
        confidence_score=1.0,
        **body.model_dump(),
    )
    db.add(contact)
    await db.commit()
    await db.refresh(contact)
    return CompanyContactOut.model_validate(contact)


@router.patch("/{company_id}/contacts/{contact_id}", response_model=CompanyContactOut)
async def update_contact(
    company_id: UUID,
    contact_id: UUID,
    body: CompanyContactUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(CompanyContact).where(
            CompanyContact.id == contact_id,
            CompanyContact.company_id == company_id,
        )
    )
    contact = result.scalar_one_or_none()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(contact, field, value)

    await db.commit()
    await db.refresh(contact)
    return CompanyContactOut.model_validate(contact)


@router.delete("/{company_id}/contacts/{contact_id}", status_code=204)
async def delete_contact(
    company_id: UUID,
    contact_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(CompanyContact).where(
            CompanyContact.id == contact_id,
            CompanyContact.company_id == company_id,
        )
    )
    contact = result.scalar_one_or_none()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    await db.delete(contact)
    await db.commit()


@router.get("/{company_id}/relevant-contacts/{job_id}")
async def relevant_contacts_for_job(
    company_id: UUID,
    job_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get contacts relevant to a specific job at this company."""
    result = await db.execute(
        select(JobContactRelevance, CompanyContact)
        .join(CompanyContact, JobContactRelevance.contact_id == CompanyContact.id)
        .where(
            JobContactRelevance.job_id == job_id,
            CompanyContact.company_id == company_id,
        )
        .order_by(JobContactRelevance.relevance_score.desc())
    )

    items = []
    for rel, contact in result:
        items.append(JobRelevantContact(
            contact=CompanyContactOut.model_validate(contact),
            relevance_reason=rel.relevance_reason,
            relevance_score=rel.relevance_score,
        ))

    return {"items": items}


# ── Outreach workflow ───────────────────────────────────────────────────

_VALID_OUTREACH = {"not_contacted", "emailed", "replied", "meeting_scheduled", "not_interested"}


@router.patch("/{company_id}/contacts/{contact_id}/outreach", response_model=CompanyContactOut)
async def update_contact_outreach(
    company_id: UUID,
    contact_id: UUID,
    body: OutreachUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update outreach status and note for a contact."""
    if body.outreach_status not in _VALID_OUTREACH:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid outreach_status. Must be one of: {', '.join(sorted(_VALID_OUTREACH))}",
        )

    result = await db.execute(
        select(CompanyContact).where(
            CompanyContact.id == contact_id,
            CompanyContact.company_id == company_id,
        )
    )
    contact = result.scalar_one_or_none()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    prev_status = contact.outreach_status
    contact.outreach_status = body.outreach_status
    contact.outreach_note = body.outreach_note
    # Stamp last_outreach_at whenever status changes away from not_contacted
    if prev_status != body.outreach_status and body.outreach_status != "not_contacted":
        contact.last_outreach_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(contact)
    return CompanyContactOut.model_validate(contact)


@router.post("/{company_id}/contacts/{contact_id}/draft-email")
async def draft_contact_email(
    company_id: UUID,
    contact_id: UUID,
    job_id: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a personalized outreach email draft for a contact using AI."""
    result = await db.execute(
        select(CompanyContact).where(
            CompanyContact.id == contact_id,
            CompanyContact.company_id == company_id,
        )
    )
    contact = result.scalar_one_or_none()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    company_result = await db.execute(select(Company).where(Company.id == company_id))
    company = company_result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    job = None
    if job_id:
        job_result = await db.execute(select(Job).where(Job.id == job_id))
        job = job_result.scalar_one_or_none()

    from app.config import get_settings
    settings = get_settings()

    # Build context
    ctx: list[str] = [
        f"Company: {company.name}",
        f"Contact: {contact.first_name} {contact.last_name}, {contact.title}",
    ]
    if company.industry:
        ctx.append(f"Industry: {company.industry}")
    if company.description:
        ctx.append(f"Company: {company.description[:250]}")
    if company.total_funding:
        ctx.append(f"Funding: {company.total_funding}")
    if company.tech_stack:
        ctx.append(f"Tech stack: {', '.join(company.tech_stack[:8])}")
    if job:
        ctx.append(f"Open role: {job.title}")

    template_subject = f"Quick question for {contact.first_name}"
    template_body = (
        f"Hi {contact.first_name},\n\n"
        f"I came across {company.name} and noticed you're {contact.title}. "
        f"We help companies like yours with cloud infrastructure and security staffing. "
        f"Would you have 15 minutes for a quick call?\n\nBest,"
    )

    if not settings.anthropic_api_key:
        return {"subject": template_subject, "body": template_body, "generated_by": "template"}

    try:
        import anthropic
        ai = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        prompt = (
            f"Write a concise, personalized cold outreach email to {contact.first_name} {contact.last_name} "
            f"({contact.title}) at {company.name}. "
            "This is from a cloud infrastructure and security consulting/staffing firm. "
            "Keep it to 3-4 sentences, non-spammy, and reference something specific about the company.\n\n"
            "Context:\n" + "\n".join(ctx) + "\n\n"
            "Respond with exactly:\n"
            "SUBJECT: <subject line>\n"
            "BODY:\n<email body>"
        )
        msg = ai.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=350,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text
        subject = template_subject
        body = text
        if "SUBJECT:" in text:
            lines = text.split("\n")
            for i, line in enumerate(lines):
                if line.startswith("SUBJECT:"):
                    subject = line.replace("SUBJECT:", "").strip()
                if line.startswith("BODY:"):
                    body = "\n".join(lines[i + 1:]).strip()
                    break
        return {"subject": subject, "body": body, "generated_by": "claude"}
    except Exception:
        return {"subject": template_subject, "body": template_body, "generated_by": "template"}


@router.post("/dedup-contacts")
async def trigger_dedup(
    user: User = Depends(require_role("admin")),
):
    """Trigger contact deduplication task (admin only)."""
    from app.workers.tasks.enrichment_task import deduplicate_contacts
    task = deduplicate_contacts.delay()
    return {"task_id": task.id, "status": "queued"}
