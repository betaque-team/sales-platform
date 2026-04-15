"""Group notification configuration API (admin-only)."""

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.alert import AlertConfig
from app.models.user import User
from app.api.deps import require_role

router = APIRouter(prefix="/alerts", tags=["alerts"])


class AlertConfigCreate(BaseModel):
    name: str
    channel: str = "google_chat"  # google_chat | email
    webhook_url: str | None = None
    email_recipients: str | None = None  # comma-separated emails
    min_relevance_score: int = 70
    role_clusters: list[str] | None = None
    geography_filter: str | None = None


class AlertConfigUpdate(BaseModel):
    name: str | None = None
    channel: str | None = None
    webhook_url: str | None = None
    email_recipients: str | None = None
    min_relevance_score: int | None = None
    role_clusters: list[str] | None = None
    geography_filter: str | None = None
    is_active: bool | None = None


def _serialize(c: AlertConfig) -> dict:
    return {
        "id": str(c.id),
        "name": c.name,
        "channel": c.channel,
        "webhook_url": c.webhook_url or "",
        "email_recipients": c.email_recipients or "",
        "min_relevance_score": c.min_relevance_score,
        "role_clusters": json.loads(c.role_clusters) if c.role_clusters else None,
        "geography_filter": c.geography_filter,
        "is_active": c.is_active,
        "created_by": str(c.created_by) if c.created_by else None,
        "last_triggered_at": c.last_triggered_at.isoformat() if c.last_triggered_at else None,
        "created_at": c.created_at.isoformat(),
    }


@router.get("")
async def list_alerts(
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """List all group notification configs (admin only)."""
    result = await db.execute(
        select(AlertConfig).order_by(AlertConfig.created_at.desc())
    )
    configs = result.scalars().all()
    return {"items": [_serialize(c) for c in configs]}


@router.post("", status_code=201)
async def create_alert(
    body: AlertConfigCreate,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Create a group notification config (admin only)."""
    if body.channel == "google_chat" and not body.webhook_url:
        raise HTTPException(400, "Webhook URL is required for Google Chat channel")
    if body.channel == "email" and not body.email_recipients:
        raise HTTPException(400, "Email recipients are required for email channel")

    config = AlertConfig(
        id=uuid.uuid4(),
        name=body.name,
        channel=body.channel,
        webhook_url=body.webhook_url if body.channel == "google_chat" else None,
        email_recipients=body.email_recipients if body.channel == "email" else None,
        min_relevance_score=body.min_relevance_score,
        role_clusters=json.dumps(body.role_clusters) if body.role_clusters else None,
        geography_filter=body.geography_filter,
        created_by=admin.id,
    )
    db.add(config)
    await db.commit()
    await db.refresh(config)
    return _serialize(config)


@router.put("/{alert_id}")
async def update_alert(
    alert_id: str,
    body: AlertConfigUpdate,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Update a group notification config (admin only)."""
    config = (await db.execute(
        select(AlertConfig).where(AlertConfig.id == alert_id)
    )).scalar_one_or_none()
    if not config:
        raise HTTPException(404, "Notification config not found")

    if body.name is not None:
        config.name = body.name
    if body.channel is not None:
        config.channel = body.channel
    if body.webhook_url is not None:
        config.webhook_url = body.webhook_url or None
    if body.email_recipients is not None:
        config.email_recipients = body.email_recipients or None
    if body.min_relevance_score is not None:
        config.min_relevance_score = body.min_relevance_score
    if body.role_clusters is not None:
        config.role_clusters = json.dumps(body.role_clusters) if body.role_clusters else None
    if body.geography_filter is not None:
        config.geography_filter = body.geography_filter or None
    if body.is_active is not None:
        config.is_active = body.is_active
    config.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(config)
    return _serialize(config)


@router.delete("/{alert_id}")
async def delete_alert(
    alert_id: str,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Delete a notification config (admin only)."""
    config = (await db.execute(
        select(AlertConfig).where(AlertConfig.id == alert_id)
    )).scalar_one_or_none()
    if not config:
        raise HTTPException(404, "Notification config not found")
    await db.delete(config)
    await db.commit()
    return {"status": "deleted"}


@router.post("/{alert_id}/test")
async def test_alert(
    alert_id: str,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Send a test notification to verify connectivity."""
    config = (await db.execute(
        select(AlertConfig).where(AlertConfig.id == alert_id)
    )).scalar_one_or_none()
    if not config:
        raise HTTPException(404, "Notification config not found")

    from app.config import get_settings
    settings = get_settings()
    test_jobs = [{
        "id": "test-000",
        "title": "Senior Cloud Engineer (Test Alert)",
        "company_name": "Test Company",
        "relevance_score": 85,
        "role_cluster": "infra",
        "geography_bucket": "global_remote",
        "salary_range": "$150k-200k",
        "platform": "greenhouse",
        "min_score": config.min_relevance_score,
    }]

    if config.channel == "google_chat":
        from app.workers.tasks.alert_task import send_google_chat_alert
        success = send_google_chat_alert(config.webhook_url, test_jobs)
        if not success:
            raise HTTPException(502, "Failed to send test alert. Check your webhook URL.")
        return {"status": "sent", "message": "Test alert sent to Google Chat"}

    elif config.channel == "email":
        from app.services.email import send_email, build_job_alert_html, build_job_alert_text
        recipients = [e.strip() for e in (config.email_recipients or "").split(",") if e.strip()]
        if not recipients:
            raise HTTPException(400, "No email recipients configured")
        html = build_job_alert_html(test_jobs, settings.app_url)
        text = build_job_alert_text(test_jobs, settings.app_url)
        success = send_email(recipients, "🚀 Test Job Alert — Sales Platform", html, text)
        if not success:
            raise HTTPException(502, "Failed to send test email. Check SMTP configuration.")
        return {"status": "sent", "message": f"Test email sent to {', '.join(recipients)}"}

    raise HTTPException(400, f"Unknown channel: {config.channel}")


@router.get("/smtp-status")
async def smtp_status(admin: User = Depends(require_role("admin"))):
    """Check if SMTP is configured."""
    from app.config import get_settings
    settings = get_settings()
    return {
        "configured": bool(settings.smtp_host and settings.smtp_from_email),
        "host": settings.smtp_host or None,
        "from_email": settings.smtp_from_email or None,
    }
