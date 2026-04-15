"""Audit log read API (admin-only).

Regression finding 61: forensic visibility for the security-sensitive
actions recorded by `app.utils.audit.log_action`. Writes happen
implicitly from the endpoints that need to be audited (currently the
three `/export/*` routes); this module is the read side.

Scope decisions
---------------
- **Admin-only.** Audit logs reveal who exported what and when;
  non-admins have no business reading them. Uses the same
  `require_role("admin")` gate as the export endpoints themselves.
- **Filter by action / resource / user / time.** The dominant
  incident-response queries are (a) "what did user X do in the
  last 24h" and (b) "who exported contacts since yesterday". Both
  are covered by the intersection of filters below.
- **Paginated with a hard cap** (`page_size <= 200`). An unbounded
  response would defeat the point of having the log — an attacker
  who breached an admin could scrape the audit table in one request.
- **No write/update/delete.** Audit rows are append-only by design.
  Retention trim is operations (separate cron/manual job) — not an
  API the web layer exposes.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_role
from app.database import get_db
from app.models.audit_log import AuditLog
from app.models.user import User

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("")
async def list_audit_logs(
    action: str | None = None,
    resource: str | None = None,
    user_id: UUID | None = None,
    # Both bounds are ISO datetime strings. Parse via FastAPI's
    # native datetime coercion — a malformed value becomes 422.
    since: datetime | None = None,
    until: datetime | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    _admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """List audit log entries, most-recent first.

    Returns the standard pagination envelope used across the API:
    `{items, total, page, page_size, total_pages}`. Each item
    includes the denormalized actor fields (email, name) so the
    frontend doesn't need a second round-trip.
    """
    base = select(AuditLog)

    if action:
        base = base.where(AuditLog.action == action)
    if resource:
        base = base.where(AuditLog.resource == resource)
    if user_id:
        base = base.where(AuditLog.user_id == user_id)
    if since:
        base = base.where(AuditLog.created_at >= since)
    if until:
        base = base.where(AuditLog.created_at <= until)

    # Total count for pagination. Build off the same filter chain
    # but drop the ORDER BY / eager-load so the count query stays
    # cheap — Postgres can use the indexes directly.
    total_result = await db.execute(
        select(func.count()).select_from(base.subquery())
    )
    total = total_result.scalar() or 0

    rows_result = await db.execute(
        base.order_by(AuditLog.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = rows_result.scalars().all()

    items = []
    for row in rows:
        actor = row.user  # eagerly loaded via lazy="joined"
        items.append({
            "id": str(row.id),
            "user": {
                "id": str(actor.id) if actor else None,
                "email": actor.email if actor else None,
                "name": actor.name if actor else None,
            },
            "action": row.action,
            "resource": row.resource,
            "ip_address": row.ip_address,
            "user_agent": row.user_agent,
            "metadata": row.metadata_json or {},
            "created_at": row.created_at.isoformat() if row.created_at else None,
        })

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if total else 0,
    }


@router.get("/{audit_id}")
async def get_audit_log(
    audit_id: UUID,
    _admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Fetch a single audit entry. Useful for deep-linking from an
    incident ticket directly to the underlying event.
    """
    row = (await db.execute(
        select(AuditLog).where(AuditLog.id == audit_id)
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Audit entry not found")

    actor = row.user
    return {
        "id": str(row.id),
        "user": {
            "id": str(actor.id) if actor else None,
            "email": actor.email if actor else None,
            "name": actor.name if actor else None,
            "role": actor.role if actor else None,
        },
        "action": row.action,
        "resource": row.resource,
        "ip_address": row.ip_address,
        "user_agent": row.user_agent,
        "metadata": row.metadata_json or {},
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
