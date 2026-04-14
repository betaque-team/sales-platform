"""Authentication endpoints: email/password login, register, password management + Google OAuth2."""

import hashlib
import secrets
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from authlib.integrations.starlette_client import OAuth
from jose import jwt

from app.config import get_settings
from app.database import get_db
from app.models.user import User
from app.api.deps import get_current_user, require_role
from app.schemas.user import UserOut, UserCreate, ChangePassword, ResetPasswordRequest, ResetPasswordConfirm

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()

oauth = OAuth()
if settings.google_client_id:
    oauth.register(
        name="google",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )

VALID_ROLES = {"admin", "reviewer", "viewer"}


def _hash_password(password: str) -> str:
    """SHA-256 hash with salt from jwt_secret. For production use bcrypt instead."""
    salted = f"{settings.jwt_secret}:{password}"
    return hashlib.sha256(salted.encode()).hexdigest()


def _verify_password(password: str, password_hash: str) -> bool:
    return _hash_password(password) == password_hash


def _mint_jwt(user: User) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=settings.jwt_expire_hours)
    return jwt.encode(
        {"sub": str(user.id), "email": user.email, "role": user.role, "exp": exp},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


@router.post("/login")
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Email/password login. Returns JWT in a cookie and as JSON."""
    result = await db.execute(select(User).where(User.email == body.email, User.is_active == True))
    user = result.scalar_one_or_none()

    if not user or not user.password_hash:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not _verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(user)

    token = _mint_jwt(user)
    response = JSONResponse(content={
        "token": token,
        "user": {
            "id": str(user.id),
            "email": user.email,
            "name": user.name,
            "role": user.role,
            "avatar_url": user.avatar_url,
        },
    })
    response.set_cookie(
        key="session", value=token,
        httponly=True, samesite="lax", secure=True,
        max_age=settings.jwt_expire_hours * 3600,
    )
    return response


@router.post("/register")
async def register(
    body: UserCreate,
    user: User = Depends(require_role("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """Register a new user (super_admin only)."""
    if body.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Role must be one of: {', '.join(VALID_ROLES)}")

    if len(body.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    import uuid
    new_user = User(
        id=uuid.uuid4(),
        email=body.email,
        name=body.name,
        password_hash=_hash_password(body.password),
        role=body.role,
        is_active=True,
        created_at=datetime.now(timezone.utc),
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    return {
        "id": str(new_user.id),
        "email": new_user.email,
        "name": new_user.name,
        "role": new_user.role,
        "is_active": new_user.is_active,
        "created_at": new_user.created_at.isoformat(),
    }


@router.post("/change-password")
async def change_password(
    body: ChangePassword,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Change current user's password."""
    if not user.password_hash:
        raise HTTPException(status_code=400, detail="Account uses Google OAuth, no password to change")

    if not _verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    if len(body.new_password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")

    user.password_hash = _hash_password(body.new_password)
    await db.commit()
    return {"ok": True, "message": "Password changed successfully"}


@router.post("/reset-password/request")
async def request_password_reset(
    body: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """Request a password reset token. Returns token directly (in production, send via email)."""
    result = await db.execute(select(User).where(User.email == body.email, User.is_active == True))
    user = result.scalar_one_or_none()

    if not user:
        # Don't reveal whether the email exists
        return {"ok": True, "message": "If the email exists, a reset token has been generated"}

    token = secrets.token_urlsafe(32)
    user.password_reset_token = _hash_password(token)
    user.password_reset_expires = datetime.now(timezone.utc) + timedelta(hours=1)
    await db.commit()

    # In production, send this via email instead
    return {"ok": True, "message": "Reset token generated", "token": token}


@router.post("/reset-password/confirm")
async def confirm_password_reset(
    body: ResetPasswordConfirm,
    db: AsyncSession = Depends(get_db),
):
    """Confirm password reset using token."""
    if len(body.new_password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")

    token_hash = _hash_password(body.token)
    result = await db.execute(
        select(User).where(
            User.password_reset_token == token_hash,
            User.is_active == True,
        )
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    if user.password_reset_expires and user.password_reset_expires < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Reset token has expired")

    user.password_hash = _hash_password(body.new_password)
    user.password_reset_token = None
    user.password_reset_expires = None
    await db.commit()

    return {"ok": True, "message": "Password reset successfully"}


@router.get("/google")
async def google_login(request: Request):
    if not settings.google_client_id:
        raise HTTPException(status_code=501, detail="Google OAuth not configured")
    redirect_uri = f"{settings.api_url}/api/v1/auth/callback"
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/callback")
async def google_callback(request: Request, db: AsyncSession = Depends(get_db)):
    token = await oauth.google.authorize_access_token(request)
    userinfo = token.get("userinfo")
    if not userinfo:
        raise HTTPException(status_code=400, detail="Failed to get user info from Google")

    email = userinfo["email"]
    google_sub = userinfo["sub"]

    # Check allow-list (if configured)
    allowed = settings.allowed_email_list
    if allowed and email not in allowed:
        raise HTTPException(status_code=403, detail="Email not authorized")

    # Find existing user by google_sub or email
    result = await db.execute(select(User).where(User.google_sub == google_sub))
    user = result.scalar_one_or_none()

    if not user:
        # Check if admin pre-created this user by email (invite-only)
        result = await db.execute(select(User).where(User.email == email, User.is_active == True))
        user = result.scalar_one_or_none()
        if user:
            # Link Google account to existing invited user
            user.google_sub = google_sub

    if not user:
        # No pre-created account — reject (invite-only mode)
        return RedirectResponse(url=settings.app_url + "/login?error=not_invited")

    user.last_login_at = datetime.now(timezone.utc)
    user.name = userinfo.get("name", user.name)
    user.avatar_url = userinfo.get("picture", user.avatar_url)

    await db.commit()
    await db.refresh(user)

    # Set JWT cookie and redirect to frontend
    jwt_token = _mint_jwt(user)
    response = RedirectResponse(url=settings.app_url + "/")
    response.set_cookie(
        key="session", value=jwt_token,
        httponly=True, samesite="lax", secure=True,
        max_age=settings.jwt_expire_hours * 3600,
    )
    return response


@router.get("/me")
async def get_me(user: User = Depends(get_current_user)):
    return UserOut.from_user(user)


@router.post("/logout")
async def logout():
    response = RedirectResponse(url=settings.app_url)
    response.delete_cookie("session")
    return response
