"""Potential Clients pipeline API with configurable stages."""

from uuid import UUID
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.database import get_db
from app.models.pipeline import PotentialClient
from app.models.pipeline_stage import PipelineStage
from app.models.company import Company
from app.models.job import Job
from app.models.resume import Resume
from app.models.user import User
from app.api.deps import get_current_user, require_role
from app.schemas.pipeline import (
    PipelineItemOut,
    PipelineUpdate,
    PIPELINE_MAX_PRIORITY,
    PIPELINE_MAX_NOTES_LENGTH,
)

# Default stages seeded on first access
DEFAULT_STAGES = [
    {"key": "new_lead", "label": "New Lead", "color": "bg-blue-500", "sort_order": 0},
    {"key": "researching", "label": "Researching", "color": "bg-purple-500", "sort_order": 1},
    {"key": "qualified", "label": "Qualified", "color": "bg-emerald-500", "sort_order": 2},
    {"key": "outreach", "label": "Outreach", "color": "bg-amber-500", "sort_order": 3},
    {"key": "engaged", "label": "Engaged", "color": "bg-green-500", "sort_order": 4},
    {"key": "disqualified", "label": "Disqualified", "color": "bg-red-500", "sort_order": 5},
]


class PipelineCreateRequest(BaseModel):
    company_id: str
    stage: str = "new_lead"
    priority: int = Field(default=0, ge=0, le=PIPELINE_MAX_PRIORITY)
    notes: str = Field(default="", max_length=PIPELINE_MAX_NOTES_LENGTH)


class StageCreate(BaseModel):
    key: str
    label: str
    color: str = "bg-gray-500"
    sort_order: int = 0


class StageUpdate(BaseModel):
    label: str | None = None
    color: str | None = None
    sort_order: int | None = None


router = APIRouter(prefix="/pipeline", tags=["pipeline"])


async def _get_active_stages(db: AsyncSession) -> list[PipelineStage]:
    """Get active pipeline stages, auto-seeding defaults if table is empty."""
    result = await db.execute(
        select(PipelineStage).where(PipelineStage.is_active == True).order_by(PipelineStage.sort_order)
    )
    stages = list(result.scalars().all())
    if not stages:
        # Seed defaults
        for s in DEFAULT_STAGES:
            stage = PipelineStage(**s)
            db.add(stage)
        await db.commit()
        result = await db.execute(
            select(PipelineStage).where(PipelineStage.is_active == True).order_by(PipelineStage.sort_order)
        )
        stages = list(result.scalars().all())
    return stages


async def _get_stage_keys(db: AsyncSession) -> list[str]:
    stages = await _get_active_stages(db)
    return [s.key for s in stages]


# ── Stage management (admin/super_admin) ──

