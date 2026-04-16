"""Career page watch management API endpoints."""

from uuid import UUID
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.scan import CareerPageWatch
from app.models.user import User
from app.api.deps import get_current_user


router = APIRouter(prefix="/career-pages", tags=["career-pages"])


# Regression finding 174: `career_page.url` had no format validation, so
# the scraper had been accepting display names (`"Yat Labs"`, `"push AI"`),
# bare slugs (`"zfnd"`, `"reifyhealth"`), and partial domains
# (`"speckle.systems"`, `"tinlake.centrifuge"`) as URLs — 117 heterogeneous
# rows. The scraper couldn't actually fetch any of them (hence `last_hash=""`
# for all 117 after 134 check rounds — change detection was effectively dead).
# We can't safely migrate existing rows without domain research per company,
# but we can stop the bleed: new POST/PATCH must supply a proper http(s) URL.
def _validate_career_page_url(v: str) -> str:
    if v is None:
        return v
    stripped = v.strip()
    if not stripped:
        raise ValueError("url must not be empty")
    if len(stripped) > 2048:
        raise ValueError("url too long (max 2048 chars)")
    low = stripped.lower()
    if not (low.startswith("http://") or low.startswith("https://")):
        raise ValueError(
            "url must be a full URL starting with http:// or https:// — "
            "slugs and display names are not accepted"
        )
    return stripped


class CareerPageOut(BaseModel):
    id: UUID
    company_id: UUID | None
    url: str
    last_hash: str
    last_checked_at: datetime | None
    has_changed: bool
    check_count: int
    change_count: int
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class CareerPageCreate(BaseModel):
    company_id: UUID | None = None
    url: str
    is_active: bool = True

    @field_validator("url")
    @classmethod
    def _check_url(cls, v):
        return _validate_career_page_url(v)


class CareerPageUpdate(BaseModel):
    url: str | None = None
    is_active: bool | None = None
    company_id: UUID | None = None

    @field_validator("url")
    @classmethod
    def _check_url(cls, v):
        # PATCH: omitted `url` stays None (partial update). If explicitly
        # provided, apply the same full-URL requirement as POST.
        if v is None:
            return v
        return _validate_career_page_url(v)


@router.get("")
async def list_career_pages(
    is_active: bool | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(CareerPageWatch)
    if is_active is not None:
        query = query.where(CareerPageWatch.is_active == is_active)

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    query = query.order_by(CareerPageWatch.created_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)

    result = await db.execute(query)
    pages = result.scalars().all()
    items = [CareerPageOut.model_validate(p) for p in pages]

    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    }


@router.post("", response_model=CareerPageOut, status_code=201)
async def create_career_page(
    body: CareerPageCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Check URL uniqueness
    existing = await db.execute(select(CareerPageWatch).where(CareerPageWatch.url == body.url))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="This URL is already being watched")

    watch = CareerPageWatch(**body.model_dump())
    db.add(watch)
    await db.commit()
    await db.refresh(watch)
    return CareerPageOut.model_validate(watch)


@router.patch("/{page_id}", response_model=CareerPageOut)
async def update_career_page(
    page_id: UUID,
    body: CareerPageUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(CareerPageWatch).where(CareerPageWatch.id == page_id))
    watch = result.scalar_one_or_none()
    if not watch:
        raise HTTPException(status_code=404, detail="Career page watch not found")

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(watch, field, value)

    await db.commit()
    await db.refresh(watch)
    return CareerPageOut.model_validate(watch)


@router.delete("/{page_id}", status_code=204)
async def delete_career_page(
    page_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(CareerPageWatch).where(CareerPageWatch.id == page_id))
    watch = result.scalar_one_or_none()
    if not watch:
        raise HTTPException(status_code=404, detail="Career page watch not found")

    await db.delete(watch)
    await db.commit()


@router.post("/{page_id}/check")
async def trigger_check(
    page_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trigger an immediate check of this career page.

    This marks the page as needing a check. The actual check is performed
    by the background scanner process.
    """
    result = await db.execute(select(CareerPageWatch).where(CareerPageWatch.id == page_id))
    watch = result.scalar_one_or_none()
    if not watch:
        raise HTTPException(status_code=404, detail="Career page watch not found")

    if not watch.is_active:
        raise HTTPException(status_code=400, detail="Career page watch is inactive")

    # Reset last_checked_at to force the scanner to pick it up next cycle
    watch.last_checked_at = None
    await db.commit()

    return {
        "ok": True,
        "message": "Check queued. The page will be scanned on the next cycle.",
        "page_id": str(page_id),
    }
