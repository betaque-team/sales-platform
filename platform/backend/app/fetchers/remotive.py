"""Fetch remote jobs from Remotive public API.

API docs: https://github.com/remotive-com/remote-jobs-api
Endpoint: GET https://remotive.com/api/remote-jobs (no auth required)
Returns: { "job-count": N, "jobs": [...] }
"""

import logging
from typing import Any

import httpx

from app.fetchers.base import BaseFetcher

logger = logging.getLogger(__name__)

API_URL = "https://remotive.com/api/remote-jobs"


class RemotiveFetcher(BaseFetcher):
    """Fetch open positions from Remotive."""

    PLATFORM = "remotive"

    def fetch(self, slug: str) -> list[dict]:
        """Fetch all remote jobs from Remotive.

        slug is ignored (always fetches all). Use '__all__' by convention.
        """
        client = self._get_client()
        all_jobs = []

        try:
            resp = client.get(
                API_URL,
                headers={"Accept": "application/json"},
            )
            if resp.status_code != 200:
                logger.warning("Remotive returned %s", resp.status_code)
                return []

            data = resp.json()
            jobs = data.get("jobs", [])

            for job in jobs:
                if not isinstance(job, dict):
                    continue
                normalized = self._normalize(job, slug)
                if normalized:
                    all_jobs.append(normalized)

        except Exception as exc:
            logger.warning("Remotive fetch failed: %s", exc)

        logger.info("Remotive fetched %d jobs", len(all_jobs))
        return all_jobs

    def _normalize(self, raw: dict[str, Any], slug: str) -> dict:
        title = (raw.get("title") or "").strip()
        if not title:
            return {}

        company_name = (raw.get("company_name") or "").strip()
        company_slug = company_name.lower().replace(" ", "-")[:100] if company_name else "unknown"

        # Location — Remotive uses 'candidate_required_location'
        location_raw = (raw.get("candidate_required_location") or "").strip()

        # URL
        job_url = raw.get("url") or ""

        # Remote scope
        remote_scope = self._detect_remote_scope(location_raw, title)
        # Check job_type for remote indicators
        job_type = raw.get("job_type") or ""
        if not remote_scope:
            remote_scope = self._detect_remote_scope(job_type) or "remote"

        # External ID
        ext_id = str(raw.get("id", ""))
        if not ext_id:
            ext_id = f"{company_slug}-{title}".lower().replace(" ", "-")[:100]

        # Category as department
        department = raw.get("category") or ""

        # Salary
        salary_range = (raw.get("salary") or "").strip()

        # Employment type
        employment_type = job_type.replace("_", " ").title() if job_type else ""

        # Posted date
        posted_at = raw.get("publication_date") or ""

        # Tags
        tags = raw.get("tags") or []

        return {
            "external_id": f"remotive-{ext_id}",
            "company_slug": company_slug,
            "company_name": company_name,
            "title": title,
            "url": job_url,
            "platform": self.PLATFORM,
            "location_raw": location_raw,
            "remote_scope": remote_scope,
            "department": department,
            "employment_type": employment_type,
            "salary_range": salary_range,
            "posted_at": posted_at,
            "raw_json": raw,
        }
