"""Fetch remote jobs from Remote OK public API.

API: GET https://remoteok.com/api (no auth required)
Returns a JSON array of job objects. First element is metadata (skip it).
"""

import logging
from typing import Any

import httpx

from app.fetchers.base import BaseFetcher

logger = logging.getLogger(__name__)

API_URL = "https://remoteok.com/api"


class RemoteOKFetcher(BaseFetcher):
    """Fetch open positions from Remote OK."""

    PLATFORM = "remoteok"

    def fetch(self, slug: str) -> list[dict]:
        """Fetch all remote jobs from RemoteOK.

        slug is ignored (always fetches all). Use '__all__' by convention.
        """
        client = self._get_client()
        all_jobs = []

        try:
            resp = client.get(
                API_URL,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "JobPlatform/1.0 (job aggregator)",
                },
            )
            if resp.status_code != 200:
                logger.warning("RemoteOK returned %s", resp.status_code)
                return []

            data = resp.json()
            if not isinstance(data, list):
                logger.warning("RemoteOK unexpected response format")
                return []

            # First element is metadata/legal notice — skip it
            jobs = data[1:] if len(data) > 1 else data

            for job in jobs:
                if not isinstance(job, dict):
                    continue
                normalized = self._normalize(job, slug)
                if normalized:
                    all_jobs.append(normalized)

        except Exception as exc:
            logger.warning("RemoteOK fetch failed: %s", exc)

        logger.info("RemoteOK fetched %d jobs", len(all_jobs))
        return all_jobs

    def _normalize(self, raw: dict[str, Any], slug: str) -> dict:
        title = (raw.get("position") or "").strip()
        if not title:
            return {}

        company_name = (raw.get("company") or "").strip()
        company_slug = company_name.lower().replace(" ", "-")[:100] if company_name else "unknown"

        # Location — RemoteOK uses 'location' field, often contains region restrictions
        location_raw = (raw.get("location") or "").strip()

        # URL
        job_url = raw.get("url") or raw.get("apply_url") or ""
        if job_url and not job_url.startswith("http"):
            job_url = f"https://remoteok.com{job_url}"

        # Remote scope
        remote_scope = self._detect_remote_scope(location_raw, title) or "remote"

        # External ID
        ext_id = str(raw.get("id", ""))
        if not ext_id:
            ext_id = f"{company_slug}-{title}".lower().replace(" ", "-")[:100]

        # Tags as department hint
        tags = raw.get("tags") or []
        department = tags[0] if isinstance(tags, list) and tags else ""

        # Salary
        salary_min = raw.get("salary_min")
        salary_max = raw.get("salary_max")
        salary_range = ""
        if salary_min and salary_max:
            salary_range = f"${salary_min:,} - ${salary_max:,}"
        elif salary_min:
            salary_range = f"${salary_min:,}+"
        elif salary_max:
            salary_range = f"Up to ${salary_max:,}"

        # Posted date — epoch timestamp
        posted_at = ""
        epoch = raw.get("epoch")
        if epoch and isinstance(epoch, (int, float)):
            from datetime import datetime as dt, timezone as tz
            posted_at = dt.fromtimestamp(epoch, tz=tz.utc).isoformat()
        elif raw.get("date"):
            posted_at = str(raw["date"])

        return {
            "external_id": f"rok-{ext_id}",
            "company_slug": company_slug,
            "company_name": company_name,
            "title": title,
            "url": job_url,
            "platform": self.PLATFORM,
            "location_raw": location_raw,
            "remote_scope": remote_scope,
            "department": department,
            "employment_type": "",
            "salary_range": salary_range,
            "posted_at": posted_at,
            "raw_json": raw,
        }
