from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from app.fetchers.base import BaseFetcher

logger = logging.getLogger(__name__)

API_URL = "https://api.lever.co/v0/postings/{slug}"


class LeverFetcher(BaseFetcher):
    """Fetch open positions from a Lever job board."""

    PLATFORM = "lever"

    def fetch(self, slug: str) -> list[dict]:
        client = self._get_client()
        url = API_URL.format(slug=slug)

        try:
            resp = client.get(url)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning("Lever %s returned %s", slug, exc.response.status_code)
            return []
        except httpx.RequestError as exc:
            logger.warning("Lever %s request failed: %s", slug, exc)
            return []

        data = resp.json()
        # Lever returns a flat list of postings.
        if not isinstance(data, list):
            logger.warning("Lever %s returned unexpected response type: %s", slug, type(data).__name__)
            return []

        return [self._normalize(posting, slug) for posting in data]

    def _normalize(self, raw: dict[str, Any], slug: str) -> dict:
        categories = raw.get("categories", {}) or {}

        location_name = categories.get("location", "")
        department = categories.get("team", "")
        commitment = categories.get("commitment", "")

        # allLocations can have multiple entries
        all_locations = categories.get("allLocations", []) or []
        if isinstance(all_locations, list):
            all_locations_str = ", ".join(str(l) for l in all_locations)
        else:
            all_locations_str = str(all_locations)

        posting_id = raw.get("id", "")
        job_url = raw.get("hostedUrl", "") or raw.get("applyUrl", "")
        if not job_url and posting_id:
            job_url = f"https://jobs.lever.co/{slug}/{posting_id}"

        # Detect remote from location, commitment, and all locations
        remote_scope = self._detect_remote_scope(
            location_name,
            commitment,
            all_locations_str,
        )

        # Extract posted date
        created_at = raw.get("createdAt")
        posted_at = ""
        if created_at and isinstance(created_at, (int, float)):
            from datetime import datetime, timezone
            posted_at = datetime.fromtimestamp(created_at / 1000, tz=timezone.utc).isoformat()

        # Build employment type from commitment
        employment_type = ""
        if commitment:
            cl = commitment.lower()
            if "full" in cl:
                employment_type = "Full-time"
            elif "part" in cl:
                employment_type = "Part-time"
            elif "contract" in cl:
                employment_type = "Contract"
            elif "intern" in cl:
                employment_type = "Internship"

        return {
            "external_id": str(posting_id),
            "company_slug": slug,
            "title": raw.get("text", ""),
            "url": job_url,
            "platform": self.PLATFORM,
            "location_raw": location_name,
            "remote_scope": remote_scope,
            "department": department,
            "employment_type": employment_type,
            "posted_at": posted_at,
            "raw_json": raw,
        }
