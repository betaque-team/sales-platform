"""Auth dependencies for route protection."""

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from jose import jwt, JWTError
from uuid import UUID

from app.config import get_settings
from app.database import get_db
from app.models.user import User
from app.models.resume import Resume
from app.utils.work_window import user_can_access_now

settings = get_settings()

# Endpoints that must remain reachable even when a user is outside
# their work-time window — the lock-out page itself, auth flows, and
# the user-facing extension-request submitter all need to keep
# functioning. Path prefixes are matched against ``request.url.path``.
#
# Kept narrow on purpose: anything not on this list goes through the
# 423 gate. New endpoints that should bypass enforcement (e.g. a
# future "I'm clocking out" endpoint) get added here explicitly.
WORK_WINDOW_ALLOWLIST_PREFIXES = (
    "/api/v1/auth/",            # login, logout, whoami, change-password
    "/api/v1/work-window/me",   # user reads own state + lists requests
)


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    """Extract and validate JWT from cookie or Authorization header.

    Also enforces per-user work-time windows: when the resolved user
    has ``work_window_enabled=True`` and ``now_ist`` is outside their
    shift (and no admin override is active), this raises **423 Locked**
    with a structured payload the frontend uses to render the lock-out
    screen. Admin / super_admin roles are exempt.

    The work-window check runs AFTER token validation so an unauth'd
    request still gets a 401 (not a misleading 423). It runs BEFORE
    the dependency returns so every protected endpoint sees a uniform
    "you can't be here right now" wall — no per-router sprinkling
    required.
    """
    token = request.cookies.get("session")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]

    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        user_id = UUID(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    result = await db.execute(select(User).where(User.id == user_id, User.is_active == True))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    # ── Work-time window enforcement ───────────────────────────────
    # Admins always pass — they need to reach admin UIs to extend a
    # locked-out user. Everyone else is gated unless the path is on
    # the allowlist (auth flows + the user's own work-window page).
    if user.role not in ("admin", "super_admin"):
        path = request.url.path
        on_allowlist = any(path.startswith(p) for p in WORK_WINDOW_ALLOWLIST_PREFIXES)
        if not on_allowlist and not user_can_access_now(user):
            # 423 Locked: the resource exists and the credential is
            # valid, but a temporal policy is blocking access. The
            # frontend distinguishes this from 401 (re-login) and 403
            # (privilege denied) — see ``Layout`` and ``LockedOutScreen``.
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail="Outside your work-time window",
            )

    return user


# Role hierarchy: higher roles inherit all lower-role permissions
ROLE_HIERARCHY = {
    "super_admin": {"super_admin", "admin", "reviewer", "viewer"},
    "admin": {"admin", "reviewer", "viewer"},
    "reviewer": {"reviewer", "viewer"},
    "viewer": {"viewer"},
}


def require_role(*roles: str):
    """Dependency factory: require user to have one of the specified roles.
    Uses role hierarchy — super_admin inherits admin, admin inherits reviewer, etc.
    """
    async def check(user: User = Depends(get_current_user)) -> User:
        user_permissions = ROLE_HIERARCHY.get(user.role, set())
        if not user_permissions.intersection(roles):
            # Regression finding 185: previously returned
            # `"Requires role: super_admin"` — naming the exact role
            # gave an attacker who held a viewer/reviewer token the
            # precise target name for privilege escalation. Generic
            # message here; the required role is still recorded in
            # server-side access logs for ops debugging.
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient privileges for this action",
            )
        return user
    return check


async def get_active_resume(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Resume | None:
    """Load the user's active resume, or None if not set."""
    if not user.active_resume_id:
        return None
    result = await db.execute(
        select(Resume).where(Resume.id == user.active_resume_id, Resume.user_id == user.id)
    )
    return result.scalar_one_or_none()
