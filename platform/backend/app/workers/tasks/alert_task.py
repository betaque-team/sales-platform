"""Job alert notification tasks -- sends to Google Chat webhooks and email."""

import json
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select

from app.workers.celery_app import celery_app
from app.workers.tasks._db import SyncSession
from app.models.alert import AlertConfig
from app.models.job import Job
from app.models.company import Company
from app.config import get_settings

logger = logging.getLogger(__name__)


def _build_google_chat_card(jobs: list[dict], settings_obj) -> dict:
    """Build a Google Chat card message for new job alerts."""
    app_url = settings_obj.app_url

    sections = []
    for j in jobs[:10]:  # Max 10 jobs per message
        score = j["relevance_score"]
        score_emoji = "\U0001f7e2" if score >= 70 else "\U0001f7e1" if score >= 50 else "\U0001f534"
        cluster = (j.get("role_cluster") or "other").upper()
        geo = (j.get("geography_bucket") or "").replace("_", " ").title()

        sections.append({
            "widgets": [
                {
                    "decoratedText": {
                        "topLabel": f"{j['company_name']} \u00b7 {cluster}",
                        "text": f"<b>{j['title']}</b>",
                        "bottomLabel": f"{score_emoji} Score: {score} \u00b7 {geo}" + (f" \u00b7 {j.get('salary_range', '')}" if j.get("salary_range") else ""),
                        "button": {
                            "text": "View",
                            "onClick": {"openLink": {"url": f"{app_url}/jobs/{j['id']}"}},
                        },
                    }
                }
            ]
        })

    overflow = len(jobs) - 10
    if overflow > 0:
        sections.append({
            "widgets": [{"decoratedText": {"text": f"<i>+{overflow} more jobs matching your criteria</i>"}}]
        })

    return {
        "cardsV2": [{
            "cardId": "job-alert",
            "card": {
                "header": {
                    "title": f"\U0001f680 {len(jobs)} New Job{'s' if len(jobs) != 1 else ''} Found",
                    "subtitle": f"Jobs scoring {jobs[0].get('min_score', 70)}+ relevance",
                },
                "sections": sections,
            },
        }]
    }


def _build_simple_text(jobs: list[dict], settings_obj) -> dict:
    """Fallback: simple text message."""
    app_url = settings_obj.app_url
    lines = [f"*\U0001f680 {len(jobs)} New Job{'s' if len(jobs) != 1 else ''} Found*\n"]
    for j in jobs[:10]:
        score = j["relevance_score"]
        lines.append(
            f"\u2022 *{j['title']}* at {j['company_name']} "
            f"(Score: {score}, {(j.get('role_cluster') or 'other').upper()}) "
            f"\u2014 {app_url}/jobs/{j['id']}"
        )
    if len(jobs) > 10:
        lines.append(f"\n+{len(jobs) - 10} more jobs")
    return {"text": "\n".join(lines)}


def send_google_chat_alert(webhook_url: str, jobs: list[dict]):
    """Send job alert to a Google Chat webhook."""
    settings = get_settings()
    try:
        payload = _build_google_chat_card(jobs, settings)
        resp = httpx.post(webhook_url, json=payload, timeout=10)
        if resp.status_code != 200:
            # Fallback to simple text
            payload = _build_simple_text(jobs, settings)
            resp = httpx.post(webhook_url, json=payload, timeout=10)
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.error("Google Chat alert failed: %s", e)
        return False


def send_email_alert(recipients: list[str], jobs: list[dict]):
    """Send job alert via email."""
    from app.services.email import send_email, build_job_alert_html, build_job_alert_text
    settings = get_settings()
    html = build_job_alert_html(jobs, settings.app_url)
    text = build_job_alert_text(jobs, settings.app_url)
    count = len(jobs)
    subject = f"\U0001f680 {count} New Job{'s' if count != 1 else ''} Found — Sales Platform"
    return send_email(recipients, subject, html, text)


@celery_app.task(name="app.workers.tasks.alert_task.check_and_send_alerts")
def check_and_send_alerts(new_job_ids: list[str]):
    """Check all active alert configs and send notifications for matching new jobs."""
    if not new_job_ids:
        return {"sent": 0}

    session = SyncSession()
    try:
        # Load the new jobs
        jobs = session.execute(
            select(Job, Company.name)
            .join(Company, Job.company_id == Company.id)
            .where(Job.id.in_(new_job_ids))
        ).all()

        if not jobs:
            return {"sent": 0}

        job_dicts = []
        for job, company_name in jobs:
            job_dicts.append({
                "id": str(job.id),
                "title": job.title,
                "company_name": company_name,
                "relevance_score": round(job.relevance_score),
                "role_cluster": job.role_cluster,
                "geography_bucket": job.geography_bucket,
                "salary_range": job.salary_range or "",
                "platform": job.platform,
            })

        # Load active alert configs (group-level, not per-user)
        configs = session.execute(
            select(AlertConfig).where(AlertConfig.is_active.is_(True))
        ).scalars().all()

        sent = 0
        for config in configs:
            # Filter jobs matching this config
            matching = []
            for j in job_dicts:
                if j["relevance_score"] < config.min_relevance_score:
                    continue
                if config.role_clusters:
                    allowed = json.loads(config.role_clusters)
                    if j["role_cluster"] not in allowed:
                        continue
                if config.geography_filter and j["geography_bucket"] != config.geography_filter:
                    continue
                matching.append(j)

            if not matching:
                continue

            # Add min_score for display
            for m in matching:
                m["min_score"] = config.min_relevance_score

            success = False
            if config.channel == "google_chat" and config.webhook_url:
                success = send_google_chat_alert(config.webhook_url, matching)
            elif config.channel == "email" and config.email_recipients:
                recipients = [e.strip() for e in config.email_recipients.split(",") if e.strip()]
                if recipients:
                    success = send_email_alert(recipients, matching)

            if success:
                config.last_triggered_at = datetime.now(timezone.utc)
                sent += 1

        session.commit()
        logger.info("Alerts sent: %d configs notified for %d new jobs", sent, len(new_job_ids))
        return {"sent": sent, "new_jobs": len(new_job_ids)}

    except Exception as e:
        logger.exception("check_and_send_alerts failed: %s", e)
        session.rollback()
        return {"sent": 0, "error": str(e)}
    finally:
        session.close()
