"""Fetch open positions from Wellfound (formerly AngelList Talent).

Wellfound does not have a public REST API like Greenhouse/Lever.
This fetcher uses their internal GraphQL API that powers the public job pages.
The slug is the company's Wellfound handle.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from app.fetchers.base import BaseFetcher

logger = logging.getLogger(__name__)

# Wellfound GraphQL endpoint used by public pages
GRAPHQL_URL = "https://wellfound.com/graphql"

# GraphQL query to fetch company jobs
JOBS_QUERY = """
query CompanyJobs($slug: String!) {
  startup(slug: $slug) {
    id
    name
    jobListings(listed: true) {
      id
      title
      slug
      description
      remote
      primaryRoleTitle
      locationNames
      compensation
      jobType
      liveStartAt
    }
  }
}
"""


class WellfoundFetcher(BaseFetcher):
    """Fetch open positions from Wellfound (AngelList Talent)."""

    PLATFORM = "wellfound"

    def fetch(self, slug: str) -> list[dict]:
        client = self._get_client()

        # Try GraphQL API first
        try:
            resp = client.post(
                GRAPHQL_URL,
                json={
                    "query": JOBS_QUERY,
                    "variables": {"slug": slug},
                },
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()

            # Check for GraphQL errors (returned with HTTP 200)
            if "errors" in data:
                error_msgs = [e.get("message", str(e)) for e in data["errors"]]
                logger.warning("Wellfound %s GraphQL errors: %s", slug, "; ".join(error_msgs))
                return []

            startup = (data.get("data") or {}).get("startup")
            if not startup:
                logger.warning("Wellfound %s: no startup data found (response keys: %s)", slug, list(data.keys()))
                return []

            listings = startup.get("jobListings", []) or []
            logger.info("Wellfound %s fetched %d listings", slug, len(listings))
            return [self._normalize(job, slug, startup.get("name", slug)) for job in listings]

        except httpx.HTTPStatusError as exc:
            logger.warning("Wellfound %s returned %s", slug, exc.response.status_code)
            return []
        except httpx.RequestError as exc:
            logger.warning("Wellfound %s request failed: %s", slug, exc)
            return []
        except Exception as exc:
            logger.warning("Wellfound %s parse error: %s", slug, exc)
            return []

    def _normalize(self, raw: dict[str, Any], slug: str, company_name: str = "") -> dict:
        job_id = raw.get("id", "")
        title = raw.get("title", "")
        job_slug = raw.get("slug", "")

        # URL
        job_url = f"https://wellfound.com/company/{slug}/jobs/{job_id}"

        # Location
        location_names = raw.get("locationNames", [])
        if isinstance(location_names, list):
            location_raw = ", ".join(location_names[:5])
        else:
            location_raw = str(location_names) if location_names else ""

        # Remote scope
        is_remote = raw.get("remote", False)
        remote_scope = self._detect_remote_scope(location_raw)
        if not remote_scope and is_remote:
            remote_scope = "remote"

        # Department / role
        department = raw.get("primaryRoleTitle", "") or ""

        # Employment type
        job_type = raw.get("jobType", "") or ""

        # Compensation
        compensation = raw.get("compensation", "")
        salary_range = str(compensation) if compensation else ""

        # Posted date
        posted_at = raw.get("liveStartAt", "") or ""

        return {
            "external_id": f"wellfound-{job_id}",
            "company_slug": slug,
            "title": title,
            "url": job_url,
            "platform": self.PLATFORM,
            "location_raw": location_raw,
            "remote_scope": remote_scope,
            "department": department,
            "employment_type": job_type,
            "salary_range": salary_range,
            "posted_at": posted_at,
            "raw_json": raw,
        }
