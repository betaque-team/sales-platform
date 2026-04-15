"""Fetch open positions from Jobvite career sites.

Jobvite exposes a JSON API at: https://jobs.jobvite.com/company-slug/jobs
with ?availableTo=External&category=&location=&page=N
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.fetchers.base import BaseFetcher

logger = logging.getLogger(__name__)

API_URL = "https://jobs.jobvite.com/{slug}/jobs"


class JobviteFetcher(BaseFetcher):
    """Fetch open positions from Jobvite."""

    PLATFORM = "jobvite"

    def fetch(self, slug: str) -> list[dict]:
        client = self._get_client()
        all_jobs = []
        page = 1

        while True:
            try:
                resp = client.get(
                    API_URL.format(slug=slug),
                    params={"availableTo": "External", "page": page},
                    headers={"Accept": "application/json"},
                )
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logger.warning("Jobvite %s returned %s", slug, exc.response.status_code)
                break
            except httpx.RequestError as exc:
                logger.warning("Jobvite %s request failed: %s", slug, exc)
                break

            # Jobvite now redirects unknown/migrated slugs to their marketing
            # support page (www.jobvite.com/support/...?invalid=1). Detect and
            # treat as a permanently-dead slug instead of spamming warnings.
            final_host = str(resp.url.host) if resp.url else ""
            if final_host.endswith("www.jobvite.com"):
                logger.info(
                    "Jobvite %s: slug no longer hosted on jobs.jobvite.com (redirected to %s)",
                    slug, final_host,
                )
                break

            try:
                data = resp.json()
            except Exception:
                # Jobvite may return HTML if the slug is wrong
                logger.warning("Jobvite %s returned non-JSON response", slug)
                break

            jobs = data.get("requisitions", [])
            if not jobs:
                break

            all_jobs.extend([self._normalize(job, slug) for job in jobs])

            # Jobvite pagination
            total_pages = data.get("totalPages", 1)
            if page >= total_pages:
                break
            page += 1

            if page > 10:
                break

        return all_jobs

    def _normalize(self, raw: dict[str, Any], slug: str) -> dict:
        job_id = raw.get("eId", "") or raw.get("id", "")
        title = raw.get("title", "")

        location_raw = raw.get("location", "") or ""
        if isinstance(location_raw, dict):
            parts = [location_raw.get("city", ""), location_raw.get("state", ""), location_raw.get("country", "")]
            location_raw = ", ".join(p for p in parts if p)

        department = raw.get("category", "") or raw.get("department", "") or ""
        job_type = raw.get("type", "") or ""

        job_url = raw.get("detailUrl", "") or raw.get("applyUrl", "")
        if not job_url and job_id:
            job_url = f"https://jobs.jobvite.com/{slug}/job/{job_id}"

        posted_at = raw.get("postingDate", "") or raw.get("datePosted", "") or ""

        remote_scope = self._detect_remote_scope(location_raw, title)

        return {
            "external_id": f"jobvite-{job_id}" if job_id else f"jobvite-{slug}-{title[:50]}",
            "company_slug": slug,
            "title": title,
            "url": job_url,
            "platform": self.PLATFORM,
            "location_raw": location_raw,
            "remote_scope": remote_scope,
            "department": department,
            "employment_type": job_type,
            "posted_at": posted_at,
            "raw_json": raw,
        }
