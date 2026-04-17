"""Detect which ATS a company uses by fingerprinting its public careers page.

Given a URL (company domain OR careers page), fetch the HTML and look for
ATS-specific signatures — script tags, iframe srcs, direct links, meta
tags. Returns zero or more ``ATSFingerprint`` tuples each identifying a
``(platform, slug)`` pair that our fetcher map can drive scans against.

Why this exists
---------------
Most ATSes we scan have no public directory we can enumerate — we
maintain hand-curated probe slug lists per platform and they go stale
every few months as customers migrate. Scraping the company side
instead inverts the problem: give us a list of target-profile domains
(e.g. a Crunchbase CSV of cloud/security startups) and let this module
figure out which ATSes they use.

It also powers Workday discovery specifically. Workday has no central
customer list and every tenant lives on its own subdomain
(``{tenant}.wd{N}.myworkdayjobs.com``), so the only way to find new
Workday boards at scale is to scrape customer careers pages for
embedded ``myworkdayjobs.com`` URLs — exactly what this module does.

Usage
-----

    from app.services.ats_fingerprint import detect_ats_from_url
    fps = detect_ats_from_url("https://jobs.nvidia.com/")
    # → [ATSFingerprint(platform="workday",
    #                   slug="nvidia/wd5/NVIDIAExternalCareerSite",
    #                   careers_url="https://nvidia.wd5.myworkdayjobs.com/...")]

    # Companies often have multiple ATSes (internal vs university
    # boards, different business units). Callers should dedupe by
    # (platform, slug) and decide which to register.

Not in scope (yet)
------------------
* Cloudflare-protected pages — fetches httpx-only. Pages that return
  403 are skipped. A future variant can route through Playwright if
  the coverage matters (Wellfound is the current non-covered case).
* Pagination into ATS customer pages. This function is "what ATS does
  one specific company use," not "enumerate every ATS customer."
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Iterable, Optional

import httpx

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ATSFingerprint:
    """One ATS signal detected on a careers page.

    ``careers_url`` is the full URL we extracted the fingerprint from
    (useful for the admin UI / debug logs so a human can click through
    and verify the match). ``slug`` is always in the shape our fetcher
    map expects — e.g. Workday's slug is the composite
    ``{tenant}/{cluster}/{site}``, Greenhouse/Lever/Ashby are simple
    string slugs.
    """

    platform: str
    slug: str
    careers_url: str


# Default headers mimicking a real Chrome. Some company careers pages
# (especially enterprise ones on Akamai / Cloudflare) gate on
# User-Agent + Accept-Language together.
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Per-platform regex patterns that extract the slug from a URL we find
# inside the HTML. Order matters: we iterate in this order and the first
# match per platform wins (deduped across platforms at the caller level
# because a single page can reference multiple platforms).
#
# Each pattern must extract ALL components needed to rebuild the slug —
# for Workday that's three groups (tenant, cluster, site); for the
# others it's a single slug group. Keep in sync with
# ``app.fetchers.url_parser`` which handles the inverse (URL → slug)
# for the pasted-link submission feature.
_PLATFORM_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # Workday: https://{tenant}.wd{N}.myworkdayjobs.com/en-US/{site}/
    # or                                               /{site}/
    # Slug is the composite {tenant}/wd{N}/{site}.
    (
        "workday",
        re.compile(
            r"https?://([a-zA-Z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z-]+/)?([A-Za-z0-9_-]+)",
            re.IGNORECASE,
        ),
    ),
    # Greenhouse: boards.greenhouse.io/{slug} (with optional /jobs/N)
    (
        "greenhouse",
        re.compile(
            r"https?://boards\.greenhouse\.io/([a-zA-Z0-9-]+)",
            re.IGNORECASE,
        ),
    ),
    # Greenhouse — embedded variant at job-boards.greenhouse.io
    (
        "greenhouse",
        re.compile(
            r"https?://job-boards\.greenhouse\.io/([a-zA-Z0-9-]+)",
            re.IGNORECASE,
        ),
    ),
    # Lever: jobs.lever.co/{slug}
    (
        "lever",
        re.compile(
            r"https?://jobs\.lever\.co/([a-zA-Z0-9-]+)",
            re.IGNORECASE,
        ),
    ),
    # Ashby: jobs.ashbyhq.com/{slug}
    (
        "ashby",
        re.compile(
            r"https?://jobs\.ashbyhq\.com/([a-zA-Z0-9-]+)",
            re.IGNORECASE,
        ),
    ),
    # Ashby subdomain form: {slug}.ashbyhq.com — explicitly EXCLUDE
    # ``jobs`` + ``api`` + ``www`` as captured slugs. Without the
    # negative alternation, a URL like ``https://jobs.ashbyhq.com/foo``
    # double-matches: once as the canonical path form (captures `foo`)
    # and once as the subdomain form (captures `jobs`). The dedup at
    # the caller level hides the duplicate for the same platform, but
    # the spurious `jobs`/`api`/`www` slug still lands in the output
    # as a second fingerprint with a bogus slug.
    (
        "ashby",
        re.compile(
            r"https?://(?!(?:jobs|api|www)\.)([a-zA-Z0-9-]+)\.ashbyhq\.com",
            re.IGNORECASE,
        ),
    ),
    # Workable: apply.workable.com/{slug}
    (
        "workable",
        re.compile(
            r"https?://apply\.workable\.com/([a-zA-Z0-9-]+)",
            re.IGNORECASE,
        ),
    ),
    # BambooHR: {slug}.bamboohr.com — exclude www/api/jobs same as
    # Ashby; otherwise a link to www.bamboohr.com marketing lands as
    # a bogus `www` slug fingerprint.
    (
        "bamboohr",
        re.compile(
            r"https?://(?!(?:www|api|jobs)\.)([a-zA-Z0-9-]+)\.bamboohr\.com",
            re.IGNORECASE,
        ),
    ),
    # SmartRecruiters: careers.smartrecruiters.com/{Slug} — CASE SENSITIVE
    (
        "smartrecruiters",
        re.compile(
            r"https?://careers\.smartrecruiters\.com/([A-Za-z0-9-]+)",
        ),
    ),
    (
        "smartrecruiters",
        re.compile(
            r"https?://jobs\.smartrecruiters\.com/([A-Za-z0-9-]+)",
        ),
    ),
    # Recruitee: {slug}.recruitee.com — exclude common non-customer
    # subdomains so a marketing site link to `www.recruitee.com` or
    # `careers.recruitee.com` doesn't land as a bogus slug.
    (
        "recruitee",
        re.compile(
            r"https?://(?!(?:www|api|careers|support|blog)\.)([a-zA-Z0-9-]+)\.recruitee\.com",
            re.IGNORECASE,
        ),
    ),
    # Jobvite (documented as platform-dead, kept for completeness)
    (
        "jobvite",
        re.compile(
            r"https?://jobs\.jobvite\.com/([a-zA-Z0-9-]+)",
            re.IGNORECASE,
        ),
    ),
]


def _extract_fingerprints(html: str, source_url: str) -> list[ATSFingerprint]:
    """Run every pattern against ``html`` and return matched fingerprints.

    Deduped in-function by ``(platform, slug)`` so the same URL appearing
    twice on one page (e.g. an inline iframe and a footer link) doesn't
    surface as two fingerprints. Preserves first-seen ordering for
    stable test assertions.
    """
    seen: set[tuple[str, str]] = set()
    out: list[ATSFingerprint] = []
    for platform, pattern in _PLATFORM_PATTERNS:
        for match in pattern.finditer(html):
            if platform == "workday":
                # Three-group pattern: (tenant, cluster, site)
                tenant, cluster, site = match.group(1), match.group(2), match.group(3)
                slug = f"{tenant}/{cluster}/{site}"
                careers_url = (
                    f"https://{tenant}.{cluster}.myworkdayjobs.com/en-US/{site}"
                )
            else:
                # One-group pattern: slug only
                slug = match.group(1)
                careers_url = match.group(0)
            key = (platform, slug)
            if key in seen:
                continue
            seen.add(key)
            out.append(ATSFingerprint(platform=platform, slug=slug, careers_url=careers_url))
    return out


def detect_ats_from_url(
    url: str,
    *,
    timeout: float = 15.0,
    max_html_bytes: int = 6_000_000,
    client: Optional[httpx.Client] = None,
) -> list[ATSFingerprint]:
    """Fetch ``url`` and return every ATS fingerprint found in the HTML.

    :param url: The careers page or company homepage to scrape. A bare
        domain like ``nvidia.com`` is accepted; ``https://`` is
        prepended if the scheme is missing.
    :param timeout: Per-request seconds. Careers pages can be slow
        (especially enterprise ones behind a CDN), so the default is
        generous. Callers running in a Celery task should keep this
        bounded to avoid hanging the worker.
    :param max_html_bytes: Hard cap on the HTML body we parse. Raised
        from 2 MB → 6 MB on 2026-04-17 after observing that Next.js /
        Gatsby SPAs inline multi-megabyte ``__NEXT_DATA__`` JSON
        payloads at the bottom of the HTML, and Ramp's careers page
        (~3.6 MB) has every Ashby URL past the 3.4 MB mark. 6 MB
        covers the p99 real-world careers page while still capping an
        attacker who points this at a pathological multi-hundred-MB
        resource. Callers running against untrusted domain lists
        should lower this.
    :param client: Optional preconfigured ``httpx.Client`` for test
        injection. The default opens a short-lived client per call.

    Returns an empty list on any fetch failure (HTTP 403/404/5xx,
    network error, non-HTML content type). Never raises — this is a
    best-effort enrichment tool, not a hard-dependency call.
    """
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        if client is None:
            with httpx.Client(
                timeout=timeout,
                follow_redirects=True,
                headers=_BROWSER_HEADERS,
            ) as c:
                resp = c.get(url)
        else:
            resp = client.get(url)
    except httpx.HTTPError as exc:
        logger.info("ATS fingerprint: fetch failed for %s: %s", url, exc)
        return []

    if resp.status_code >= 400:
        # 403 is the hot path for Cloudflare-protected sites like
        # wellfound.com; 404 for a wrong careers URL. Both are "no
        # fingerprint for this URL" — not an error we want to bubble.
        logger.info("ATS fingerprint: %s returned HTTP %d", url, resp.status_code)
        return []

    ct = resp.headers.get("content-type", "")
    if "html" not in ct.lower():
        # A careers page that returns JSON / plain text is either a
        # redirect to an API endpoint (rare) or a content-negotiated
        # response for our Accept header. Skip rather than try to
        # fingerprint JSON.
        logger.info("ATS fingerprint: %s non-HTML content-type %r", url, ct)
        return []

    # Cap the parsed body. `resp.text` decodes the full body into a
    # Python string; truncating the underlying bytes BEFORE decoding
    # avoids a very-large-body DoS path.
    html = resp.text
    if len(html) > max_html_bytes:
        html = html[:max_html_bytes]

    return _extract_fingerprints(html, url)


def detect_ats_for_domains(
    domains: Iterable[str],
    *,
    timeout: float = 15.0,
) -> dict[str, list[ATSFingerprint]]:
    """Batch variant: fingerprint a list of domains and return a dict.

    Sequential (not parallel) by design — we're polite to the target
    companies' infra, and running this against a thousand domains is a
    background Celery task, not a web request. If a caller genuinely
    needs parallelism, wrap this in ``ThreadPoolExecutor`` but use a
    small worker count (≤8) and the same ``httpx.Client`` shared
    across all workers so connection pooling kicks in.

    :returns: Dict keyed by the input domain, value is the list of
        fingerprints found (possibly empty). Every input appears in
        the result even on failure — callers can distinguish "not
        detected" from "not attempted" by presence in the dict.
    """
    out: dict[str, list[ATSFingerprint]] = {}
    # One client for the whole batch — connection pooling pays off
    # when several target domains resolve to the same CDN edge.
    with httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        headers=_BROWSER_HEADERS,
    ) as client:
        for domain in domains:
            # Try the canonical careers URL first, then fall back to
            # the domain root. This order matters — most companies
            # link to their ATS from `/careers` or `/jobs`, rarely
            # from the marketing homepage. Hitting `/careers` first
            # avoids wasted bandwidth parsing a 50KB marketing page.
            fps: list[ATSFingerprint] = []
            for suffix in ("/careers", "/jobs", ""):
                target = domain.rstrip("/") + suffix
                if not target.startswith(("http://", "https://")):
                    target = "https://" + target
                fps = detect_ats_from_url(target, timeout=timeout, client=client)
                if fps:
                    break
            out[domain] = fps
    return out
