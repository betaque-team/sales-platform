"""Admin user management API endpoints."""

from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.api.deps import require_role
from app.schemas.user import UserOut, UserUpdate
from app.utils.audit import log_action

router = APIRouter(prefix="/users", tags=["users"])

VALID_ROLES = {"super_admin", "admin", "reviewer", "viewer"}

ROLE_DESCRIPTIONS = {
    "super_admin": "Full platform control: user management, all admin permissions, feedback management",
    "admin": "Monitoring, role clusters, feedback management, view all resumes and sales performance",
    "reviewer": "Review jobs, manage pipeline, score resumes, submit feedback",
    "viewer": "View-only access to jobs, companies, and analytics, submit feedback",
}


@router.get("")
async def list_users(
    user: User = Depends(require_role("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """List all users (super_admin only)."""
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    users = result.scalars().all()
    return {
        "items": [
            {
                "id": str(u.id),
                "email": u.email,
                "name": u.name,
                "avatar_url": u.avatar_url or "",
                "role": u.role,
                "is_active": u.is_active,
                "has_password": bool(u.password_hash),
                "has_google": bool(u.google_sub),
                "created_at": u.created_at.isoformat() if u.created_at else None,
                "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
            }
            for u in users
        ],
        "total": len(users),
    }


# Regression finding 127: the role-change + is_active guards in
# `update_user` only counted `role == "admin"`, never `super_admin`.
# If a super_admin demoted themselves or the only remaining super_admin
# to a lower role, the platform permanently lost access to every
# super_admin-only endpoint (list users, PATCH, DELETE, force-reset
# password). `deactivate_user` below already got this right — it
# counted `User.role.in_(["admin", "super_admin"])`. This helper
# lifts the correct query into one place so the three call sites
# can't drift again, and counts ACTIVE privileged users (a
# deactivated admin can't log in, so they don't count toward the "can
# we still administer this platform" question).
async def _count_active_admins_or_super(
    db: AsyncSession, exclude_id: UUID | None = None
) -> int:
    """Count active users whose role is admin or super_admin.

    `exclude_id` lets the caller ask "how many will remain AFTER I
    demote/deactivate this one?" — useful because the existing row
    hasn't been mutated yet at call time, so we'd otherwise count it
    as if it were still a full-privilege user.
    """
    query = select(func.count()).select_from(User).where(
        User.role.in_(["admin", "super_admin"]),
        User.is_active == True,  # noqa: E712
    )
    if exclude_id is not None:
        query = query.where(User.id != exclude_id)
    return (await db.execute(query)).scalar() or 0


@router.patch("/{user_id}")
async def update_user(
    user_id: UUID,
    body: UserUpdate,
    request: Request,
    admin: User = Depends(require_role("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """Update user role or active status (super_admin only)."""
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    # F127: block self-role-change. A super_admin PATCH'ing their own
    # role to viewer is still technically possible via this endpoint
    # even with the "last admin/super_admin" count guard below
    # (because the count check would pass if there's another active
    # super_admin), but it's a surprising footgun — roles should only
    # be changed by ANOTHER privileged user, not by the account being
    # demoted. Same pattern as the self-deactivate block below.
    if body.role is not None and target.id == admin.id and body.role != target.role:
        raise HTTPException(
            status_code=400,
            detail="Cannot change your own role — ask another super_admin",
        )

    if body.role is not None:
        if body.role not in VALID_ROLES:
            raise HTTPException(status_code=400, detail=f"Role must be one of: {', '.join(VALID_ROLES)}")
        # F127: last-privileged-user guard covers BOTH admin and
        # super_admin. Pre-fix, demoting a super_admin to viewer
        # passed silently because the guard only counted `admin`.
        # Also uses `exclude_id=target.id` so the count reflects
        # post-mutation state (how many active admins/super_admins
        # would remain AFTER this change), not current state.
        downgrading = (
            target.role in ("admin", "super_admin")
            and body.role not in ("admin", "super_admin")
        )
        if downgrading:
            remaining = await _count_active_admins_or_super(db, exclude_id=target.id)
            if remaining < 1:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot remove the last admin/super_admin",
                )
        target.role = body.role

    if body.is_active is not None:
        # Prevent deactivating self
        if target.id == admin.id and not body.is_active:
            raise HTTPException(status_code=400, detail="Cannot deactivate your own account")
        # F127: last-privileged-user guard now counts both admin and
        # super_admin (pre-fix, deactivating the only super_admin
        # went through because the guard filtered to `role=admin`).
        if target.role in ("admin", "super_admin") and not body.is_active:
            remaining = await _count_active_admins_or_super(db, exclude_id=target.id)
            if remaining < 1:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot deactivate the last admin/super_admin",
                )
        target.is_active = body.is_active

    await db.commit()
    await db.refresh(target)

    await log_action(
        db, admin,
        action="user.update",
        resource="user",
        request=request,
        metadata={"target_user_id": str(user_id), "fields": list(body.model_dump(exclude_unset=True).keys())},
    )

    return {
        "id": str(target.id),
        "email": target.email,
        "name": target.name,
        "role": target.role,
        "is_active": target.is_active,
    }


@router.delete("/{user_id}")
async def deactivate_user(
    user_id: UUID,
    request: Request,
    admin: User = Depends(require_role("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate a user (super_admin only). Data is never deleted."""
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot deactivate your own account")

    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    if target.role in ("admin", "super_admin"):
        # F127: lifted into the shared helper so the three call sites
        # (PATCH role change, PATCH is_active, DELETE) can't drift
        # apart. Excludes `target.id` so we measure how many would
        # remain AFTER this deactivation.
        remaining = await _count_active_admins_or_super(db, exclude_id=target.id)
        if remaining < 1:
            raise HTTPException(status_code=400, detail="Cannot deactivate the last admin/super_admin")

    target.is_active = False
    await db.commit()

    await log_action(
        db, admin,
        action="user.deactivate",
        resource="user",
        request=request,
        metadata={"target_user_id": str(user_id), "email": target.email},
    )

    return {"ok": True, "message": f"User {target.email} deactivated (data preserved)"}


@router.post("/{user_id}/reset-password")
async def admin_reset_password(
    user_id: UUID,
    request: Request,
    admin: User = Depends(require_role("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """Super admin force-resets a user's password and returns a temporary one."""
    import secrets
    from app.api.v1.auth import _hash_password

    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    temp_password = secrets.token_urlsafe(12)
    target.password_hash = _hash_password(temp_password)
    target.password_reset_token = None
    target.password_reset_expires = None
    # F247 regression fix: flag the user so the next login forces a
    # change-password screen. Without this, the temp password stays
    # valid indefinitely — the admin shares it, the user logs in,
    # and the deterministic credential remains in circulation. The
    # ``change_password`` handler clears the flag once the user
    # picks a new password.
    target.must_change_password = True
    await db.commit()

    await log_action(
        db, admin,
        action="user.password_reset",
        resource="user",
        request=request,
        metadata={"target_user_id": str(user_id), "email": target.email},
    )

    return {
        "ok": True,
        "temp_password": temp_password,
        "message": f"Temporary password set for {target.email}. User should change it on next login.",
    }


@router.get("/roles")
async def get_roles(user: User = Depends(require_role("admin"))):
    """Get available authorization roles and their descriptions."""
    return {
        "roles": [
            {"name": name, "description": desc}
            for name, desc in ROLE_DESCRIPTIONS.items()
        ]
    }
