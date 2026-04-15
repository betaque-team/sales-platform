"""Review workflow API endpoints."""

from uuid import UUID
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.database import get_db
from app.models.job import Job
from app.models.review import Review
from app.models.company import Company
from app.models.pipeline import PotentialClient
from app.models.user import User
from app.api.deps import get_current_user, require_role
from app.schemas.review import ReviewCreate, ReviewOut

router = APIRouter(prefix="/reviews", tags=["reviews"])


@router.post("", response_model=ReviewOut)
async def submit_review(
    body: ReviewCreate,
    user: User = Depends(require_role("admin", "reviewer")),
    db: AsyncSession = Depends(get_db),
):
    # Validate job exists
    result = await db.execute(select(Job).where(Job.id == body.job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Normalize decision: frontend sends accept/reject/skip, store as accepted/rejected/skipped
    decision_map = {"accept": "accepted", "reject": "rejected", "skip": "skipped"}
    normalized = decision_map.get(body.decision, body.decision)

    # Regression finding 73: rejection tags must only be persisted on
    # `decision="rejected"` rows. The frontend carried selectedTags across
    # prev/next navigation (finding 72) AND submitted them in the Accept
    # payload too — so a reviewer who armed tags for job A, then clicked
    # Next and hit Accept on job B, produced an accepted-review row with
    # rejection tags attached. Downstream rejection-reason histograms
    # double-count those tags because they show up on both accepted and
    # rejected rows. Silent-drop here (rather than 400) because the
    # reviewer's intent on Accept is "this is good" — surfacing an error
    # they never triggered would be a worse UX. The frontend fix
    # (tester-owned) sets tags=[] on accept/skip too; this is
    # defense-in-depth for hand-crafted POSTs or a future frontend regression.
    persisted_tags = list(body.tags) if normalized == "rejected" else []

    # Create review
    review = Review(
        job_id=body.job_id,
        reviewer_id=user.id,
        decision=normalized,
        comment=body.comment,
        tags=persisted_tags,
    )
    db.add(review)

    # Update job status
    if normalized in ("accepted", "rejected"):
        job.status = normalized
    elif normalized == "skipped":
        job.status = "under_review"

    # If accepted, create/update pipeline entry
    if normalized == "accepted":
        result = await db.execute(
            select(PotentialClient).where(PotentialClient.company_id == job.company_id)
        )
        client = result.scalar_one_or_none()
        if client:
            client.accepted_jobs_count += 1
        else:
            # Auto-create pipeline entry
            result = await db.execute(select(Company).where(Company.id == job.company_id))
            company = result.scalar_one_or_none()
            if company:
                company.is_target = True
                client = PotentialClient(
                    company_id=job.company_id,
                    stage="new_lead",
                    accepted_jobs_count=1,
                )
                db.add(client)

    await db.commit()
    await db.refresh(review)

    # Dispatch feedback processing
    from app.workers.tasks.feedback_task import process_review_feedback_task
    process_review_feedback_task.delay(str(review.id))

    out = ReviewOut.model_validate(review)
    out.reviewer_name = user.name
    return out


@router.get("")
async def list_reviews(
    job_id: UUID | None = None,
    decision: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(Review).options(joinedload(Review.reviewer))

    if job_id:
        query = query.where(Review.job_id == job_id)
    if decision:
        query = query.where(Review.decision == decision)

    query = query.order_by(Review.created_at.desc())

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    reviews = result.unique().scalars().all()

    items = []
    for r in reviews:
        item = ReviewOut.model_validate(r)
        item.reviewer_name = r.reviewer.name if r.reviewer else None
        items.append(item)

    return {"items": items, "total": total, "page": page, "page_size": per_page, "total_pages": (total + per_page - 1) // per_page}
