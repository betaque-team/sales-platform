"""Fetch jobs from Y Combinator's Work at a Startup (workatastartup.com).

Why this fetcher exists
-----------------------
YC-backed companies skew heavily toward infra / dev-tools / AI —
roughly our exact hiring cluster. Until now we've been probing YC
slugs opportunistically via ``discovery_task``'s hardcoded slug
lists; this fetcher turns YC into a first-class automated source.

Integration model
-----------------
Aggregator pattern — single synthetic board, slug ``__all__``,
platform ``yc_waas``. Each emitted job carries its own
``company_name`` + slug, so ``scan_task``'s aggregator branch
resolves a distinct Company row per hirer.

Data strategy (why two stages)
------------------------------
YC exposes two public surfaces we can chain:

  1. **Company enumeration** — ``yc-oss.github.io``'s GitHub-Pages
     JSON dumps. Per-batch files (e.g. ``winter-2025.json``) list
     ~150-450 companies with 29 fields each: batch, industry,
     regions, team_size, launched_at, ``isHiring`` boolean,
     one-liner, tags, stage. **But no jobs.**

  2. **Jobs pull** — ``workatastartup.com/jobs/search?q=<term>``
     returns ~16-22 postings per call with: id, title, jobType,
     location, salary, companyName, companySlug, applyUrl, …
     The ``q`` param is required (empty → zero hits). The
     ``batch=Wxx`` filter is documented but **ignored** by the
     server (tested), so we can't scope by batch server-side.

We chain them: iterate a keyword list (``engineer``, ``security``,
``devops``, etc.) against ``/jobs/search``, dedupe by ``job.id``,
then left-join the ``companySlug`` back to the batch data from
step 1 so the emitted job dict carries both the job's own fields
AND the richer company metadata (batch, industry, team size, …).

Why a keyword list
------------------
``/jobs/search`` requires ``q``. Empty returns nothing. We
maintain a small list tuned to our infra/security cluster plus a
handful of generic role terms so we still surface backend /
frontend / product jobs for the broader relevance scorer.

Rate limits
-----------
Both surfaces have no observed 429s at modest volume. We send at
most ~12-18 HTTP calls per run (batches + keywords). ``scan_all_
platforms`` fires every 30 min → ~24-36 calls/hour to each host.
Comfortable.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from app.fetchers.base import BaseFetcher

logger = logging.getLogger(__name__)

# GitHub-Pages CDN — effectively unlimited, cheap JSON dumps.
_YC_BATCH_URL = "https://yc-oss.github.io/api/batches/{season}-{year}.json"

# YC publishes batch files twice a year (winter / summer); "spring"
# and "fall" filenames appear occasionally for special cohorts. We
# probe all four seasons to be resilient to schedule changes.
_SEASONS = ("winter", "summer", "spring", "fall")

# Which batches to crawl. YC cos stay "hiring" for 6-18 months
# post-graduation, so we cover the last ~3 years. The list is
# frontier-first so newer batches get resolved first (yielding
# more recent roles).
#
# Update this once a year. A YC cohort in its 4th+ year tends to
# have graduated to using their own Greenhouse / Ashby board,
# which our existing fetchers already cover.
_RECENT_BATCHES = (
    (2025, "winter"), (2025, "summer"), (2025, "spring"), (2025, "fall"),
    (2024, "winter"), (2024, "summer"), (2024, "spring"), (2024, "fall"),
    (2023, "winter"), (2023, "summer"),
)

# Keyword list for ``/jobs/search``. Order matters only for
# deterministic test fixtures — semantically it's a set. Deliberately
# skewed toward our infra/security cluster but includes enough
# generic terms to catch the long tail without 50 HTTP calls.
#
# Each keyword returns ~20 jobs; we expect ~70-80% overlap after
# dedup. Net: ~200-350 unique jobs per run on a typical week.
_SEARCH_KEYWORDS = (
    "engineer",       # catch-all — widest net
    "devops",
    "infrastructure",
    "platform",
    "reliability",
    "security",
    "cloud",
    "kubernetes",
    "backend",
    "founding",       # YC-specific shape — "founding engineer" is common
    "staff",          # senior IC tag
    "senior",
)

# WaaS jobs API. Accept-JSON is the pivot between the HTML page
# and the JSON blob — sending `Accept: application/json` returns
# ``{"jobs":[…]}`` with 13 fields per job.
_WAAS_SEARCH_URL = "https://www.workatastartup.com/jobs/search"


class YCWaaSFetcher(BaseFetcher):
    """Fetcher for Y Combinator's Work at a Startup listings."""

    PLATFORM = "yc_waas"

    # ── Stage 1: company enumeration ────────────────────────────────

    def _fetch_companies(
        self, client: httpx.Client
    ) -> dict[str, dict]:
        """Fetch ``isHiring`` companies from the recent batches.

        Returns ``{companySlug: company_record}`` — keyed on slug
        because the WaaS jobs response references companies by
        slug (``companySlug``), not by id.

        Silently tolerates missing batch files (404) — not every
        season publishes one. Returns whatever we could gather.
        """
        companies: dict[str, dict] = {}
        for year, season in _RECENT_BATCHES:
            url = _YC_BATCH_URL.format(season=season, year=year)
            try:
                resp = client.get(url, timeout=20)
                if resp.status_code == 404:
                    logger.debug("YC batch %s-%d: 404 (no file this season)", season, year)
                    continue
                resp.raise_for_status()
                batch_data = resp.json()
            except Exception as exc:
                logger.warning("YC batch %s-%d fetch failed: %s", season, year, exc)
                continue

            if not isinstance(batch_data, list):
                logger.warning("YC batch %s-%d: unexpected shape (not a list)", season, year)
                continue

            for rec in batch_data:
                if not isinstance(rec, dict):
                    continue
                # Keep only actively-hiring cos — everyone else clutters
                # the company table. A co that flips `isHiring: true`
                # later will get picked up on the next run.
                if not rec.get("isHiring"):
                    continue
                slug = (rec.get("slug") or "").strip()
                if not slug:
                    continue
                # First-write-wins if a company appears in multiple
                # batch files (rare but possible on re-classifications).
                companies.setdefault(slug, rec)

        logger.info("YC WaaS: collected %d hiring companies across %d batches", len(companies), len(_RECENT_BATCHES))
        return companies

    # ── Stage 2: jobs search ────────────────────────────────────────

    def _fetch_jobs_for_keyword(
        self, client: httpx.Client, keyword: str
    ) -> list[dict]:
        """One WaaS ``/jobs/search`` call. Returns raw job dicts.

        Response shape on 200::

            {"jobs": [
                {"id": 12345, "title": "Senior Platform Engineer",
                 "jobType": "fulltime", "location": "SF / Remote",
                 "salary": "$180K - $250K", "companyName": "Acme",
                 "companySlug": "acme", "applyUrl": "/companies/acme/jobs/12345",
                 …},
                …
            ]}

        Errors return an empty list — we'd rather lose one keyword
        than fail the whole run.
        """
        try:
            resp = client.get(
                _WAAS_SEARCH_URL,
                params={"q": keyword},
                headers={"Accept": "application/json"},
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning("YC WaaS /jobs/search q=%r failed: %s", keyword, exc)
            return []
        jobs = data.get("jobs") if isinstance(data, dict) else None
        if not isinstance(jobs, list):
            return []
        return [j for j in jobs if isinstance(j, dict)]

    # ── Fetch entry point ──────────────────────────────────────────

    def fetch(self, slug: str) -> list[dict]:
        """Fetch + join YC companies and WaaS job postings.

        ``slug`` is ignored — aggregator convention. Returns a list
        of normalized job dicts. Safe to call repeatedly; dedupe
        happens upstream in scan_task via ``(platform, external_id)``.
        """
        client = self._get_client()
        companies = self._fetch_companies(client)

        # Dedupe jobs across keyword calls by id.
        seen_ids: set[int | str] = set()
        raw_jobs: list[dict] = []
        for kw in _SEARCH_KEYWORDS:
            for job in self._fetch_jobs_for_keyword(client, kw):
                jid = job.get("id")
                if jid is None or jid in seen_ids:
                    continue
                seen_ids.add(jid)
                raw_jobs.append(job)

        logger.info(
            "YC WaaS: %d unique jobs across %d keywords (dedup by id)",
            len(raw_jobs), len(_SEARCH_KEYWORDS),
        )

        normalized: list[dict] = []
        for job in raw_jobs:
            co_slug = (job.get("companySlug") or "").strip()
            company_meta = companies.get(co_slug, {}) if co_slug else {}
            nj = self._normalize(job, company_meta)
            if nj:
                normalized.append(nj)

        logger.info("YC WaaS: %d jobs after normalization", len(normalized))
        return normalized

    # Mandatory override. Base class signature is ``_normalize(raw, slug)``;
    # we extend with a second arg (company metadata) because the WaaS
    # response is sparse and the batch files carry the richer data.
    def _normalize(self, raw: dict, company_meta: dict | None = None) -> dict:  # type: ignore[override]
        title = (raw.get("title") or "").strip()
        if not title:
            return {}

        # Company resolution — prefer the rich batch record's canonical
        # name + slug over WaaS's own ``companyName`` / ``companySlug``
        # because the batch files have authoritative capitalization
        # (e.g. "Ramp" not "ramp") and we dedupe against Company.name.
        if company_meta:
            company_name = (company_meta.get("name") or "").strip() or (raw.get("companyName") or "").strip()
            company_slug = (company_meta.get("slug") or "").strip() or (raw.get("companySlug") or "").strip()
        else:
            company_name = (raw.get("companyName") or "").strip()
            company_slug = (raw.get("companySlug") or "").strip()
        if not company_name:
            # A job without a company is unusable — we can't attribute
            # it or route outreach. Drop quietly.
            return {}
        # Sanitize the slug to our convention (lowercase, dashes).
        if not company_slug:
            company_slug = re.sub(
                r"[^a-z0-9-]", "",
                company_name.lower().replace(" ", "-"),
            )[:100] or "unknown-yc-company"

        # External id — keep WaaS job id for idempotent upserts. Namespace
        # with `yc-` so join debug is obvious.
        job_id = raw.get("id")
        external_id = f"yc-{job_id}" if job_id is not None else f"yc-{company_slug}-{title[:40]}"

        # Absolute URL — WaaS gives us either a full URL or a relative
        # `/companies/{slug}/jobs/{id}` path.
        apply_url = (raw.get("applyUrl") or "").strip()
        if apply_url and not apply_url.startswith("http"):
            apply_url = f"https://www.workatastartup.com{apply_url}"
        if not apply_url:
            # Fall back to company profile page if no job-specific link
            # (rare but possible when WaaS is still indexing).
            apply_url = f"https://www.workatastartup.com/companies/{company_slug}"

        # Location + remote scope.
        location_raw = (raw.get("location") or "").strip()
        remote_scope = self._detect_remote_scope(location_raw, title, (raw.get("roleType") or "")) or ""
        # WaaS's `roleType` is often literal "REMOTE" / "ONSITE" /
        # "HYBRID" — map those even if the location_raw check missed.
        role_type_upper = (raw.get("roleType") or "").upper()
        if not remote_scope and "REMOTE" in role_type_upper:
            remote_scope = "remote"

        # Salary passthrough — WaaS formats it as "$120K - $180K" or
        # similar; just preserve the string.
        salary_range = (raw.get("salary") or "").strip()

        # Employment type — fulltime / intern / contract.
        employment_type = (raw.get("jobType") or "").strip().lower().replace(" ", "_")

        # Department hint from company tags when present.
        department = ""
        tags = (company_meta or {}).get("tags") or []
        if isinstance(tags, list) and tags:
            department = str(tags[0])[:80]

        return {
            "external_id": external_id,
            "company_slug": company_slug,
            "company_name": company_name,
            "title": title,
            "url": apply_url,
            "platform": self.PLATFORM,
            "location_raw": location_raw,
            "remote_scope": remote_scope,
            "department": department,
            "employment_type": employment_type,
            "salary_range": salary_range,
            "posted_at": "",  # WaaS doesn't expose post-date in the search blob.
            # Keep both the job payload AND the joined company metadata
            # so downstream tools (intelligence, sales outreach) can pull
            # richer context (batch, industry, team size, stage) without
            # a separate fetch.
            "raw_json": {
                "yc_job_id": job_id,
                "yc_job_type": raw.get("jobType"),
                "yc_role_type": raw.get("roleType"),
                "yc_apply_url": apply_url,
                "yc_company_one_liner": (company_meta or {}).get("one_liner"),
                "yc_company_batch": (company_meta or {}).get("batch"),
                "yc_company_industry": (company_meta or {}).get("industry"),
                "yc_company_team_size": (company_meta or {}).get("team_size"),
                "yc_company_stage": (company_meta or {}).get("stage"),
                "yc_company_website": (company_meta or {}).get("website"),
                "yc_company_tags": tags,
                "company_name": company_name,
            },
        }
