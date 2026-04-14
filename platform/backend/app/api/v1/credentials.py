"""Platform credential management endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.platform_credential import PlatformCredential
from app.models.resume import Resume
from app.models.user import User
from app.api.deps import get_current_user
from app.utils.crypto import encrypt_credential

router = APIRouter(prefix="/credentials", tags=["credentials"])

SUPPORTED_PLATFORMS = [
    "greenhouse", "lever", "ashby", "workable", "smartrecruiters",
    "recruitee", "bamboohr", "jobvite", "wellfound", "himalayas",
]


@router.get("/{resume_id}")
async def list_credentials(
    resume_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List credentials for a resume (passwords masked)."""
    # Verify resume ownership
    resume = (await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user.id)
    )).scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    result = await db.execute(
        select(PlatformCredential)
        .where(PlatformCredential.resume_id == resume.id)
        .order_by(PlatformCredential.platform)
    )
    creds = result.scalars().all()

    return {
        "items": [
            {
                "id": str(c.id),
                "resume_id": str(c.resume_id),
                "platform": c.platform,
                "email": c.email,
                "has_password": bool(c.encrypted_password),
                "profile_url": c.profile_url,
                "is_verified": c.is_verified,
                "last_used_at": c.last_used_at.isoformat() if c.last_used_at else None,
                "created_at": c.created_at.isoformat(),
            }
            for c in creds
        ],
        "supported_platforms": SUPPORTED_PLATFORMS,
    }


@router.post("/{resume_id}")
async def save_credential(
    resume_id: str,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add or update a credential for a platform."""
    resume = (await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user.id)
    )).scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    platform = body.get("platform", "").lower()
    email = body.get("email", "").strip()
    password = body.get("password", "")
    profile_url = body.get("profile_url", "")

    if platform not in SUPPORTED_PLATFORMS:
        raise HTTPException(status_code=400, detail=f"Unsupported platform. Must be one of: {', '.join(SUPPORTED_PLATFORMS)}")
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")

    # Check if credential already exists for this resume+platform
    existing = (await db.execute(
        select(PlatformCredential).where(
            PlatformCredential.resume_id == resume.id,
            PlatformCredential.platform == platform,
        )
    )).scalar_one_or_none()

    if existing:
        existing.email = email
        if password:
            existing.encrypted_password = encrypt_credential(password)
        if profile_url:
            existing.profile_url = profile_url
        existing.is_verified = False  # Reset verification on update
        db.add(existing)
        cred = existing
    else:
        cred = PlatformCredential(
            id=uuid.uuid4(),
            resume_id=resume.id,
            platform=platform,
            email=email,
            encrypted_password=encrypt_credential(password) if password else "",
            profile_url=profile_url,
        )
        db.add(cred)

    await db.commit()
    await db.refresh(cred)

    return {
        "id": str(cred.id),
        "platform": cred.platform,
        "email": cred.email,
        "has_password": bool(cred.encrypted_password),
        "profile_url": cred.profile_url,
        "is_verified": cred.is_verified,
    }


@router.delete("/{resume_id}/{platform}")
async def delete_credential(
    resume_id: str,
    platform: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a credential for a platform."""
    resume = (await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user.id)
    )).scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    cred = (await db.execute(
        select(PlatformCredential).where(
            PlatformCredential.resume_id == resume.id,
            PlatformCredential.platform == platform,
        )
    )).scalar_one_or_none()
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found")

    cred.is_verified = False
    cred.encrypted_password = ""
    cred.email = f"archived_{cred.email}"
    await db.commit()
    return {"status": "archived", "message": "Credential archived (data preserved)"}
