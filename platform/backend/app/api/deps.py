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

settings = get_settings()


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    """Extract and validate JWT from cookie or Authorization header."""
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
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Requires role: {', '.join(roles)}")
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
