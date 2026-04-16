"""Pydantic schemas for Role Rule endpoints."""

from pydantic import BaseModel, field_validator
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


# Regression finding 178: `list[str]` accepts the empty list, so
# `POST /rules {"cluster":"infra","base_role":"test","keywords":[]}`
# returned 201 with a rule that could never match anything — dead weight
# in the admin UI and, worse, confusing for whoever encountered it later
# wondering why a rule wasn't firing. `null` was already rejected by the
# list_type validator; `[]` now joins it at 422. Also strip out empty
# strings/whitespace-only entries inside the list (same "might as well
# not have a rule" result).
def _require_non_empty_keywords(v: list[str]) -> list[str]:
    if v is None:
        return v
    cleaned = [k.strip() for k in v if isinstance(k, str) and k.strip()]
    if not cleaned:
        raise ValueError("keywords must contain at least one non-empty entry")
    return cleaned


class RoleRuleCreate(BaseModel):
    cluster: str
    base_role: str
    keywords: list[str]
    is_active: bool = True

    @field_validator("keywords")
    @classmethod
    def _check_keywords(cls, v):
        return _require_non_empty_keywords(v)


class RoleRuleUpdate(BaseModel):
    cluster: str | None = None
    base_role: str | None = None
    keywords: list[str] | None = None
    is_active: bool | None = None

    @field_validator("keywords")
    @classmethod
    def _check_keywords(cls, v):
        # PATCH: allow `keywords` to be omitted entirely, but if it IS
        # provided, hold it to the same non-empty rule as POST.
        if v is None:
            return v
        return _require_non_empty_keywords(v)
