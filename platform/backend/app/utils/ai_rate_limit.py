"""Shared per-feature AI rate-limit + audit-log helpers.

Regression finding 236: cover-letter and interview-prep AI endpoints
shipped without rate limits or audit trails — only the customize
endpoint had F170's daily-cap pattern. A motivated user (or
automation hitting the API on their behalf) could spam the other two
indefinitely with no quota guard. This module lifts the count + cap +
log pattern out of `resume.py::customize_resume_for_job` so all three
handlers use one source of truth.

Pattern:

  from app.utils.ai_rate_limit import check_ai_quota, log_ai_call
  from app.models.resume import AI_FEATURE_COVER_LETTER

  # Pre-call: 429 if over budget. Returns the count *before* this
  # call so the handler can include it in the log row.
  used_today = await check_ai_quota(db, user, AI_FEATURE_COVER_LETTER)

  # ... call the AI, get result ...

  # Post-call: log success/failure + token counts. Failure rows do
  # NOT count against the quota (per F170/F203) — the F-key here is
  # the `success` flag the underlying log query already filters on.
  await log_ai_call(
      db, user, AI_FEATURE_COVER_LETTER,
      job_id=job.id,
      input_tokens=result.get("input_tokens", 0),
      output_tokens=result.get("output_tokens", 0),
      success=not result.get("error", False),
  )

The two-call shape (check then log) is deliberate: it lets the handler
dispatch to Claude between the two steps and logs the actual token
usage. A combined "atomic" check_and_log would have to either log
before the call (counting failures, F170 regression) or after (race
window where N concurrent calls all see used=quota-1 and all proceed).
The current shape accepts the rare race — at worst, two concurrent
calls land at user.cap+1 and both succeed; that's a UX upside, not a
budget hole.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.resume import (
    AICustomizationLog,
    AI_FEATURE_CUSTOMIZE,
    AI_FEATURE_COVER_LETTER,
    AI_FEATURE_INTERVIEW_PREP,
    AI_FEATURE_VALUES,
)
from app.models.user import User


def _limit_for(feature: str) -> int:
    """Per-feature daily cap from config.

    Centralised here (not duplicated at each call site) so a config
    change rolls through to all three handlers automatically.
    """
    settings = get_settings()
    if feature == AI_FEATURE_CUSTOMIZE:
        return settings.ai_daily_limit_per_user
    if feature == AI_FEATURE_COVER_LETTER:
        return settings.ai_cover_letter_daily_limit_per_user
    if feature == AI_FEATURE_INTERVIEW_PREP:
        return settings.ai_interview_prep_daily_limit_per_user
    raise ValueError(f"Unknown AI feature: {feature!r}")


def _today_start_utc() -> datetime:
    """Midnight UTC for the rate-limit window.

    F236 explicit choice: same reset cadence as the existing customize
    flow (midnight UTC) for consistency. Documented in docs/AI_USAGE.md.
    """
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


async def count_ai_calls_today(
    db: AsyncSession, user: User, feature: str
) -> int:
    """Count successful AI calls of `feature` by `user` since midnight UTC.

    Only `success=True` rows count (F170/F203) — failed calls (no api
    key, upstream 5xx, timeout, parse error) don't burn quota. The
    composite index `ix_ai_customization_logs_user_feature_created`
    keeps this O(1)-cardinality even after the table grows.
    """
    if feature not in AI_FEATURE_VALUES:
        raise ValueError(f"Unknown AI feature: {feature!r}")
    today_start = _today_start_utc()
    return (await db.execute(
        select(func.count(AICustomizationLog.id)).where(
            AICustomizationLog.user_id == user.id,
            AICustomizationLog.feature == feature,
            AICustomizationLog.created_at >= today_start,
            AICustomizationLog.success == True,  # noqa: E712
        )
    )).scalar() or 0


async def check_ai_quota(
    db: AsyncSession, user: User, feature: str
) -> int:
    """Raise 429 if the user is over today's limit for `feature`.

    Returns the current `used_today` count so the caller can include
    it in their handler's log row (avoids a second SELECT).

    The 429 response includes the per-feature limit + reset time in the
    detail string so the frontend can render a useful error toast
    without a second round-trip to /ai/usage.
    """
    used_today = await count_ai_calls_today(db, user, feature)
    limit = _limit_for(feature)
    if used_today >= limit:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Daily {feature.replace('_', ' ')} limit reached "
                f"({limit}/day). Resets at midnight UTC."
            ),
            headers={
                # Standard `Retry-After` header so well-behaved clients
                # (curl --retry, browser fetch with retry libs, monitoring
                # tools) honor the quota window. Value is seconds until
                # midnight UTC. Capped at 86400 by definition.
                "Retry-After": str(_seconds_until_midnight_utc()),
            },
        )
    return used_today


def _seconds_until_midnight_utc() -> int:
    """Whole-second countdown to the next UTC midnight reset.

    UTC has no DST so `timedelta(days=1)` + `replace(hour=0)` is
    safe — no timezone-walking drift.
    """
    now = datetime.now(timezone.utc)
    next_midnight = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return max(1, int((next_midnight - now).total_seconds()))


async def log_ai_call(
    db: AsyncSession,
    user: User,
    feature: str,
    *,
    job_id: UUID | None = None,
    resume_id: UUID | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    success: bool = False,
) -> AICustomizationLog:
    """Persist one row to `ai_customization_logs`.

    `success=False` rows DO get written (so we can debug failure
    rates) but they do NOT count against the user's daily quota
    because `count_ai_calls_today` filters on `success=True`. This is
    deliberate per F170/F203 — quota is for "AI work the user
    benefited from", not "calls the user made".

    Caller passes the token counts from the Anthropic response usage
    block when available; pass 0 if the call never reached Claude
    (no api key, upstream auth fail, etc).
    """
    if feature not in AI_FEATURE_VALUES:
        raise ValueError(f"Unknown AI feature: {feature!r}")
    row = AICustomizationLog(
        user_id=user.id,
        resume_id=resume_id,
        job_id=job_id,
        feature=feature,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        success=success,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def usage_snapshot(db: AsyncSession, user: User) -> dict:
    """Return per-feature usage stats for the current user.

    Powers the new `GET /api/v1/ai/usage` endpoint (F236). Single
    query with GROUP BY rather than three separate counts — one round
    trip, three numbers back.
    """
    today_start = _today_start_utc()
    rows = (await db.execute(
        select(
            AICustomizationLog.feature,
            func.count(AICustomizationLog.id),
        ).where(
            AICustomizationLog.user_id == user.id,
            AICustomizationLog.created_at >= today_start,
            AICustomizationLog.success == True,  # noqa: E712
        ).group_by(AICustomizationLog.feature)
    )).all()
    used_by_feature = {row[0]: int(row[1]) for row in rows}

    settings = get_settings()
    has_api_key = bool(settings.anthropic_api_key.get_secret_value())

    def _block(feature: str, limit: int) -> dict:
        used = used_by_feature.get(feature, 0)
        return {
            "used": used,
            "limit": limit,
            "remaining": max(0, limit - used),
        }

    return {
        "has_api_key": has_api_key,
        "reset_at_utc": (
            _today_start_utc().isoformat().replace("+00:00", "Z")
        ),  # Today's window started here; next reset is +24h.
        "features": {
            AI_FEATURE_CUSTOMIZE: _block(
                AI_FEATURE_CUSTOMIZE, settings.ai_daily_limit_per_user
            ),
            AI_FEATURE_COVER_LETTER: _block(
                AI_FEATURE_COVER_LETTER,
                settings.ai_cover_letter_daily_limit_per_user,
            ),
            AI_FEATURE_INTERVIEW_PREP: _block(
                AI_FEATURE_INTERVIEW_PREP,
                settings.ai_interview_prep_daily_limit_per_user,
            ),
        },
    }