@router.get("/stages")
async def list_stages(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all pipeline stages (including inactive for admin)."""
    if user.role in ("admin", "super_admin"):
        result = await db.execute(select(PipelineStage).order_by(PipelineStage.sort_order))
    else:
        result = await db.execute(
            select(PipelineStage).where(PipelineStage.is_active == True).order_by(PipelineStage.sort_order)
        )
    stages = result.scalars().all()
    if not stages:
        stages = await _get_active_stages(db)
    return {
        "items": [
            {
                "id": str(s.id),
                "key": s.key,
                "label": s.label,
                "color": s.color,
                "sort_order": s.sort_order,
                "is_active": s.is_active,
            }
            for s in stages
        ]
    }


@router.post("/stages", status_code=201)
async def create_stage(
    body: StageCreate,
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Add a new pipeline stage (admin/super_admin)."""
    # Check key uniqueness
    existing = (await db.execute(
        select(PipelineStage).where(PipelineStage.key == body.key)
    )).scalar_one_or_none()
    if existing:
        if not existing.is_active:
            # Reactivate
            existing.is_active = True
            existing.label = body.label
            existing.color = body.color
            existing.sort_order = body.sort_order
            await db.commit()
            return {"ok": True, "id": str(existing.id), "reactivated": True}
        raise HTTPException(400, "Stage key already exists")

    stage = PipelineStage(key=body.key, label=body.label, color=body.color, sort_order=body.sort_order)
    db.add(stage)
    await db.commit()
    await db.refresh(stage)
    return {"ok": True, "id": str(stage.id)}


@router.patch("/stages/{stage_id}")
async def update_stage(
    stage_id: UUID,
    body: StageUpdate,
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Update a stage label, color, or sort order (admin/super_admin)."""
    stage = await db.get(PipelineStage, stage_id)
    if not stage:
        raise HTTPException(404, "Stage not found")

    if body.label is not None:
        stage.label = body.label
    if body.color is not None:
        stage.color = body.color
    if body.sort_order is not None:
        stage.sort_order = body.sort_order

    await db.commit()
    return {"ok": True, "id": str(stage.id), "label": stage.label, "color": stage.color}


@router.delete("/stages/{stage_id}")
async def deactivate_stage(
    stage_id: UUID,
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate a pipeline stage (soft-delete, data preserved)."""
    stage = await db.get(PipelineStage, stage_id)
    if not stage:
        raise HTTPException(404, "Stage not found")

    # Check if any pipeline items use this stage
    count = (await db.execute(
        select(func.count()).select_from(PotentialClient).where(PotentialClient.stage == stage.key)
    )).scalar() or 0

    stage.is_active = False
    await db.commit()
    return {
        "ok": True,
        "message": f"Stage '{stage.label}' deactivated (data preserved)",
        "items_in_stage": count,
    }


# ── Pipeline CRUD ──

@router.get("")
async def get_pipeline(
    stage: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    active_stages = await _get_active_stages(db)
    stage_keys = [s.key for s in active_stages]

    query = select(PotentialClient).options(
        joinedload(PotentialClient.company),
        joinedload(PotentialClient.applicant),
        joinedload(PotentialClient.resume),
    )
    if stage:
        query = query.where(PotentialClient.stage == stage)
    query = query.order_by(PotentialClient.priority.desc(), PotentialClient.created_at.desc())

    result = await db.execute(query)
    clients = result.unique().scalars().all()

    # Gather company IDs to compute live metrics
    company_ids = [c.company_id for c in clients if c.company_id]

    open_roles_map: dict[str, int] = {}
    accepted_map: dict[str, int] = {}
    velocity_map: dict[str, str] = {}
    last_job_map: dict[str, datetime | None] = {}

    if company_ids:
        open_result = await db.execute(
            select(Job.company_id, func.count(Job.id))
            .where(Job.company_id.in_(company_ids), Job.status.in_(["new", "accepted", "under_review"]))
            .group_by(Job.company_id)
        )
        for cid, cnt in open_result:
            open_roles_map[str(cid)] = cnt

        acc_result = await db.execute(
            select(Job.company_id, func.count(Job.id))
            .where(Job.company_id.in_(company_ids), Job.status == "accepted")
            .group_by(Job.company_id)
        )
        for cid, cnt in acc_result:
            accepted_map[str(cid)] = cnt

        thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
        vel_result = await db.execute(
            select(Job.company_id, func.count(Job.id))
            .where(Job.company_id.in_(company_ids), Job.first_seen_at >= thirty_days_ago)
            .group_by(Job.company_id)
        )
        for cid, cnt in vel_result:
            cid_str = str(cid)
            velocity_map[cid_str] = "high" if cnt > 5 else "medium" if cnt >= 2 else "low"

        last_result = await db.execute(
            select(Job.company_id, func.max(Job.first_seen_at))
            .where(Job.company_id.in_(company_ids))
            .group_by(Job.company_id)
        )
        for cid, last_seen in last_result:
            last_job_map[str(cid)] = last_seen

    items = []
    for c in clients:
        item = PipelineItemOut.model_validate(c)
        item.company_name = c.company.name if c.company else None
        item.company_website = c.company.website if c.company else None
        item.applied_by_name = c.applicant.name if c.applicant else None
        item.resume_label = c.resume.label if c.resume else None
        items.append(item)

    items_data = []
    for item, c in zip(items, clients):
        d = item.model_dump(mode="json")
        cid = str(c.company_id) if c.company_id else ""
        d["total_open_roles"] = open_roles_map.get(cid, 0)
        d["accepted_jobs_count"] = accepted_map.get(cid, d.get("accepted_jobs_count", 0))
        d["hiring_velocity"] = velocity_map.get(cid, "low")
        d["last_job_at"] = last_job_map.get(cid, None)
        if d["last_job_at"]:
            d["last_job_at"] = d["last_job_at"].isoformat()
        items_data.append(d)

    # Group by stage (include all active stages even if empty)
    grouped = {s: [] for s in stage_keys}
    for item in items_data:
        stage_key = item["stage"]
        if stage_key in grouped:
            grouped[stage_key].append(item)
        else:
            # Item in a deactivated stage — still show it
            grouped.setdefault(stage_key, []).append(item)

    # Return stage config along with items
    stages_config = [
        {"key": s.key, "label": s.label, "color": s.color}
        for s in active_stages
    ]

    return {"stages": stage_keys, "stages_config": stages_config, "items": grouped, "total": len(items_data)}


@router.post("", status_code=201)
async def create_pipeline_entry(
    body: PipelineCreateRequest,
    user: User = Depends(require_role("admin", "reviewer")),
    db: AsyncSession = Depends(get_db),
):
    """Manually add a company to the pipeline."""
    company = (await db.execute(select(Company).where(Company.id == body.company_id))).scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    existing = (await db.execute(
        select(PotentialClient).where(PotentialClient.company_id == body.company_id)
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Company is already in the pipeline")

    stage_keys = await _get_stage_keys(db)
    if body.stage not in stage_keys:
        raise HTTPException(status_code=400, detail=f"Invalid stage. Must be one of: {', '.join(stage_keys)}")

    client = PotentialClient(
        company_id=body.company_id,
        stage=body.stage,
        priority=body.priority,
        notes=body.notes,
    )
    db.add(client)
    await db.commit()
    await db.refresh(client)

    try:
        from app.workers.tasks.enrichment_task import enrich_company
        enrich_company.delay(str(company.id))
    except Exception:
        pass

    return {"ok": True, "id": str(client.id), "company_name": company.name}


@router.get("/{client_id}", response_model=PipelineItemOut)
async def get_client(client_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(PotentialClient).options(joinedload(PotentialClient.company)).where(PotentialClient.id == client_id)
    )
    client = result.unique().scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    item = PipelineItemOut.model_validate(client)
    item.company_name = client.company.name if client.company else None
    item.company_website = client.company.website if client.company else None
    return item


@router.patch("/{client_id}", response_model=PipelineItemOut)
async def update_client(
    client_id: UUID, body: PipelineUpdate,
    user: User = Depends(require_role("admin", "reviewer")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PotentialClient).options(joinedload(PotentialClient.company)).where(PotentialClient.id == client_id)
    )
    client = result.unique().scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    if body.stage is not None:
        # Validate against known stage keys — same check as POST — so cards
        # can't be dropped into a non-existent / deactivated stage via the
        # API (and then vanish from the kanban board).
        stage_keys = await _get_stage_keys(db)
        if body.stage not in stage_keys:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid stage. Must be one of: {', '.join(stage_keys)}",
            )
        client.stage = body.stage
    if body.priority is not None:
        client.priority = body.priority
    # Regression finding 111: validate FK references before commit so a
    # non-existent UUID returns 404 instead of a raw 500 IntegrityError.
    if body.assigned_to is not None:
        if (await db.get(User, body.assigned_to)) is None:
            raise HTTPException(status_code=404, detail="assigned_to user not found")
        client.assigned_to = body.assigned_to
    if body.resume_id is not None:
        if (await db.get(Resume, body.resume_id)) is None:
            raise HTTPException(status_code=404, detail="resume_id not found")
        client.resume_id = body.resume_id
    if body.applied_by is not None:
        if (await db.get(User, body.applied_by)) is None:
            raise HTTPException(status_code=404, detail="applied_by user not found")
        client.applied_by = body.applied_by
    if body.notes is not None:
        client.notes = body.notes

    await db.commit()
    await db.refresh(client)
    item = PipelineItemOut.model_validate(client)
    item.company_name = client.company.name if client.company else None
    item.company_website = client.company.website if client.company else None
    return item
