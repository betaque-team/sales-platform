"""Saved-filter-presets CRUD (F241).

khushi.jain feedback "Problem of Filter Stickness" — half-fixed by
F34 (URL-driven filter state survives navigation), but the user also
asked for named filter presets. This module is the missing half.

Auth model: every endpoint is per-user (filtered by `user_id`).
There's no admin override — saved filters are personal tooling, not
shared org config. If saved-filter sharing becomes a need later,
add a separate `shared_filters` table rather than overloading this
one (different access semantics, different audit-log shape).

Validation:
  - `name` 1-100 chars (matches DB column).
  - `filters` is a free-form dict — no per-key validation here. The
    JobsPage always sends back the same shape it received from
    /api/v1/jobs, so adding a new filter axis to JobsPage just
    starts shipping that key in `filters` without a schema change.
  - Duplicate name check: lower-cased uniqueness per user (so "Infra"
    and "infra" collide — matches the DB index).
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.saved_filter import SavedFilter
from app.models.user import User


router = APIRouter(prefix="/saved-filters", tags=["saved-filters"])


# Request shapes — `extra="forbid"` consistent with the Round 51/F130
# pattern across the codebase. Stale-schema clients sending
# `filterz: {...}` get a clean 422 instead of silent drop.

class SavedFilterCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(..., min_length=1, max_length=100)
    filters: dict = Field(default_factory=dict)


class SavedFilterUpdate(BaseModel):
    """Partial update — both fields optional, but at least one must
    be present (the handler 400s on a fully-empty body)."""
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=100)
    filters: dict | None = None


def _shape(row: SavedFilter) -> dict:
    return {
        "id": str(row.id),
        "name": row.name,
        "filters": row.filters or {},
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("")
async def list_saved_filters(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List the current user's saved filters, newest-edited first."""
    rows = (await db.execute(
        select(SavedFilter)
        .where(SavedFilter.user_id == user.id)
        .order_by(SavedFilter.updated_at.desc())
    )).scalars().all()
    return {"items": [_shape(r) for r in rows], "total": len(rows)}


@router.post("", status_code=201)
async def create_saved_filter(
    body: SavedFilterCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Save a new named filter preset.

    Conflicts (case-insensitive name collision per-user) → 409 with
    a useful message. The DB-level UNIQUE index would also catch this
    via IntegrityError but the explicit check gives a friendlier
    error before the round-trip to the DB.
    """
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "Name cannot be empty")

    existing = (await db.execute(
        select(SavedFilter).where(
            SavedFilter.user_id == user.id,
            func.lower(SavedFilter.name) == name.lower(),
        )
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(
            409,
            f"You already have a saved filter named '{existing.name}'. "
            f"Use PATCH to update it, or pick a different name.",
        )

    row = SavedFilter(user_id=user.id, name=name, filters=body.filters or {})
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _shape(row)


@router.patch("/{saved_filter_id}")
async def update_saved_filter(
    saved_filter_id: UUID,
    body: SavedFilterUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Rename and/or rewrite a saved filter's filter set.

    Both fields are optional; at least one must be provided. The
    `updated_at` column auto-bumps via the ORM `onupdate`.
    """
    row = (await db.execute(
        select(SavedFilter).where(
            SavedFilter.id == saved_filter_id,
            SavedFilter.user_id == user.id,
        )
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Saved filter not found")

    patch = body.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(400, "No fields to update")

    if "name" in patch:
        new_name = (patch["name"] or "").strip()
        if not new_name:
            raise HTTPException(400, "Name cannot be empty")
        # Case-insensitive uniqueness check (excluding this row).
        clash = (await db.execute(
            select(SavedFilter).where(
                SavedFilter.user_id == user.id,
                SavedFilter.id != row.id,
                func.lower(SavedFilter.name) == new_name.lower(),
            )
        )).scalar_one_or_none()
        if clash:
            raise HTTPException(409, f"Another saved filter named '{clash.name}' already exists")
        row.name = new_name

    if "filters" in patch and patch["filters"] is not None:
        row.filters = patch["filters"]

    # Manual timestamp bump in case the SQLAlchemy onupdate doesn't
    # fire on JSONB-only changes (some dialects skip onupdate when
    # only mutable JSONB fields change).
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    return _shape(row)


@router.delete("/{saved_filter_id}", status_code=204)
async def delete_saved_filter(
    saved_filter_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a saved filter. Idempotent — 204 even if it didn't
    exist (so the frontend doesn't have to coordinate a "are you
    sure it's there?" pre-check)."""
    row = (await db.execute(
        select(SavedFilter).where(
            SavedFilter.id == saved_filter_id,
            SavedFilter.user_id == user.id,
        )
    )).scalar_one_or_none()
    if row:
        await db.delete(row)
        await db.commit()
    return None
