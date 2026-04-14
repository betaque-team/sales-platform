from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from app.fetchers.base import BaseFetcher

logger = logging.getLogger(__name__)

API_URL = "https://api.ashbyhq.com/posting-api/job-board/{slug}"


class AshbyFetcher(BaseFetcher):
    """Fetch open positions from an Ashby job board."""

    PLATFORM = "ashby"

    def fetch(self, slug: str) -> list[dict]:
        client = self._get_client()
        url = API_URL.format(slug=slug)

        try:
            resp = client.get(url)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning("Ashby %s returned %s", slug, exc.response.status_code)
            return []
        except httpx.RequestError as exc:
            logger.warning("Ashby %s request failed: %s", slug, exc)
            return []

        data = resp.json()
        jobs: list[dict] = data.get("jobs", [])
        return [self._normalize(job, slug) for job in jobs]

    def _normalize(self, raw: dict[str, Any], slug: str) -> dict:
        location_name = raw.get("location") or raw.get("locationName") or ""
        if isinstance(location_name, dict):
            location_name = location_name.get("name", "")

        department = raw.get("departmentName") or raw.get("department") or ""
        if isinstance(department, dict):
            department = department.get("name", "")

        job_id = raw.get("id", "")
        job_url = raw.get("jobUrl") or raw.get("applyUrl") or ""
        if not job_url and job_id:
            job_url = f"https://jobs.ashbyhq.com/{slug}/{job_id}"

        return {
            "external_id": str(job_id),
            "company_slug": slug,
            "title": raw.get("title", ""),
            "url": job_url,
            "platform": self.PLATFORM,
            "location_raw": location_name,
            "remote_scope": self._detect_remote_scope(location_name),
            "department": department,
            "raw_json": raw,
        }
