"""Fetch open positions from Wellfound (formerly AngelList Talent).

History
-------
The original implementation hit ``https://wellfound.com/graphql``
directly via httpx. STATUS 2026-04-17: Cloudflare returned HTTP 403
to every header set we tried. F254 attempt 2: Wellfound migrated to
DataDome, which adds TLS/IP-fingerprint gating on top of the JS
challenge — so even a real headless Chromium with stealth scripts
gets the 2.5KB challenge shell on ``/company/*`` paths.

Current strategy
----------------
Use the shared ``app.services.playwright_browser`` service to load
the company's job page in a real Chromium with playwright-stealth
applied. Capture the GraphQL XHR that the page itself fires (rather
than walking the DOM, whose markup churns) and normalise from the
JSON payload.

Honest expectations
-------------------
* DataDome's bot detection is sophisticated; our best-effort headless
  Chromium currently fails the challenge on protected paths from
  datacenter IPs (Oracle ARM VM included). A real-IP residential
  proxy or a managed bypass service (Browserbase / ScrapingBee /
  ZenRows) would be needed for reliable success.
* This fetcher is therefore **best-effort**: when DataDome blocks,
  we log the reason and return ``[]`` cleanly so the platform-scan
  flow continues without errors. The stale-board cull will deactivate
  Wellfound boards after 5 consecutive empty scans (current behaviour).
* We keep the Playwright code in place because (a) DataDome occasionally
  ships a regression that lets stealth pass, (b) some specific
  customer slugs may not be protected, and (c) the same browser
  primitive is used for the v6 Apply Routine — having it always
  ready in the worker image is operationally cheaper than launching
  on demand.

Sync/async bridge
-----------------
The fetcher base class is synchronous (Celery tasks call
``fetcher.fetch(slug)``), but the Playwright service is async-only.
We bridge via ``asyncio.run`` per call. Cost: ~2s for Chromium
relaunch on each scan because the event loop is fresh. Acceptable
for a fetcher run twice daily; if Wellfound ever produces enough
boards to make this matter, switch the BaseFetcher to expose an
optional async path.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.fetchers.base import BaseFetcher

logger = logging.getLogger(__name__)


# Public Wellfound URL pattern that lists a company's open jobs.
# Slug is the company's Wellfound handle (e.g. ``figma`` for Figma).
_PUBLIC_JOB_PAGE = "https://wellfound.com/company/{slug}/jobs"

# The GraphQL request the public page fires to hydrate its job list.
# We intercept any response whose URL contains this substring rather
# than calling the GraphQL endpoint directly — Wellfound's GraphQL
# is at ``/graphql`` and the page sends a ``StartupJobs`` operation
# (or similar; the operation name has churned over time).
_GRAPHQL_PATH = "/graphql"

# Wall-clock budget per slug. DataDome's challenge JS takes 5-15s
# in a real browser on a clean fingerprint; on datacenter IPs it
# never resolves. Hard cap so a single bad slug can't pin the worker.
_PER_SLUG_TIMEOUT_S = 25


class WellfoundFetcher(BaseFetcher):
    """Best-effort Wellfound fetcher via the Playwright service."""

    PLATFORM = "wellfound"

    def fetch(self, slug: str) -> list[dict]:
        """Public entry point — sync to match BaseFetcher.fetch signature.

        Drives the async Playwright code via ``asyncio.run``. Returns
        ``[]`` on any failure (DataDome block, timeout, Playwright
        unavailable in this environment, parse failure) — never raises
        so the platform-scan flow can survive a Wellfound outage.
        """
        try:
            return asyncio.run(self._fetch_async(slug))
        except Exception as exc:
            logger.warning(
                "Wellfound %s: fetch failed (%s) — returning empty list",
                slug, type(exc).__name__,
            )
            return []

    async def _fetch_async(self, slug: str) -> list[dict]:
        """Async implementation — open browser, load page, capture XHR,
        normalise jobs. Defensive against every failure mode."""
        # Lazy import so test environments without Playwright installed
        # don't blow up at module import time. Same pattern used by the
        # service module.
        try:
            from app.services.playwright_browser import (
                BrowserError,
                BrowserSession,
                PlaywrightUnavailable,
            )
        except ImportError:
            logger.warning(
                "Wellfound %s: app.services.playwright_browser not importable",
                slug,
            )
            return []

        url = _PUBLIC_JOB_PAGE.format(slug=slug)
        try:
            async with BrowserSession() as session:
                # Two passes:
                #   1. Capture the GraphQL XHR while navigating. Most
                #      reliable when DataDome lets us through — the
                #      JSON shape is stable across UI revs.
                #   2. Fall back to DOM scrape if no XHR fires (e.g.
                #      page renders fully server-side).
                try:
                    payload = await asyncio.wait_for(
                        session.capture_xhr(
                            url_substring=_GRAPHQL_PATH,
                            navigate_to=url,
                            method="POST",
                            timeout_ms=_PER_SLUG_TIMEOUT_S * 1000,
                        ),
                        timeout=_PER_SLUG_TIMEOUT_S,
                    )
                except (BrowserError, asyncio.TimeoutError) as exc:
                    logger.info(
                        "Wellfound %s: no GraphQL XHR captured (%s); "
                        "falling back to DOM",
                        slug, exc,
                    )
                    payload = None

                if payload:
                    jobs = self._normalize_graphql(payload, slug)
                    if jobs:
                        return jobs
                    logger.info(
                        "Wellfound %s: GraphQL captured but yielded 0 jobs; "
                        "trying DOM scrape", slug,
                    )

                # DOM fallback: walk the rendered HTML for job links.
                # When DataDome blocks, the HTML is the 2.5KB challenge
                # shell and this also returns []. Either way we exit
                # cleanly with no exception bubbling up.
                html = await session.html()
                if self._looks_like_datadome_challenge(html):
                    logger.info(
                        "Wellfound %s: DataDome challenge detected "
                        "(html=%d bytes) — best-effort fetch returns empty",
                        slug, len(html),
                    )
                    return []
                return self._normalize_dom(html, slug)

        except PlaywrightUnavailable:
            logger.warning(
                "Wellfound %s: Playwright not installed in this environment",
                slug,
            )
            return []
        except BrowserError as exc:
            logger.warning("Wellfound %s: browser error: %s", slug, exc)
            return []

    @staticmethod
    def _looks_like_datadome_challenge(html: str) -> bool:
        """Heuristic detector for DataDome's challenge shell.

        The shell is consistently ~1.5-2.5 KB and contains specific
        markers. Two checks (size + token) so a future redesign of
        the shell doesn't trick us into trusting empty pages as
        real content.
        """
        if not html or len(html) > 8000:
            return False
        markers = ("enable JS", "datadome", "x-dd-b", '"cmsg"', "id=\"cmsg\"")
        return any(m in html.lower() for m in (mm.lower() for mm in markers))

    def _normalize_graphql(self, payload: Any, slug: str) -> list[dict]:
        """Walk the captured GraphQL response and emit normalised jobs.

        The exact shape changes with Wellfound UI releases. We probe
        a few common locations defensively — pulling out anything
        with a recognisable ``id`` + ``title`` pair.
        """
        if not isinstance(payload, dict):
            return []
        # Common path: ``data.startup.jobListings`` (legacy GraphQL).
        listings: list = []
        try:
            data = payload.get("data") or {}
            startup = data.get("startup") or data.get("company") or {}
            listings = (
                startup.get("jobListings")
                or startup.get("jobs")
                or startup.get("openPositions")
                or []
            )
        except Exception:
            listings = []
        if not isinstance(listings, list):
            return []

        company_name = ""
        try:
            company_name = (payload.get("data") or {}).get("startup", {}).get("name", "") or slug
        except Exception:
            company_name = slug

        out: list[dict] = []
        for job in listings:
            if not isinstance(job, dict):
                continue
            normalised = self._build_job(job, slug, company_name)
            if normalised:
                out.append(normalised)
        return out

    def _normalize_dom(self, html: str, slug: str) -> list[dict]:
        """Last-resort DOM scrape. Pulls anchor tags whose href looks
        like a Wellfound job permalink and treats their text as the
        title. Returns whatever we can salvage — often empty when
        DataDome blocks.
        """
        import re

        # Match anchors like /company/{slug}/jobs/12345-title-slug
        pattern = re.compile(
            rf'<a[^>]+href="(/company/{re.escape(slug)}/jobs/(\d+)[^"]*)"[^>]*>([^<]+)</a>',
            re.IGNORECASE,
        )
        seen: set[str] = set()
        out: list[dict] = []
        for match in pattern.finditer(html or ""):
            href, job_id, title = match.group(1), match.group(2), match.group(3)
            if job_id in seen:
                continue
            seen.add(job_id)
            out.append(self._build_job(
                {"id": job_id, "title": title.strip(), "slug": ""},
                slug, slug,
                fallback_url=f"https://wellfound.com{href}",
            ))
        return out

    def _build_job(
        self,
        raw: dict,
        slug: str,
        company_name: str,
        *,
        fallback_url: str | None = None,
    ) -> dict:
        """Build a normalised job dict from a raw GraphQL/DOM record.

        Applies the same field caps as F253 (HN fetcher) so an oversize
        title from a future GraphQL revision can't overflow
        ``Job.title_normalized String(500)`` and poison the batch.
        """
        job_id = str(raw.get("id") or "").strip()
        if not job_id:
            return {}
        raw_title = (raw.get("title") or "").strip()
        if not raw_title:
            raw_title = "Open position"
        # Title cap — see F253 for rationale.
        title = raw_title[:200]
        # URL: prefer GraphQL-provided permalink, fall back to public page.
        url = (
            raw.get("url")
            or raw.get("permalink")
            or fallback_url
            or f"https://wellfound.com/company/{slug}/jobs/{job_id}"
        )[:2048]
        location_raw = (
            ", ".join(raw.get("locationNames", [])[:3])
            if isinstance(raw.get("locationNames"), list)
            else (raw.get("location") or "")
        )[:255]
        remote_scope = "remote" if raw.get("remote") else self._detect_remote_scope(location_raw, title) or ""

        return {
            "external_id": f"wf-{job_id}",
            "company_slug": slug,
            "company_name": company_name[:200] if company_name else slug,
            "title": title,
            "url": url,
            "platform": self.PLATFORM,
            "location_raw": location_raw,
            "remote_scope": remote_scope or "",
            "department": "",
            "employment_type": (raw.get("jobType") or "")[:50],
            "salary_range": (raw.get("compensation") or "")[:100],
            "posted_at": raw.get("liveStartAt") or "",
            "raw_json": {
                "wellfound_job_id": job_id,
                "wellfound_company_slug": slug,
                "wellfound_company_name": company_name,
                "title": raw_title,
            },
        }
