"""Fetch job listings associated with a company on LinkedIn.

LinkedIn does NOT have a free public API for job listings. This fetcher
implements multiple strategies with automatic fallback:

1. **JSearch API via RapidAPI** (preferred) -- aggregates LinkedIn + other
   boards. Free tier: 500 requests/month. Subscribe at:
   https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch
   Set RAPIDAPI_KEY in .env and RAPIDAPI_LINKEDIN_HOST=jsearch.p.rapidapi.com

2. **LinkedIn Data API via RapidAPI** (alternative) -- direct LinkedIn data.
   Subscribe at: https://rapidapi.com/rockapis-rockapis-default/api/linkedin-data-api
   Set RAPIDAPI_LINKEDIN_HOST=linkedin-data-api.p.rapidapi.com

3. **LinkedIn public job search (fallback)** -- makes a carefully rate-limited
   request to LinkedIn's public guest search page. Fragile, may break.

Set RAPIDAPI_KEY in .env to enable API strategies.
"""

from __future__ import annotations

import logging
import time
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from app.fetchers.base import BaseFetcher
from app.config import get_settings

logger = logging.getLogger(__name__)

# Default: JSearch API (most popular on RapidAPI, free 500 req/month)
DEFAULT_RAPIDAPI_HOST = "jsearch.p.rapidapi.com"

# LinkedIn public jobs search (fallback, fragile)
LINKEDIN_SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"

# Rate limit: max 1 request per 10 seconds to avoid detection
_last_request_time = 0.0


