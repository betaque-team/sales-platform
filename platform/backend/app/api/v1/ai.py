"""Cross-feature AI utility endpoints (usage snapshot, etc).

Regression finding 236: per-feature AI usage was previously surfaced
only via `GET /resume/ai-usage` which returned customize-only stats
in flat top-level keys. Adding cover-letter and interview-prep meant
either:

  (a) Bolting more keys onto `/resume/ai-usage` (which lives under
      the resume router and is awkward to discover), or
  (b) Creating a dedicated cross-cutting `/ai/*` namespace that any
      future AI feature can extend without touching unrelated routers.

Picked (b). This module is the home for AI-wide endpoints; the
existing `/resume/ai-usage` stays as a backwards-compatible alias
that returns the same `customize` block in its legacy flat shape so
the current frontend keeps working without a release-coordination
dance.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.user import User
from app.utils.ai_rate_limit import usage_snapshot

router = APIRouter(prefix="/ai", tags=["ai"])


@router.get("/usage")
async def get_usage(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Per-feature daily AI usage for the current user.

    Returns:
      {
        "has_api_key": true,
        "reset_at_utc": "2026-04-17T00:00:00Z",
        "features": {
          "customize": {"used": 3, "limit": 10, "remaining": 7},
          "cover_letter": {"used": 1, "limit": 30, "remaining": 29},
          "interview_prep": {"used": 0, "limit": 10, "remaining": 10}
        }
      }

    `reset_at_utc` is the START of today's window — the next reset is
    at +24h. Frontend can render "Resets in 4h 23m" by computing
    `(reset_at_utc + 24h) - now`.
    """
    return await usage_snapshot(db, user)
