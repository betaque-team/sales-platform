"""Fetch open positions from SmartRecruiters.

SmartRecruiters public API: https://api.smartrecruiters.com/v1/companies/{slug}/postings
Returns paginated results with offset/limit.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.fetchers.base import BaseFetcher

logger = logging.getLogger(__name__)

API_URL = "https://api.smartrecruiters.com/v1/companies/{slug}/postings"


class SmartRecruitersFetcher(BaseFetcher):
    """Fetch open positions from SmartRecruiters."""

    PLATFORM = "smartrecruiters"

    def fetch(self, slug: str) -> list[dict]:
        client = self._get_client()
        all_jobs = []
        offset = 0
        limit = 100

        while True:
            try:
                resp = client.get(
                    API_URL.format(slug=slug),
                    params={"offset": offset, "limit": limit},
                )
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logger.warning("SmartRecruiters %s returned %s", slug, exc.response.status_code)
                break
            except httpx.RequestError as exc:
                logger.warning("SmartRecruiters %s request failed: %s", slug, exc)
                break

            data = resp.json()
            postings = data.get("content", [])
            if not postings:
                break

            all_jobs.extend([self._normalize(p, slug) for p in postings])

            total = data.get("totalFound", 0)
            offset += len(postings)
            if offset >= total:
                break

            if offset > 500:
                break

        return all_jobs

    def _normalize(self, raw: dict[str, Any], slug: str) -> dict:
        job_id = raw.get("id", "") or raw.get("uuid", "")
        title = raw.get("name", "")

        # Location
        location = raw.get("location", {}) or {}
        if isinstance(location, dict):
            parts = [
                location.get("city", ""),
                location.get("region", ""),
                location.get("country", ""),
            ]
            location_raw = ", ".join(p for p in parts if p)
            remote_flag = location.get("remote", False)
        else:
            location_raw = str(location)
            remote_flag = False

        # Department
        department_obj = raw.get("department", {}) or {}
        department = department_obj.get("label", "") if isinstance(department_obj, dict) else str(department_obj)

        # Employment type
        type_of_employment = raw.get("typeOfEmployment", {}) or {}
        employment_type = type_of_employment.get("label", "") if isinstance(type_of_employment, dict) else ""

        # URL
        ref = raw.get("ref", "")
        company_obj = raw.get("company", {}) or {}
        company_identifier = company_obj.get("identifier", slug)
        job_url = f"https://jobs.smartrecruiters.com/{company_identifier}/{job_id}"

        # Posted date
        posted_at = raw.get("releasedDate", "") or raw.get("createdOn", "") or ""

        # Remote scope
        remote_scope = self._detect_remote_scope(location_raw)
        if not remote_scope and remote_flag:
            remote_scope = "remote"

        return {
            "external_id": f"sr-{job_id}",
            "company_slug": slug,
            "title": title,
            "url": job_url,
            "platform": self.PLATFORM,
            "location_raw": location_raw,
            "remote_scope": remote_scope,
            "department": department,
            "employment_type": employment_type,
            "posted_at": posted_at,
            "raw_json": raw,
        }
