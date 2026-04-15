"""Job listing API endpoints."""

from uuid import UUID
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select, func, or_, literal, case
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.database import get_db
from app.models.job import Job, JobDescription
from app.models.company import Company
from app.models.user import User
from app.models.resume import ResumeScore
from app.models.role_config import RoleClusterConfig
from app.api.deps import get_current_user, require_role
from app.schemas.job import JobOut, JobDescriptionOut, JobStatusUpdate, BulkActionRequest
from app.utils.sanitize import sanitize_html
from app.utils.sql import escape_like


async def _get_relevant_clusters(db: AsyncSession) -> list[str]:
    """Get the list of role cluster names that are marked as relevant."""
    result = await db.execute(
        select(RoleClusterConfig.name).where(
            RoleClusterConfig.is_relevant == True,
            RoleClusterConfig.is_active == True,
        )
    )
    clusters = result.scalars().all()
    # Fallback to hardcoded if no config exists yet
    return list(clusters) if clusters else ["infra", "security"]

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("")
async def list_jobs(
    status: str | None = None,
    platform: str | None = None,
    source_platform: str | None = None,
    company_id: UUID | None = None,
    company: str | None = None,
    geography_bucket: str | None = None,
    geography: str | None = None,
    role_cluster: str | None = None,
    is_classified: bool | None = None,
    search: str | None = None,
    q: str | None = None,
    sort_by: str = "first_seen_at",
    sort_dir: str = "desc",
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    page_size: int | None = Query(None, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Accept page_size as alias for per_page (frontend sends page_size)
    if page_size is not None:
        per_page = page_size

    # Regression finding 33: the response schema aliases `Job.platform` as
    # `source_platform` and field-level aliases for `search` (`q`) and
    # `company_id` (`company`) are expected by callers who are reading the
    # response field names and assuming the query params match. Accept the
    # aliases here as a non-breaking alternative to the original param
    # names — callers who were passing the original names still work.
    effective_platform = platform or source_platform
    effective_search = search or q

    query = select(Job).options(joinedload(Job.company))

    if status:
        query = query.where(Job.status == status)
    if effective_platform:
        query = query.where(Job.platform == effective_platform)
    if company_id:
        query = query.where(Job.company_id == company_id)
    if company and company.strip():
        # `company=` is a name-substring filter (the id-based filter lives on
        # `company_id`). Matches the same ilike pattern used for the combined
        # `search` box so the two behave consistently. Findings 84+85:
        # escape LIKE metachars and strip whitespace-only input so `"100%"`
        # / `"dev_ops"` / `"   "` don't degenerate into wildcard matches.
        needle = f"%{escape_like(company.strip())}%"
        query = query.where(Job.company.has(Company.name.ilike(needle, escape="\\")))
    geo = geography_bucket or geography
    if geo:
        query = query.where(Job.geography_bucket == geo)
    if role_cluster:
        if role_cluster == "relevant":
            relevant_clusters = await _get_relevant_clusters(db)
            query = query.where(Job.role_cluster.in_(relevant_clusters))
        else:
            query = query.where(Job.role_cluster == role_cluster)

    # Regression finding 87: let callers filter the (huge — ~90% of rows)
    # unclassified pool without hand-crafting `role_cluster=` URLs that
    # some clients strip as empty. `is_classified=false` → the row has
    # NULL or "" cluster; `is_classified=true` → anything else. We
    # check both NULL and "" because historical rows use the empty
    # string while newer inserts may leave it NULL. Combining this with
    # `role_cluster=foo` is contradictory-but-valid SQL (returns 0) —
    # we don't reject it; the frontend just shouldn't send both.
    if is_classified is True:
        query = query.where(
            Job.role_cluster.is_not(None),
            Job.role_cluster != "",
        )
    elif is_classified is False:
        query = query.where(
            or_(Job.role_cluster.is_(None), Job.role_cluster == "")
        )

    if effective_search and effective_search.strip():
        # Search across title, company name, and location. Findings 84+85:
        # strip whitespace-only input and escape LIKE metachars — a search
        # for `"100%"` must not match every row, and a 3-space input must
        # not wildcard-match random titles with triple spaces.
        needle = f"%{escape_like(effective_search.strip())}%"
        query = query.where(
            or_(
                Job.title.ilike(needle, escape="\\"),
                Job.company.has(Company.name.ilike(needle, escape="\\")),
                Job.location_raw.ilike(needle, escape="\\"),
            )
        )

    # Count
    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    # If sorting by resume_score, use a LEFT JOIN with ResumeScore
    if sort_by == "resume_score" and user.active_resume_id:
        query = query.outerjoin(
            ResumeScore,
            (ResumeScore.job_id == Job.id) & (ResumeScore.resume_id == user.active_resume_id),
        )
        score_col = func.coalesce(ResumeScore.overall_score, 0)
        query = query.order_by(score_col.desc() if sort_dir == "desc" else score_col.asc())
    elif sort_by == "company_name":
        # Sort by the related company name — need explicit join
        query = query.join(Company, Job.company_id == Company.id)
        query = query.order_by(Company.name.desc() if sort_dir == "desc" else Company.name.asc())
    else:
        sort_col = getattr(Job, sort_by, None)
        if sort_col is None:
            sort_col = Job.first_seen_at
        query = query.order_by(sort_col.desc() if sort_dir == "desc" else sort_col.asc())

    query = query.offset((page - 1) * per_page).limit(per_page)

    result = await db.execute(query)
    jobs = result.unique().scalars().all()

    # Fetch resume scores for these jobs
    resume_scores_map: dict[str, float] = {}
    if user.active_resume_id and jobs:
        job_ids = [j.id for j in jobs]
        score_result = await db.execute(
            select(ResumeScore.job_id, ResumeScore.overall_score)
            .where(
                ResumeScore.resume_id == user.active_resume_id,
                ResumeScore.job_id.in_(job_ids),
            )
        )
        for job_id, score in score_result:
            resume_scores_map[str(job_id)] = round(score, 1)

    items = []
    for j in jobs:
        item = JobOut.model_validate(j)
        item.company_name = j.company.name if j.company else None
        items.append(item)

    # Serialize with resume_score enrichment
    items_data = []
    for item, j in zip(items, jobs):
        d = item.model_dump(mode="json")
        d["resume_score"] = resume_scores_map.get(str(j.id))
        items_data.append(d)

    return {"items": items_data, "total": total, "page": page, "page_size": per_page, "total_pages": (total + per_page - 1) // per_page}


@router.get("/review-queue")
async def review_queue(
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(require_role("admin", "reviewer")),
    db: AsyncSession = Depends(get_db),
):
    """Get next batch of unreviewed jobs sorted by relevance score."""
    query = (
        select(Job).options(joinedload(Job.company))
        .where(Job.status == "new")
        .order_by(Job.relevance_score.desc(), Job.first_seen_at.desc())
        .limit(limit)
    )
    result = await db.execute(query)
    jobs = result.unique().scalars().all()

    items = []
    for j in jobs:
        item = JobOut.model_validate(j)
        item.company_name = j.company.name if j.company else None
        items.append(item)

    return {"items": items, "total": len(items), "page": 1, "page_size": limit, "total_pages": 1}


@router.get("/{job_id}")
async def get_job(job_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Job).options(joinedload(Job.company), joinedload(Job.description)).where(Job.id == job_id)
    )
    job = result.unique().scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    data = JobOut.model_validate(job)
    data.company_name = job.company.name if job.company else None

    d = data.model_dump(mode="json")

    # Enrich with resume score if active resume exists
    if user.active_resume_id:
        score_result = await db.execute(
            select(ResumeScore).where(
                ResumeScore.resume_id == user.active_resume_id,
                ResumeScore.job_id == job.id,
            )
        )
        rs = score_result.scalar_one_or_none()
        if rs:
            d["resume_score"] = round(rs.overall_score, 1)
            d["resume_fit"] = {
                "overall_score": round(rs.overall_score, 1),
                "keyword_score": round(rs.keyword_score, 1),
                "role_match_score": round(rs.role_match_score, 1),
                "format_score": round(rs.format_score, 1),
                "matched_keywords": rs.matched_keywords or [],
                "missing_keywords": rs.missing_keywords or [],
                "suggestions": rs.suggestions or [],
            }
        else:
            d["resume_score"] = None
            d["resume_fit"] = None
    else:
        d["resume_score"] = None
        d["resume_fit"] = None

    return d


@router.get("/{job_id}/score-breakdown")
async def get_job_score_breakdown(job_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Get scoring breakdown for a specific job."""
    result = await db.execute(
        select(Job).options(joinedload(Job.company)).where(Job.id == job_id)
    )
    job = result.unique().scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    from app.workers.tasks._scoring import (
        _title_match_score, _company_fit_score, _geography_clarity_score,
        _source_priority_score, _freshness_score,
    )
    from app.workers.tasks._role_matching import match_role

    role_match = match_role(job.title)
    title_score = _title_match_score(role_match["matched_role"], role_match["role_cluster"])
    company_score = _company_fit_score(job.company.is_target if job.company else False)
    geo_score = _geography_clarity_score(job.geography_bucket, job.remote_scope)
    source_score = _source_priority_score(job.platform)
    fresh_score = _freshness_score(job.posted_at)

    return {
        "total": job.relevance_score,
        "breakdown": [
            {"signal": "Title Match", "weight": 0.40, "raw": round(title_score, 2), "weighted": round(title_score * 0.40 * 100, 1), "detail": f"Matched: {role_match['matched_role'] or 'None'} ({role_match['role_cluster'] or 'no cluster'})"},
            {"signal": "Company Fit", "weight": 0.20, "raw": round(company_score, 2), "weighted": round(company_score * 0.20 * 100, 1), "detail": f"Target: {'Yes' if (job.company and job.company.is_target) else 'No'}"},
            {"signal": "Geography Clarity", "weight": 0.20, "raw": round(geo_score, 2), "weighted": round(geo_score * 0.20 * 100, 1), "detail": f"Bucket: {job.geography_bucket or 'unknown'}, Scope: {job.remote_scope or 'none'}"},
            {"signal": "Source Priority", "weight": 0.10, "raw": round(source_score, 2), "weighted": round(source_score * 0.10 * 100, 1), "detail": f"Platform: {job.platform}"},
            {"signal": "Freshness", "weight": 0.10, "raw": round(fresh_score, 2), "weighted": round(fresh_score * 0.10 * 100, 1), "detail": f"Posted: {job.posted_at.strftime('%Y-%m-%d') if job.posted_at else 'Unknown'}"},
        ],
    }


@router.get("/{job_id}/description")
async def get_job_description(job_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(JobDescription).where(JobDescription.job_id == job_id))
    jd = result.scalar_one_or_none()
    if jd:
        # The frontend renders this via dangerouslySetInnerHTML, so any HTML
        # coming from ATS boards must be sanitized (strip <script>, event
        # handlers, javascript: URLs, etc.) before we hand it back.
        return JobDescriptionOut(
            id=jd.id,
            job_id=jd.job_id,
            raw_text=sanitize_html(jd.text_content or jd.html_content or ""),
            parsed_requirements=[],
            parsed_nice_to_have=[],
            parsed_tech_stack=[],
        )

    # Fallback: extract description from raw_json
    import html as html_mod
    job_result = await db.execute(select(Job).where(Job.id == job_id))
    job = job_result.scalar_one_or_none()
    raw_text = ""
    if job and job.raw_json:
        raw = job.raw_json if isinstance(job.raw_json, dict) else {}
        # Platform-specific field mapping
        raw_text = (
            raw.get("content")           # greenhouse
            or raw.get("descriptionHtml")  # ashby
            or raw.get("description")      # lever, himalayas, remoteok, remotive
            or raw.get("descriptionPlain")  # lever/ashby plaintext fallback
            or raw.get("descriptionBody")   # lever additional
            or ""
        )
        # Lever stores lists of requirements — join if the additional field has more
        additional = raw.get("additional") or raw.get("additionalPlain") or ""
        if additional and len(additional) > len(raw_text):
            raw_text = additional
        # Unescape HTML entities (raw_json may store &lt; as escaped)
        if raw_text and "&lt;" in raw_text:
            raw_text = html_mod.unescape(raw_text)

    # Sanitize before returning — frontend renders via dangerouslySetInnerHTML.
    return JobDescriptionOut(raw_text=sanitize_html(raw_text), parsed_requirements=[], parsed_nice_to_have=[], parsed_tech_stack=[])


@router.get("/{job_id}/reviews")
async def get_job_reviews(job_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Get reviews for a specific job."""
    from app.models.review import Review
    from app.schemas.review import ReviewOut
    result = await db.execute(
        select(Review).options(joinedload(Review.reviewer))
        .where(Review.job_id == job_id)
        .order_by(Review.created_at.desc())
    )
    reviews = result.unique().scalars().all()
    items = []
    for r in reviews:
        item = ReviewOut.model_validate(r)
        item.reviewer_name = r.reviewer.name if r.reviewer else None
        items.append(item)
    return items


@router.patch("/{job_id}")
async def update_job_status(
    job_id: UUID, body: JobStatusUpdate,
    user: User = Depends(require_role("admin", "reviewer")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job.status = body.status
    await db.commit()
    return {"ok": True}


@router.post("/bulk-action")
async def bulk_action(
    body: BulkActionRequest,
    user: User = Depends(require_role("admin", "reviewer")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Job).where(Job.id.in_(body.job_ids)))
    jobs = result.scalars().all()
    for j in jobs:
        j.status = body.action
    await db.commit()
    return {"updated": len(jobs)}
