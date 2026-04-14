"""Fetch open positions from Recruitee.

Recruitee public API: https://{slug}.recruitee.com/api/offers
Returns a list of job offers in JSON.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.fetchers.base import BaseFetcher

logger = logging.getLogger(__name__)

API_URL = "https://{slug}.recruitee.com/api/offers"


class RecruiteeFetcher(BaseFetcher):
    """Fetch open positions from Recruitee."""

    PLATFORM = "recruitee"

    def fetch(self, slug: str) -> list[dict]:
        client = self._get_client()

        try:
            resp = client.get(API_URL.format(slug=slug))
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning("Recruitee %s returned %s", slug, exc.response.status_code)
            return []
        except httpx.RequestError as exc:
            logger.warning("Recruitee %s request failed: %s", slug, exc)
            return []

        try:
            data = resp.json()
        except Exception as exc:
            logger.warning("Recruitee %s returned non-JSON response: %s (body len=%d)", slug, exc, len(resp.text))
            return []

        offers = data.get("offers", [])
        if not isinstance(offers, list):
            logger.warning("Recruitee %s unexpected offers type: %s", slug, type(offers).__name__)
            return []

        logger.info("Recruitee %s fetched %d offers", slug, len(offers))
        return [self._normalize(offer, slug) for offer in offers]

    def _normalize(self, raw: dict[str, Any], slug: str) -> dict:
        job_id = raw.get("id", "")
        title = raw.get("title", "")
        slug_name = raw.get("slug", "")

        # Location
        location_raw = raw.get("location", "") or ""
        city = raw.get("city", "")
        country = raw.get("country", "")
        if not location_raw and (city or country):
            location_raw = ", ".join(p for p in [city, country] if p)

        # Department
        department = raw.get("department", "") or ""

        # Employment type
        employment_type = raw.get("employment_type_code", "") or ""

        # URL
        careers_url = raw.get("careers_url", "")
        job_url = raw.get("url", "") or careers_url
        if not job_url:
            job_url = f"https://{slug}.recruitee.com/o/{slug_name}" if slug_name else ""

        # Remote
        remote_flag = raw.get("remote", False)
        remote_scope = self._detect_remote_scope(location_raw, title)
        if not remote_scope and remote_flag:
            remote_scope = "remote"

        # Salary
        salary_parts = []
        if raw.get("min_salary"):
            salary_parts.append(str(raw["min_salary"]))
        if raw.get("max_salary"):
            salary_parts.append(f"- {raw['max_salary']}")
        if raw.get("salary_currency"):
            salary_parts.insert(0, raw["salary_currency"])
        salary_range = " ".join(salary_parts) if salary_parts else ""

        # Posted date
        posted_at = raw.get("published_at", "") or raw.get("created_at", "") or ""

        return {
            "external_id": f"recruitee-{job_id}",
            "company_slug": slug,
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
