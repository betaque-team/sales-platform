"""Role rule management API endpoints."""

from uuid import UUID
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.rule import RoleRule
from app.models.user import User
from app.api.deps import get_current_user, require_role
from app.schemas.rule import RoleRuleOut, RoleRuleCreate, RoleRuleUpdate

router = APIRouter(prefix="/rules", tags=["rules"])


@router.get("")
async def list_rules(
    cluster: str | None = None,
    is_active: bool | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(RoleRule)

    if cluster:
        query = query.where(RoleRule.cluster == cluster)
    if is_active is not None:
        query = query.where(RoleRule.is_active == is_active)

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    query = query.order_by(RoleRule.cluster.asc(), RoleRule.base_role.asc())
    query = query.offset((page - 1) * per_page).limit(per_page)

    result = await db.execute(query)
    rules = result.scalars().all()
    items = [RoleRuleOut.model_validate(r) for r in rules]

    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    }


@router.post("", response_model=RoleRuleOut, status_code=201)
async def create_rule(
    body: RoleRuleCreate,
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    if body.cluster not in ("infra", "security"):
        raise HTTPException(status_code=400, detail="Cluster must be 'infra' or 'security'")

    rule = RoleRule(**body.model_dump())
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return RoleRuleOut.model_validate(rule)


@router.patch("/{rule_id}", response_model=RoleRuleOut)
async def update_rule(
    rule_id: UUID,
    body: RoleRuleUpdate,
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(RoleRule).where(RoleRule.id == rule_id))
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    update_data = body.model_dump(exclude_unset=True)

    if "cluster" in update_data and update_data["cluster"] not in ("infra", "security"):
        raise HTTPException(status_code=400, detail="Cluster must be 'infra' or 'security'")

    for field, value in update_data.items():
        setattr(rule, field, value)

    await db.commit()
    await db.refresh(rule)
    return RoleRuleOut.model_validate(rule)


@router.delete("/{rule_id}", status_code=204)
async def delete_rule(
    rule_id: UUID,
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(RoleRule).where(RoleRule.id == rule_id))
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    await db.delete(rule)
    await db.commit()
