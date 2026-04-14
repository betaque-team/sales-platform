"""Career page change-detection task."""

import hashlib
import logging
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy import select

from app.workers.celery_app import celery_app
from app.workers.tasks._db import SyncSession
from app.models.scan import CareerPageWatch

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30  # seconds
USER_AGENT = "JobPlatformBot/1.0 (+https://github.com/your-org/job-platform)"


def _fetch_page_hash(url: str) -> str | None:
    """Fetch a URL and return the SHA-256 hash of the response body, or None on error."""
    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": USER_AGENT})
            resp.raise_for_status()
            return hashlib.sha256(resp.content).hexdigest()
    except Exception as e:
        logger.warning("Failed to fetch career page %s: %s", url, e)
        return None


@celery_app.task(name="app.workers.tasks.career_page_task.check_career_pages", bind=True, max_retries=1)
def check_career_pages(self):
    """Iterate active CareerPageWatch records, fetch pages, and compare hashes.

    If the page content hash has changed since the last check, mark has_changed=True,
    increment change_count, and log the change (notification placeholder).
    """
    logger.info("Starting check_career_pages")
    session = SyncSession()

    changed_count = 0
    checked_count = 0
    error_count = 0

    try:
        watches = session.execute(
            select(CareerPageWatch).where(CareerPageWatch.is_active.is_(True))
        ).scalars().all()

        for watch in watches:
            new_hash = _fetch_page_hash(watch.url)
            now = datetime.now(timezone.utc)

            watch.last_checked_at = now
            watch.check_count += 1

            if new_hash is None:
                error_count += 1
                continue

            checked_count += 1

            if watch.last_hash and new_hash != watch.last_hash:
                watch.has_changed = True
                watch.change_count += 1
                changed_count += 1
                logger.info(
                    "Career page changed: %s (company_id=%s, changes=%d)",
                    watch.url, watch.company_id, watch.change_count,
                )
                # TODO: trigger notification (email, Slack webhook, etc.)
            else:
                watch.has_changed = False

            watch.last_hash = new_hash

        session.commit()

        logger.info(
            "check_career_pages complete: %d checked, %d changed, %d errors",
            checked_count, changed_count, error_count,
        )
        return {
            "checked": checked_count,
            "changed": changed_count,
            "errors": error_count,
        }

    except Exception as e:
        logger.exception("check_career_pages failed: %s", e)
        session.rollback()
        raise self.retry(exc=e, countdown=120)
    finally:
        session.close()
