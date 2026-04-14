from __future__ import annotations

import logging
from typing import Any

import httpx

from app.fetchers.base import BaseFetcher

logger = logging.getLogger(__name__)

# BambooHR has two known JSON endpoints:
# 1. /careers/list - older endpoint (may return HTML on some tenants)
# 2. /jobs - newer ATS embed endpoint (returns JSON reliably)
API_URLS = [
    "https://{slug}.bamboohr.com/jobs",
    "https://{slug}.bamboohr.com/careers/list",
]


class BambooHRFetcher(BaseFetcher):
    """Fetch open positions from a BambooHR careers page."""

    PLATFORM = "bamboohr"

    def fetch(self, slug: str) -> list[dict]:
        client = self._get_client()

        # Try both endpoints -- newer /jobs endpoint first
        for url_template in API_URLS:
            url = url_template.format(slug=slug)
            try:
                resp = client.get(
                    url,
                    headers={"Accept": "application/json"},
                    follow_redirects=True,
                )
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logger.warning("BambooHR %s %s returned %s", slug, url, exc.response.status_code)
                continue
            except httpx.RequestError as exc:
                logger.warning("BambooHR %s %s request failed: %s", slug, url, exc)
                continue

            content_type = resp.headers.get("content-type", "")
            if "json" not in content_type and "javascript" not in content_type:
                logger.warning("BambooHR %s %s returned non-JSON content-type: %s", slug, url, content_type)
                continue

            try:
                data = resp.json()
            except Exception:
                logger.warning("BambooHR %s %s returned non-JSON body (len=%d)", slug, url, len(resp.text))
                continue

            # Handle both response shapes: {"result": [...]} and direct list
            jobs = data.get("result", data) if isinstance(data, dict) else data
            if not isinstance(jobs, list):
                logger.warning("BambooHR %s unexpected result type: %s", slug, type(jobs).__name__)
                continue

            logger.info("BambooHR %s fetched %d jobs from %s", slug, len(jobs), url)
            return [self._normalize(job, slug) for job in jobs]

        logger.warning("BambooHR %s: all endpoints failed", slug)
        return []

    def _normalize(self, raw: dict[str, Any], slug: str) -> dict:
        job_id = str(raw.get("id", ""))

        title = raw.get("jobOpeningName", "") or raw.get("title", "")

        # Location
        location_city = raw.get("location", {})
        if isinstance(location_city, dict):
            city = location_city.get("city", "")
            state = location_city.get("state", "")
            country = location_city.get("country", "")
            location_name = ", ".join(p for p in [city, state, country] if p)
        elif isinstance(location_city, str):
            location_name = location_city
        else:
            location_name = ""

        department = raw.get("departmentLabel", "") or raw.get("department", "") or ""

        employment_status = raw.get("employmentStatusLabel", "") or ""

        job_url = f"https://{slug}.bamboohr.com/careers/{job_id}" if job_id else ""

        remote_scope = self._detect_remote_scope(location_name, title)

        return {
            "external_id": f"bamboo-{slug}-{job_id}",
            "company_slug": slug,
            "title": title,
            "url": job_url,
            "platform": self.PLATFORM,
            "location_raw": location_name,
            "remote_scope": remote_scope,
            "department": department,
            "employment_type": employment_status,
            "raw_json": raw,
        }