class LinkedInFetcher(BaseFetcher):
    """Fetch job listings from LinkedIn for a given company."""

    PLATFORM = "linkedin"

    def fetch(self, slug: str) -> list[dict]:
        """Fetch jobs. `slug` is the company name (e.g., "cloudflare").

        Tries RapidAPI first (if key present), falls back to public scraping.
        """
        settings = get_settings()
        if settings.rapidapi_key:
            host = getattr(settings, "rapidapi_linkedin_host", "") or DEFAULT_RAPIDAPI_HOST
            jobs = self._fetch_via_rapidapi(slug, host)
            if jobs:
                return jobs
            logger.info("LinkedIn RapidAPI returned 0 jobs for %s, trying fallback", slug)

        return self._fetch_via_public_search(slug)

    # ------------------------------------------------------------------
    # Strategy 1: JSearch API (jsearch.p.rapidapi.com)
    # ------------------------------------------------------------------

    def _fetch_via_rapidapi(self, company_name: str, host: str) -> list[dict]:
        """Dispatch to the right normalizer based on RapidAPI host."""
        if "jsearch" in host:
            return self._fetch_jsearch(company_name)
        elif "linkedin-data-api" in host:
            return self._fetch_linkedin_data_api(company_name)
        else:
            # Try generic LinkedIn Jobs Search (original API)
            return self._fetch_generic_rapidapi(company_name, host)

    def _fetch_jsearch(self, company_name: str) -> list[dict]:
        """Fetch via JSearch API -- aggregates LinkedIn, Indeed, Glassdoor, etc."""
        client = self._get_client()
        settings = get_settings()
        host = "jsearch.p.rapidapi.com"
        all_jobs: list[dict] = []

        # Fetch multiple pages to get comprehensive results
        for page in range(1, 4):  # 3 pages max
            try:
                resp = client.get(
                    f"https://{host}/search",
                    headers={
                        "X-RapidAPI-Key": settings.rapidapi_key,
                        "X-RapidAPI-Host": host,
                    },
                    params={
                        "query": f"jobs at {company_name}",
                        "page": str(page),
                        "num_pages": "1",
                        "date_posted": "month",
                        "remote_jobs_only": "false",
                    },
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()
                jobs = data.get("data", [])
                if not jobs:
                    break
                all_jobs.extend(jobs)
                logger.info("JSearch %s page %d: %d jobs", company_name, page, len(jobs))
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 403:
                    logger.warning("JSearch: not subscribed (403). Subscribe at https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch")
                elif exc.response.status_code == 429:
                    logger.warning("JSearch %s: rate limited on page %d", company_name, page)
                else:
                    logger.warning("JSearch %s page %d returned %s", company_name, page, exc.response.status_code)
                break
            except Exception as exc:
                logger.warning("JSearch %s error: %s", company_name, exc)
                break

        logger.info("JSearch %s total: %d jobs", company_name, len(all_jobs))
        return [self._normalize_jsearch(j, company_name) for j in all_jobs]

    def _normalize_jsearch(self, raw: dict[str, Any], company_name: str) -> dict:
        """Normalize a JSearch API response job."""
        job_id = raw.get("job_id", "")
        title = raw.get("job_title", "") or ""
        job_url = raw.get("job_apply_link", "") or raw.get("job_google_link", "") or ""
        location = raw.get("job_city", "")
        state = raw.get("job_state", "")
        country = raw.get("job_country", "")
        if state:
            location = f"{location}, {state}" if location else state
        if country and country not in (location or ""):
            location = f"{location}, {country}" if location else country

        is_remote = raw.get("job_is_remote", False)
        remote_scope = "remote" if is_remote else ""

        employment_type = raw.get("job_employment_type", "") or ""

        # Parse posted date
        posted_ts = raw.get("job_posted_at_datetime_utc", "")
        posted_at = ""
        if posted_ts:
            try:
                posted_at = datetime.fromisoformat(posted_ts.replace("Z", "+00:00")).isoformat()
            except (ValueError, TypeError):
                posted_at = posted_ts

        salary_min = raw.get("job_min_salary")
        salary_max = raw.get("job_max_salary")
        salary_range = ""
        if salary_min and salary_max:
            salary_range = f"${int(salary_min):,}-${int(salary_max):,}"
        elif salary_min:
            salary_range = f"${int(salary_min):,}+"

        return {
            "external_id": f"linkedin-{job_id}" if job_id else f"linkedin-{hash(job_url)}",
            "company_slug": company_name,
            "title": title,
            "url": job_url,
            "platform": self.PLATFORM,
            "location_raw": location,
            "remote_scope": self._detect_remote_scope(location, title, remote_scope),
            "department": "",
            "employment_type": employment_type,
            "salary_range": salary_range,
            "posted_at": posted_at,
            "raw_json": raw,
        }

    # ------------------------------------------------------------------
    # Strategy 2: LinkedIn Data API (linkedin-data-api.p.rapidapi.com)
    # ------------------------------------------------------------------

    def _fetch_linkedin_data_api(self, company_name: str) -> list[dict]:
        """Fetch via LinkedIn Data API (direct LinkedIn data)."""
        client = self._get_client()
        settings = get_settings()
        host = "linkedin-data-api.p.rapidapi.com"

        try:
            resp = client.get(
                f"https://{host}/search-jobs",
                headers={
                    "X-RapidAPI-Key": settings.rapidapi_key,
                    "X-RapidAPI-Host": host,
                },
                params={
                    "keywords": company_name,
                    "locationId": "92000000",  # worldwide
                    "datePosted": "anyTime",
                    "sort": "mostRelevant",
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            jobs = data.get("data", [])
            if not isinstance(jobs, list):
                logger.warning("LinkedIn Data API %s: unexpected data type", company_name)
                return []
            logger.info("LinkedIn Data API %s fetched %d jobs", company_name, len(jobs))
            return [self._normalize_linkedin_data_api(j, company_name) for j in jobs]

        except httpx.HTTPStatusError as exc:
            logger.warning("LinkedIn Data API %s returned %s", company_name, exc.response.status_code)
            return []
        except Exception as exc:
            logger.warning("LinkedIn Data API %s error: %s", company_name, exc)
            return []

    def _normalize_linkedin_data_api(self, raw: dict[str, Any], company_name: str) -> dict:
        """Normalize a LinkedIn Data API response."""
        job_id = raw.get("id", "") or raw.get("trackingUrn", "")
        title = raw.get("title", "") or ""
        job_url = raw.get("url", "") or ""
        location = raw.get("location", "") or ""
        posted_at = raw.get("postAt", "") or raw.get("listedAt", "") or ""

        return {
            "external_id": f"linkedin-{job_id}" if job_id else f"linkedin-{hash(job_url)}",
            "company_slug": company_name,
            "title": title,
            "url": job_url,
            "platform": self.PLATFORM,
            "location_raw": location,
            "remote_scope": self._detect_remote_scope(location, title),
            "department": "",
            "employment_type": raw.get("type", "") or "",
            "posted_at": posted_at,
            "raw_json": raw,
        }

    # ------------------------------------------------------------------
    # Strategy 3: Generic RapidAPI LinkedIn endpoint (original)
    # ------------------------------------------------------------------

    def _fetch_generic_rapidapi(self, company_name: str, host: str) -> list[dict]:
        """Use any RapidAPI LinkedIn Jobs Search API."""
        client = self._get_client()
        settings = get_settings()

        try:
            resp = client.post(
                f"https://{host}/",
                headers={
                    "X-RapidAPI-Key": settings.rapidapi_key,
                    "X-RapidAPI-Host": host,
                    "Content-Type": "application/json",
                },
                json={
                    "search_terms": "",
                    "company_name": [company_name],
                    "location": "",
                    "page": "1",
                },
                timeout=30,
            )
            resp.raise_for_status()
            jobs = resp.json()

            if not isinstance(jobs, list):
                logger.warning("LinkedIn RapidAPI %s: unexpected type %s", company_name, type(jobs).__name__)
                return []

            logger.info("LinkedIn RapidAPI %s fetched %d jobs", company_name, len(jobs))
            return [self._normalize_generic(job, company_name) for job in jobs]

        except httpx.HTTPStatusError as exc:
            logger.warning("LinkedIn RapidAPI %s returned %s", company_name, exc.response.status_code)
            return []
        except Exception as exc:
            logger.warning("LinkedIn RapidAPI %s error: %s", company_name, exc)
            return []

    def _normalize_generic(self, raw: dict[str, Any], company_name: str) -> dict:
        """Normalize from generic RapidAPI LinkedIn Jobs Search."""
        job_id = raw.get("job_id", "") or raw.get("linkedin_job_url_cleaned", "")
        title = raw.get("job_title", "") or ""
        job_url = raw.get("linkedin_job_url_cleaned", "") or raw.get("job_url", "") or ""
        location = raw.get("job_location", "") or ""
        posted_at = raw.get("posted_date", "") or ""

        return {
            "external_id": f"linkedin-{job_id}" if job_id else f"linkedin-{hash(job_url)}",
            "company_slug": company_name,
            "title": title,
            "url": job_url,
            "platform": self.PLATFORM,
            "location_raw": location,
            "remote_scope": self._detect_remote_scope(location, title),
            "department": "",
            "employment_type": raw.get("job_employment_type", "") or "",
            "posted_at": posted_at,
            "raw_json": raw,
        }

    # ------------------------------------------------------------------
    # Fallback: LinkedIn public guest search (rate-limited, fragile)
    # ------------------------------------------------------------------

    def _fetch_via_public_search(self, company_name: str) -> list[dict]:
        """Fallback: scrape LinkedIn's public guest job search page.

        Rate-limited to max 1 request per 10 seconds. Fragile.
        """
        global _last_request_time
        now = time.time()
        wait = 10.0 - (now - _last_request_time)
        if wait > 0:
            time.sleep(wait)

        client = self._get_client()

        try:
            resp = client.get(
                LINKEDIN_SEARCH_URL,
                params={
                    "keywords": company_name,
                    "location": "",
                    "start": "0",
                    "f_C": "",
                },
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                },
                timeout=15,
            )
            _last_request_time = time.time()
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            _last_request_time = time.time()
            logger.warning("LinkedIn public %s returned %s (may be rate-limited)", company_name, exc.response.status_code)
            return []
        except httpx.RequestError as exc:
            _last_request_time = time.time()
            logger.warning("LinkedIn public %s request failed: %s", company_name, exc)
            return []

        html = resp.text
        if not html or len(html) < 100:
            logger.warning("LinkedIn public %s: empty or blocked response (len=%d)", company_name, len(html))
            return []

        jobs = self._parse_linkedin_html(html, company_name)
        logger.info("LinkedIn public %s parsed %d jobs from HTML", company_name, len(jobs))
        return jobs

    def _parse_linkedin_html(self, html: str, company_name: str) -> list[dict]:
        """Parse LinkedIn guest job search HTML."""
        results = []

        card_pattern = re.compile(
            r'<div[^>]*class="[^"]*base-card[^"]*"[^>]*>.*?</div>\s*</li>',
            re.DOTALL,
        )
        cards = card_pattern.findall(html)

        for card in cards:
            try:
                title_match = re.search(r'<h3[^>]*class="[^"]*base-search-card__title[^"]*"[^>]*>\s*(.+?)\s*</h3>', card, re.DOTALL)
                title = title_match.group(1).strip() if title_match else ""
                title = re.sub(r"<[^>]+>", "", title).strip()

                url_match = re.search(r'<a[^>]*href="(https://www\.linkedin\.com/jobs/view/[^"?]+)', card)
                job_url = url_match.group(1) if url_match else ""

                company_match = re.search(r'<h4[^>]*class="[^"]*base-search-card__subtitle[^"]*"[^>]*>.*?<a[^>]*>\s*(.+?)\s*</a>', card, re.DOTALL)
                company = company_match.group(1).strip() if company_match else company_name
                company = re.sub(r"<[^>]+>", "", company).strip()

                loc_match = re.search(r'<span[^>]*class="[^"]*job-search-card__location[^"]*"[^>]*>\s*(.+?)\s*</span>', card, re.DOTALL)
                location = loc_match.group(1).strip() if loc_match else ""
                location = re.sub(r"<[^>]+>", "", location).strip()

                job_id_match = re.search(r'/jobs/view/[^/]*?(\d+)', job_url)
                job_id = job_id_match.group(1) if job_id_match else ""

                # Extract posting date
                date_match = re.search(r'<time[^>]*datetime="([^"]*)"', card)
                posted_at = date_match.group(1) if date_match else ""

                if title and job_url:
                    results.append({
                        "external_id": f"linkedin-{job_id}" if job_id else f"linkedin-{hash(job_url)}",
                        "company_slug": company_name,
                        "title": title,
                        "url": job_url,
                        "platform": self.PLATFORM,
                        "location_raw": location,
                        "remote_scope": self._detect_remote_scope(location, title),
                        "department": "",
                        "posted_at": posted_at,
                        "raw_json": {"company": company, "location": location},
                    })
            except Exception as exc:
                logger.debug("LinkedIn parse error on card: %s", exc)
                continue

        return results

    def _normalize(self, raw: dict[str, Any], slug: str) -> dict:
        return self._normalize_generic(raw, slug)
