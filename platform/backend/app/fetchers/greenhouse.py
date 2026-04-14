from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from app.fetchers.base import BaseFetcher

logger = logging.getLogger(__name__)

API_URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"


class GreenhouseFetcher(BaseFetcher):
    """Fetch open positions from a Greenhouse job board."""

    PLATFORM = "greenhouse"

    def fetch(self, slug: str) -> list[dict]:
        client = self._get_client()
        url = API_URL.format(slug=slug)

        try:
            resp = client.get(url)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning("Greenhouse %s returned %s", slug, exc.response.status_code)
            return []
        except httpx.RequestError as exc:
            logger.warning("Greenhouse %s request failed: %s", slug, exc)
            return []

        data = resp.json()
        jobs: list[dict] = data.get("jobs", [])
        return [self._normalize(job, slug) for job in jobs]

    def _normalize(self, raw: dict[str, Any], slug: str) -> dict:
        location_name = ""
        loc = raw.get("location")
        if isinstance(loc, dict):
            location_name = loc.get("name", "")
        elif isinstance(loc, str):
            location_name = loc

        department = ""
        departments = raw.get("departments")
        if departments and isinstance(departments, list) and len(departments) > 0:
            dept = departments[0]
            if isinstance(dept, dict):
                department = dept.get("name", "")
            elif isinstance(dept, str):
                department = dept

        job_id = raw.get("id", "")
        job_url = raw.get("absolute_url", "")
        if not job_url and job_id:
            job_url = f"https://boards.greenhouse.io/{slug}/jobs/{job_id}"

        # Extract all location signals for better remote detection
        office_locations = []
        offices = raw.get("offices", [])
        if isinstance(offices, list):
            for office in offices:
                if isinstance(office, dict):
                    ol = office.get("location", "")
                    if ol:
                        office_locations.append(ol)
                    on = office.get("name", "")
                    if on and on != ol:
                        office_locations.append(on)

        # Extract posted date
        posted_at = raw.get("first_published") or raw.get("updated_at") or ""

        # Detect remote scope from location + office locations + content hints
        remote_scope = self._detect_remote_scope(
            location_name,
            *office_locations,
        )

        return {
            "external_id": str(job_id),
            "company_slug": slug,
            "title": raw.get("title", ""),
            "url": job_url,
            "platform": self.PLATFORM,
            "location_raw": location_name,
            "remote_scope": remote_scope,
            "department": department,
            "posted_at": posted_at,
            "raw_json": raw,
        }
