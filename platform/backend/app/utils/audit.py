"""Audit-log write helper for security-sensitive actions.

Regression finding 61 second-half: forensic record of bulk exports and
other sensitive actions. The role-gate for `/export/*` landed earlier;
this module is how endpoints record the fact that an export happened
so a compromised admin account still leaves a trail.

Design
------
- **Fail-open**: an audit write failure must NOT break the caller's
  flow. Exports stream CSV — by the time we call `log_action` the
  DB read is done and the user is about to receive bytes. If the
  audit commit fails (transient Redis-less-than-Postgres hiccup,
  disk pressure, etc.) we log a warning and the export continues.
- **Own commit**: commits inside the helper so the audit row is
  durable before the StreamingResponse closes the request.
  Callers' sessions are read-only in practice for exports, so
  there's no competing transaction.
- **Request-optional**: `request` is keyword-only because some
  callers (backfill scripts, admin CLI) won't have one. IP and
  UA are filled from the request when present.
- **No PII in metadata**: `metadata` stores filter values and row
  counts, not the exported bytes themselves. If the export rows
  change, we can re-query; but the audit row is a record of the
  event, not a copy of the payload.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.user import User

logger = logging.getLogger(__name__)


# Cap on the stored `user_agent` value — matches the column definition
# in `models/audit_log.py`. Truncate defensively rather than raise.
_MAX_USER_AGENT_LEN = 500


def _client_ip(request: Request | None) -> str | None:
    """Best-effort client IP extraction.

    Preference order: the first entry of `X-Forwarded-For` (set by
    the nginx reverse proxy on prod), then `X-Real-IP`, then the
    direct socket peer. Returns None if we can't determine it
    (e.g., test client without transport metadata).
    """
    if request is None:
        return None
    xff = request.headers.get("x-forwarded-for")
    if xff:
        # XFF can be a comma-separated chain — first hop is the
        # originating client, later hops are proxies. We want the
        # originator.
        first = xff.split(",", 1)[0].strip()
        if first:
            return first[:45]
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()[:45]
    # `request.client` is None in some TestClient configurations.
    if request.client and request.client.host:
        return request.client.host[:45]
    return None


def _user_agent(request: Request | None) -> str | None:
    if request is None:
        return None
    ua = request.headers.get("user-agent")
    if not ua:
        return None
    return ua[:_MAX_USER_AGENT_LEN]


async def log_action(
    session: AsyncSession,
    user: User,
    action: str,
    resource: str,
    *,
    request: Request | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditLog | None:
    """Persist an audit row. Returns the created row, or None if the
    write failed.

    Usage:
        await log_action(
            db, user,
            action="export.contacts",
            resource="contacts",
            request=request,
            metadata={"row_count": len(rows), "filters": {...}},
        )
    """
    row = AuditLog(
        user_id=user.id,
        action=action,
        resource=resource,
        ip_address=_client_ip(request),
        user_agent=_user_agent(request),
        metadata_json=metadata or {},
    )
    try:
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row
    except Exception as e:
        # Fail-open: an audit write failure must not break the
        # action being audited. The response is already queued in
        # the caller, and a missing audit row is a monitoring
        # problem (alert on it), not a user-facing error.
        logger.warning(
            "audit log write failed: action=%s resource=%s user=%s err=%s",
            action, resource, user.id, e,
        )
        try:
            await session.rollback()
        except Exception:
            pass
        return None
