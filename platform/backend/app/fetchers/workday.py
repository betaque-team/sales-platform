"""Fetch open positions from Workday career sites.

Workday is unlike Greenhouse/Lever/Ashby in three ways:

1. **Per-tenant subdomain + cluster:** every customer gets their own
   hostname of the form ``{tenant}.wd{N}.myworkdayjobs.com`` where
   ``N ∈ {1, 3, 5, 10, 12, …}`` is the data-center cluster. Amazon
   is on ``wd1``, NVIDIA on ``wd5``, Capital One on ``wd12``, etc.
   There's no central board directory — discovery happens by
   scraping a company's public careers page and extracting the
   ``myworkdayjobs.com`` URL.

2. **Per-tenant "site" name:** every tenant can host multiple job
   boards under one account (e.g. AT&T has ``ATTGeneral``,
   ``ATTcollege``, ``Cricket`` under the same ``att.wd1`` tenant).
   Only some board sites are externally accessible; picking the
   wrong one produces HTTP 401/404/422.

3. **POST-based JSON API with pagination:** the fetch is
   ``POST {base}/wday/cxs/{tenant}/{site}/jobs`` with a JSON body
   ``{limit, offset, searchText, appliedFacets}``. Results cap at
   20 per page (Workday's server-side hard limit regardless of
   requested ``limit``), total count lives in ``total``, and a
   cap of ``2000`` is documented upstream (after which Workday
   refuses to page further — confirmed empirically on NVIDIA/Citi).

Slug format
-----------
To fit the existing ``(platform, slug)`` contract without
changing the ``CompanyATSBoard`` schema, Workday slugs in our DB
are a composite: ``{tenant}/{cluster}/{site}``. Example:

    nvidia/wd5/NVIDIAExternalCareerSite

The fetcher splits this on ``/`` and builds the URL from the
three parts. The ``url_parser.py`` should recognise pasted
Workday URLs and decompose them into this shape.

Discovery
---------
Workday doesn't publish a customer directory. Our
``WORKDAY_PROBE_SLUGS`` list starts with 4 verified-live
enterprise tenants (NVIDIA, Salesforce, Citi, Capital One).
Ongoing discovery uses the fingerprint helper in
``app.services.ats_fingerprint`` — given a company's careers
page URL, it finds embedded ``myworkdayjobs.com`` links and
emits ``(tenant, cluster, site)`` tuples that can be added
to the probe list.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from app.fetchers.base import BaseFetcher

logger = logging.getLogger(__name__)

# Workday's server-side cap on `limit`. Anything >20 is clamped and the
# client still only gets 20 back. Pagination happens via `offset`.
_WORKDAY_PAGE_SIZE = 20

# Hard cap on how many pages we'll walk for one board. 100 pages × 20 per
# page = 2000 jobs, which matches Workday's own `total`-capped ceiling
# (confirmed empirically: NVIDIA reports `total: 2000` even when the
# real listing count is larger). Cap here protects against an edge case
# where `total` is NULL / malformed and we'd otherwise loop forever.
_WORKDAY_MAX_PAGES = 100


class WorkdayFetcher(BaseFetcher):
    """Fetch open positions from a Workday tenant.

    The ``slug`` for this fetcher is a ``/``-separated composite of
    ``(tenant, cluster, site)`` — see module docstring. Examples:

        nvidia/wd5/NVIDIAExternalCareerSite
        salesforce/wd12/External_Career_Site
        citi/wd5/2
    """

    PLATFORM = "workday"

    def fetch(self, slug: str) -> list[dict]:
        tenant, cluster, site = self._decompose_slug(slug)
        if not all((tenant, cluster, site)):
            logger.warning(
                "Workday %s: malformed slug — expected 'tenant/cluster/site', got %r",
                slug, slug,
            )
            return []

        client = self._get_client()
        url = f"https://{tenant}.{cluster}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
        all_jobs: list[dict] = []

        for page in range(_WORKDAY_MAX_PAGES):
            offset = page * _WORKDAY_PAGE_SIZE
            payload = {
                "limit": _WORKDAY_PAGE_SIZE,
                "offset": offset,
                "searchText": "",
                "appliedFacets": {},
            }
            try:
                resp = client.post(
                    url,
                    json=payload,
                    # Workday rejects requests without these — content-type
                    # is sometimes inferred by httpx but pinning explicitly
                    # avoids a class of "400 bad content type" edge cases
                    # on older Workday clusters (wd1, wd3).
                    headers={"Content-Type": "application/json", "Accept": "application/json"},
                )
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                code = exc.response.status_code
                if code in (401, 403):
                    # Board exists but isn't public (internal-only site)
                    # — common on enterprise tenants who expose only some
                    # of their sites externally. Nothing we can do; stop
                    # pagination cleanly.
                    logger.info("Workday %s: site requires auth (HTTP %d)", slug, code)
                elif code == 404:
                    # Site name is wrong. The tenant exists but this site
                    # string doesn't map to anything. The probe-list /
                    # fingerprinter should produce valid (tenant, site)
                    # pairs, but this guards against a stale entry.
                    logger.info("Workday %s: site not found (HTTP 404)", slug)
                elif code == 422:
                    # Workday returns 422 for some body-level validation
                    # failures — e.g. an appliedFacets shape the tenant
                    # doesn't understand. Log and bail on this board.
                    logger.warning("Workday %s: API rejected payload (HTTP 422)", slug)
                else:
                    logger.warning("Workday %s: HTTP %d", slug, code)
                break
            except httpx.RequestError as exc:
                logger.warning("Workday %s: request failed: %s", slug, exc)
                break

            try:
                data = resp.json()
            except Exception:
                logger.warning("Workday %s: non-JSON response at offset=%d", slug, offset)
                break

            postings = data.get("jobPostings", []) or []
            total = data.get("total", 0)

            if not postings:
                # Empty page — end of results. Don't keep requesting
                # past this, even if total > offset (occasionally the
                # two disagree on the last page).
                break

            all_jobs.extend(self._normalize(p, slug, tenant, cluster, site) for p in postings)

            # If we've got everything the server says it has, stop. The
            # explicit break (instead of just relying on the empty-page
            # check next loop) saves one wasted request.
            if offset + len(postings) >= total:
                break

        logger.info("Workday %s: fetched %d jobs", slug, len(all_jobs))
        return all_jobs

    @staticmethod
    def _decompose_slug(slug: str) -> tuple[str, str, str]:
        """Split the composite slug into ``(tenant, cluster, site)``.

        Returns tuple of empty strings on malformed input so callers can
        short-circuit with ``all((tenant, cluster, site))`` rather than
        raising. Keeps the fetcher contract "returns list" even on
        garbage input.
        """
        parts = slug.split("/")
        if len(parts) != 3:
            return ("", "", "")
        tenant, cluster, site = parts[0].strip(), parts[1].strip(), parts[2].strip()
        # Cluster must be ``wd\d+`` — sanity-check so a slug like
        # ``nvidia/wd5/NVIDIA`` doesn't get silently rewritten via a
        # typo like ``nvidia/d5/NVIDIA`` into an invalid URL.
        if not cluster.startswith("wd") or not cluster[2:].isdigit():
            return ("", "", "")
        return (tenant, cluster, site)

    def _normalize(
        self,
        raw: dict[str, Any],
        slug: str,
        tenant: str,
        cluster: str,
        site: str,
    ) -> dict:
        """Normalize a single Workday job posting to our standard shape.

        Workday posting fields observed (NVIDIA sample):
            title, externalPath, locationsText, postedOn, bulletFields

        ``externalPath`` is a relative URL fragment like
        ``/en-US/NVIDIAExternalCareerSite/job/US-CA-Santa-Clara/…``
        which needs the tenant hostname prepended to become a full URL.

        ``postedOn`` is a human-readable "Posted N days ago"-style
        string, not a timestamp — left as-is in the raw payload so a
        future parser can extract it if we need a real datetime.
        """
        title = (raw.get("title") or "").strip()
        location_raw = (raw.get("locationsText") or "").strip()
        external_path = raw.get("externalPath") or ""

        # The job's unique identity is the externalPath (per-tenant
        # unique per board) — safer than any numeric id because Workday
        # doesn't consistently expose one in the list response.
        # Composite external_id prefixed with the slug so a posting
        # moving between tenants (rare) doesn't collide.
        if external_path:
            external_id = f"workday-{tenant}-{external_path.strip('/').replace('/', '_')[:400]}"
        else:
            # Extremely rare fallback — if externalPath is missing we
            # fall back to title+location, capped, to keep the column
            # under the 500-char limit on Job.external_id.
            external_id = f"workday-{tenant}-{(title + '-' + location_raw)[:400]}"

        # Build a publicly-accessible job URL. The external_path
        # already starts with ``/en-US/...`` so prepend host only.
        if external_path:
            job_url = f"https://{tenant}.{cluster}.myworkdayjobs.com{external_path}"
        else:
            job_url = f"https://{tenant}.{cluster}.myworkdayjobs.com/en-US/{site}"

        remote_scope = self._detect_remote_scope(location_raw, title)

        return {
            "external_id": external_id,
            "company_slug": slug,
            "title": title,
            "url": job_url,
            "platform": self.PLATFORM,
            "location_raw": location_raw,
            "remote_scope": remote_scope,
            # Workday doesn't expose department in the list view — it's
            # on the detail page. Left empty; a future enrichment pass
            # can fetch per-job if needed.
            "department": "",
            "employment_type": "",
            "posted_at": raw.get("postedOn") or "",
            "raw_json": raw,
        }
