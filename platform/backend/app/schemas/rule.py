"""Pydantic schemas for Role Rule endpoints."""

from pydantic import BaseModel
from datetime import datetime
from uuid import UUID


class RoleRuleOut(BaseModel):
    id: UUID
    cluster: str
    base_role: str
    keywords: list[str]
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class RoleRuleCreate(BaseModel):
    cluster: str
    base_role: str
    keywords: list[str]
    is_active: bool = True


class RoleRuleUpdate(BaseModel):
    cluster: str | None = None
    base_role: str | None = None
    keywords: list[str] | None = None
    is_active: bool | None = None
