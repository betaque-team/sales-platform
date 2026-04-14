"""Admin API for managing configurable role clusters (relevant job positions)."""

import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.role_config import RoleClusterConfig
from app.models.user import User
from app.api.deps import get_current_user, require_role

router = APIRouter(prefix="/role-clusters", tags=["role-clusters"])


class RoleClusterCreate(BaseModel):
    name: str
    display_name: str
    is_relevant: bool = True
    keywords: str = ""
    approved_roles: str = ""
    sort_order: int = 0


class RoleClusterUpdate(BaseModel):
    display_name: str | None = None
    is_relevant: bool | None = None
    is_active: bool | None = None
    keywords: str | None = None
    approved_roles: str | None = None
    sort_order: int | None = None


def _serialize(rc: RoleClusterConfig) -> dict:
    return {
        "id": str(rc.id),
        "name": rc.name,
        "display_name": rc.display_name,
        "is_relevant": rc.is_relevant,
        "is_active": rc.is_active,
        "keywords": rc.keywords,
        "approved_roles": rc.approved_roles,
        "sort_order": rc.sort_order,
        "keywords_list": [k.strip() for k in rc.keywords.split(",") if k.strip()] if rc.keywords else [],
        "approved_roles_list": [r.strip() for r in rc.approved_roles.split(",") if r.strip()] if rc.approved_roles else [],
        "created_at": rc.created_at.isoformat() if rc.created_at else None,
        "updated_at": rc.updated_at.isoformat() if rc.updated_at else None,
    }


@router.get("")
async def list_role_clusters(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all role clusters. Shows which ones count as 'relevant'."""
    result = await db.execute(
        select(RoleClusterConfig).order_by(RoleClusterConfig.sort_order, RoleClusterConfig.name)
    )
    clusters = result.scalars().all()
    return {
        "items": [_serialize(c) for c in clusters],
        "relevant_clusters": [c.name for c in clusters if c.is_relevant and c.is_active],
    }


@router.post("")
async def create_role_cluster(
    body: RoleClusterCreate,
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Create a new role cluster (admin only)."""
    name = body.name.lower().strip().replace(" ", "_")

    existing = await db.execute(
        select(RoleClusterConfig).where(RoleClusterConfig.name == name)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Role cluster '{name}' already exists")

    cluster = RoleClusterConfig(
        id=uuid.uuid4(),
        name=name,
        display_name=body.display_name,
        is_relevant=body.is_relevant,
        is_active=True,
        keywords=body.keywords,
        approved_roles=body.approved_roles,
        sort_order=body.sort_order,
    )
    db.add(cluster)
    await db.commit()
    await db.refresh(cluster)
    return _serialize(cluster)


@router.patch("/{cluster_id}")
async def update_role_cluster(
    cluster_id: str,
    body: RoleClusterUpdate,
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Update a role cluster (admin only)."""
    result = await db.execute(
        select(RoleClusterConfig).where(RoleClusterConfig.id == cluster_id)
    )
    cluster = result.scalar_one_or_none()
    if not cluster:
        raise HTTPException(status_code=404, detail="Role cluster not found")

    if body.display_name is not None:
        cluster.display_name = body.display_name
    if body.is_relevant is not None:
        cluster.is_relevant = body.is_relevant
    if body.is_active is not None:
        cluster.is_active = body.is_active
    if body.keywords is not None:
        cluster.keywords = body.keywords
    if body.approved_roles is not None:
        cluster.approved_roles = body.approved_roles
    if body.sort_order is not None:
        cluster.sort_order = body.sort_order

    cluster.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(cluster)
    return _serialize(cluster)


@router.delete("/{cluster_id}")
async def delete_role_cluster(
    cluster_id: str,
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Delete a role cluster (admin only). Cannot delete built-in infra/security."""
    result = await db.execute(
        select(RoleClusterConfig).where(RoleClusterConfig.id == cluster_id)
    )
    cluster = result.scalar_one_or_none()
    if not cluster:
        raise HTTPException(status_code=404, detail="Role cluster not found")

    if cluster.name in ("infra", "security"):
        raise HTTPException(status_code=400, detail="Cannot delete built-in role clusters")

    await db.delete(cluster)
    await db.commit()
    return {"ok": True}
