"""Job alert configuration API."""

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
from app.api.deps import get_current_user

router = APIRouter(prefix="/alerts", tags=["alerts"])


class AlertConfigCreate(BaseModel):
    channel: str = "google_chat"
    webhook_url: str
    min_relevance_score: int = 70
    role_clusters: list[str] | None = None
    geography_filter: str | None = None


class AlertConfigUpdate(BaseModel):
    webhook_url: str | None = None
    min_relevance_score: int | None = None
    role_clusters: list[str] | None = None
    geography_filter: str | None = None
    is_active: bool | None = None


@router.get("")
async def list_alerts(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AlertConfig).where(AlertConfig.user_id == user.id).order_by(AlertConfig.created_at.desc())
    )
    configs = result.scalars().all()
    return {
        "items": [
            {
                "id": str(c.id),
                "channel": c.channel,
                "webhook_url": c.webhook_url,
                "min_relevance_score": c.min_relevance_score,
                "role_clusters": json.loads(c.role_clusters) if c.role_clusters else None,
                "geography_filter": c.geography_filter,
                "is_active": c.is_active,
                "last_triggered_at": c.last_triggered_at.isoformat() if c.last_triggered_at else None,
                "created_at": c.created_at.isoformat(),
            }
            for c in configs
        ]
    }


@router.post("", status_code=201)
async def create_alert(body: AlertConfigCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    config = AlertConfig(
        id=uuid.uuid4(),
        user_id=user.id,
        channel=body.channel,
        webhook_url=body.webhook_url,
        min_relevance_score=body.min_relevance_score,
        role_clusters=json.dumps(body.role_clusters) if body.role_clusters else None,
        geography_filter=body.geography_filter,
    )
    db.add(config)
    await db.commit()
    return {"id": str(config.id), "status": "created"}


@router.put("/{alert_id}")
async def update_alert(alert_id: str, body: AlertConfigUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    config = (await db.execute(
        select(AlertConfig).where(AlertConfig.id == alert_id, AlertConfig.user_id == user.id)
    )).scalar_one_or_none()
    if not config:
        raise HTTPException(404, "Alert config not found")

    if body.webhook_url is not None:
        config.webhook_url = body.webhook_url
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
    return {"id": str(config.id), "status": "updated"}


@router.delete("/{alert_id}")
async def delete_alert(alert_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    config = (await db.execute(
        select(AlertConfig).where(AlertConfig.id == alert_id, AlertConfig.user_id == user.id)
    )).scalar_one_or_none()
    if not config:
        raise HTTPException(404, "Alert config not found")
    await db.delete(config)
    await db.commit()
    return {"status": "deleted"}


@router.post("/{alert_id}/test")
async def test_alert(alert_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Send a test alert to verify webhook connectivity."""
    config = (await db.execute(
        select(AlertConfig).where(AlertConfig.id == alert_id, AlertConfig.user_id == user.id)
    )).scalar_one_or_none()
    if not config:
        raise HTTPException(404, "Alert config not found")

    from app.workers.tasks.alert_task import send_google_chat_alert
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

    success = send_google_chat_alert(config.webhook_url, test_jobs)
    if not success:
        raise HTTPException(502, "Failed to send test alert. Check your webhook URL.")

    return {"status": "sent", "message": "Test alert sent to your Google Chat group"}
