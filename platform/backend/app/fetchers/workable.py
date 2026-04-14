from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from app.fetchers.base import BaseFetcher

logger = logging.getLogger(__name__)

API_URL = "https://apply.workable.com/api/v1/widget/accounts/{slug}"


class WorkableFetcher(BaseFetcher):
    """Fetch open positions from a Workable job board."""

    PLATFORM = "workable"

    def fetch(self, slug: str) -> list[dict]:
        client = self._get_client()
        url = API_URL.format(slug=slug)

        try:
            resp = client.get(url)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning("Workable %s returned %s", slug, exc.response.status_code)
            return []
        except httpx.RequestError as exc:
            logger.warning("Workable %s request failed: %s", slug, exc)
            return []

        data = resp.json()
        jobs: list[dict] = data.get("jobs", [])
        return [self._normalize(job, slug) for job in jobs]

    def _normalize(self, raw: dict[str, Any], slug: str) -> dict:
        # Workable location can be a dict with city/country or a plain string.
        location_raw = raw.get("location", "")
        if isinstance(location_raw, dict):
            parts = [
                location_raw.get("city", ""),
                location_raw.get("region", ""),
                location_raw.get("country", ""),
            ]
            location_name = ", ".join(p for p in parts if p)
        elif isinstance(location_raw, str):
            location_name = location_raw
        else:
            location_name = ""

        department = raw.get("department") or ""
        if isinstance(department, dict):
            department = department.get("name", "") or ""

        job_id = raw.get("id") or raw.get("shortcode") or ""
        shortcode = raw.get("shortcode", "")
        job_url = raw.get("url") or raw.get("application_url") or ""
        if not job_url and shortcode:
            job_url = f"https://apply.workable.com/{slug}/j/{shortcode}/"

        # Telecommuting flag
        telecommuting = raw.get("telecommuting", False)

        # Country/city for location
        country = raw.get("country") or ""
        city = raw.get("city") or ""
        if not location_name and (country or city):
            location_name = ", ".join(p for p in [city, country] if p)

        # Remote scope detection using location + telecommuting flag
        remote_texts = [location_name]
        if telecommuting:
            remote_texts.append("remote")
        remote_scope = self._detect_remote_scope(*remote_texts)

        # Employment type
        employment_type = raw.get("employment_type") or ""

        # Published date
        posted_at = raw.get("published_on") or raw.get("created_at") or ""

        return {
            "external_id": str(job_id),
            "company_slug": slug,
            "title": raw.get("title", ""),
            "url": job_url,
            "platform": self.PLATFORM,
            "location_raw": location_name,
            "remote_scope": remote_scope,
            "department": department,
            "employment_type": employment_type,
            "posted_at": posted_at,
            "raw_json": raw,
        }
