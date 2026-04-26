from pydantic import BaseModel, EmailStr
from datetime import datetime
from uuid import UUID


class UserOut(BaseModel):
    id: UUID
    email: str
    name: str
    avatar_url: str
    role: str
    is_active: bool
    active_resume_id: UUID | None = None
    has_password: bool = False
    # F247: surfaced so the frontend can route to the change-password
    # screen when a super-admin has force-reset the user's password.
    # Defaults to False so old clients that ignore the field aren't
    # affected, but the new client checks it after every login + every
    # ``/auth/me`` call and locks navigation until the user changes it.
    must_change_password: bool = False
    created_at: datetime
    last_login_at: datetime | None

    model_config = {"from_attributes": True}

    @classmethod
    def from_user(cls, user) -> "UserOut":
        return cls(
            id=user.id,
            email=user.email,
            name=user.name,
            avatar_url=user.avatar_url or "",
            role=user.role,
            is_active=user.is_active,
            active_resume_id=user.active_resume_id,
            has_password=bool(user.password_hash),
            # ``getattr`` with a False default keeps this safe to call
            # against any User-shaped object that predates the column
            # (test factories, etc.). On real ORM rows the column is
            # NOT NULL so the attribute always exists.
            must_change_password=getattr(user, "must_change_password", False),
            created_at=user.created_at,
            last_login_at=user.last_login_at,
        )


class UserUpdate(BaseModel):
    role: str | None = None
    is_active: bool | None = None


class UserCreate(BaseModel):
    email: EmailStr
    name: str
    password: str
    role: str = "viewer"


class ChangePassword(BaseModel):
    current_password: str
    new_password: str


class ResetPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordConfirm(BaseModel):
    token: str
    new_password: str
