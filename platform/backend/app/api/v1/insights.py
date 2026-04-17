"""AI Intelligence API endpoints (F237).

Three routes:

  GET  /api/v1/insights/me          — current user's latest insights
  GET  /api/v1/insights/product     — admin-only platform insights
  POST /api/v1/insights/{id}/action — admin marks a product insight
                                      actioned/dismissed/duplicate
  POST /api/v1/insights/run         — admin manual trigger (debug /
                                      "I just shipped a fix, recompute now")

Auth model:
  - /me:          any authenticated user; returns ONLY their own row
  - /product/*:   require_role("admin"); rows are platform-wide
  - /run:         require_role("admin"); fires the Celery task

Empty-result behavior: `/me` returns `{"latest": null, "history": []}`
when no insights have been generated for this user yet (e.g. they
joined after the last beat run, or have no recent activity). The
frontend renders an "Insights will appear after the next scheduled
run (Mon/Thu 04:00 UTC)" empty state — friendlier than a 404.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_role
from app.database import get_db
from app.models.insight import UserInsight, ProductInsight
from app.models.user import User
from app.utils.audit import log_action


router = APIRouter(prefix="/insights", tags=["insights"])


# ── User insights ────────────────────────────────────────────────────────────

@router.get("/me")
async def get_my_insights(
    history: int = Query(0, ge=0, le=10),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the current user's latest AI insight bundle.

    Default: returns just the latest run. Pass `?history=N` (0-10) to
    also include the prior N runs so the frontend can show a "Compare
    to last week" toggle.

    Shape:
      {
        "latest": {
          "generation_id": ...,
          "generated_at": ISO,
          "insights": [{title, body, severity, category, action_link?}, ...],
          "model_version": ...,
          "prompt_version": ...
        } | null,
        "history": [ {same shape...} ]  // length 0..N
      }
    """
    rows = (await db.execute(
        select(UserInsight)
        .where(UserInsight.user_id == user.id)
        .order_by(UserInsight.generated_at.desc())
        .limit(1 + history)
    )).scalars().all()

    def _shape(r: UserInsight) -> dict:
        return {
            "generation_id": str(r.generation_id),
            "generated_at": r.generated_at.isoformat() if r.generated_at else None,
            "insights": r.insights or [],
            "model_version": r.model_version,
            "prompt_version": r.prompt_version,
        }

    return {
        "latest": _shape(rows[0]) if rows else None,
        "history": [_shape(r) for r in rows[1:]] if len(rows) > 1 else [],
    }


# ── Product insights (admin-only) ────────────────────────────────────────────

@router.get("/product", dependencies=[Depends(require_role("admin"))])
async def list_product_insights(
    status: Literal["pending", "actioned", "dismissed", "all"] = "pending",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """List product-improvement insights for admin triage.

    Default filter is `pending` (no `actioned_at` yet) — what the
    admin actually needs to look at. `actioned` / `dismissed` are
    available for "show me what we've already triaged"; `all` is the
    catch-all.
    """
    query = select(ProductInsight)
    if status == "pending":
        query = query.where(ProductInsight.actioned_at.is_(None))
    elif status == "actioned":
        query = query.where(ProductInsight.actioned_status == "actioned")
    elif status == "dismissed":
        query = query.where(ProductInsight.actioned_status.in_(["dismissed", "duplicate"]))
    # status == "all": no filter

    # Sort: severity DESC (high first), then generated_at DESC (newest first)
    severity_rank = func.case(
        (ProductInsight.severity == "high", 3),
        (ProductInsight.severity == "medium", 2),
        (ProductInsight.severity == "low", 1),
        else_=0,
    )
    query = query.order_by(severity_rank.desc(), ProductInsight.generated_at.desc())

    total = (await db.execute(
        select(func.count()).select_from(query.subquery())
    )).scalar() or 0
    query = query.offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(query)).scalars().all()

    items = [
        {
            "id": str(r.id),
            "generation_id": str(r.generation_id),
            "title": r.title,
            "body": r.body,
            "category": r.category,
            "severity": r.severity,
            "generated_at": r.generated_at.isoformat() if r.generated_at else None,
            "actioned_at": r.actioned_at.isoformat() if r.actioned_at else None,
            "actioned_status": r.actioned_status,
            "actioned_note": r.actioned_note,
            "actioned_by": str(r.actioned_by) if r.actioned_by else None,
            "model_version": r.model_version,
            "prompt_version": r.prompt_version,
        }
        for r in rows
    ]
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


class InsightActionBody(BaseModel):
    """Body for POST /insights/{id}/action."""

    # F157: reject unknown fields so a typo'd `staus` doesn't get
    # silently dropped.
    model_config = ConfigDict(extra="forbid")

    # actioned: we shipped a fix based on this. dismissed: we
    # decided not to act. duplicate: this is the same as another
    # row we already actioned.
    status: Literal["actioned", "dismissed", "duplicate"]
    note: str | None = Field(default=None, max_length=2000)


@router.post("/{insight_id}/action", dependencies=[Depends(require_role("admin"))])
async def action_product_insight(
    insight_id: UUID,
    body: InsightActionBody,
    request: Request,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Mark a product insight as actioned / dismissed / duplicate.

    The action gets fed into the next product-insights run as context
    so the LLM can either (a) score whether the actioned fix moved
    the underlying metric, or (b) avoid re-suggesting a dismissed
    item. Closes the AI-improving-the-product loop.
    """
    row = (await db.execute(
        select(ProductInsight).where(ProductInsight.id == insight_id)
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Insight not found")
    row.actioned_at = datetime.now(timezone.utc)
    row.actioned_by = admin.id
    row.actioned_status = body.status
    row.actioned_note = body.note
    await db.commit()
    await db.refresh(row)

    await log_action(
        db, admin,
        action=f"product_insight.{body.status}",
        resource="product_insight",
        request=request,
        metadata={
            "insight_id": str(insight_id),
            "title": row.title,
            "category": row.category,
            "severity": row.severity,
            "note_len": len(body.note or ""),
        },
    )
    return {
        "id": str(row.id),
        "actioned_status": row.actioned_status,
        "actioned_at": row.actioned_at.isoformat(),
        "actioned_note": row.actioned_note,
    }


# ── Manual trigger (admin) ───────────────────────────────────────────────────

@router.post("/run", dependencies=[Depends(require_role("admin"))])
async def trigger_insights_run(request: Request, admin: User = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)):
    """Manually fire the weekly insights Celery task.

    Useful for: smoke-testing the prompt after a code change, or
    "I just shipped a fix mentioned in last week's product insights,
    recompute now to see if the metric moved" workflows. Without this
    button the admin would have to wait until Mon/Thu 04:00 UTC.

    Logs the manual trigger as `insights.manual_run` in the audit log
    so accidental triggers (or abuse) is traceable.
    """
    from app.workers.tasks.ai_insights_task import run_weekly_insights
    task = run_weekly_insights.delay()

    await log_action(
        db, admin,
        action="insights.manual_run",
        resource="insights",
        request=request,
        metadata={"task_id": task.id},
    )
    return {"task_id": task.id, "status": "queued"}
