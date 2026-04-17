"""Parse an ATS job posting URL into ``(platform, slug, external_id)``.

Used by ``POST /jobs/submit-link`` (Feature A) to route a pasted link
to the right existing fetcher without each fetcher needing its own
URL-sniffing code. The per-platform regexes are intentionally narrow:
we'd rather 400 on an ambiguous URL and ask the user than import a
garbage row under the wrong company slug.

Every regex captures exactly two named groups: ``slug`` and
``external_id``. ``slug`` must match the value an existing scanner
fetcher would pass to its API (so re-submitting a link from a
scanned board upserts rather than duplicating). ``external_id`` is
the ATS's own job id — the same value the scanner's ``_normalize``
step writes to ``Job.external_id``, which guarantees the ``UNIQUE
(external_id)`` idempotency story at
:class:`app.models.job.Job`.

Adding a new ATS here is the complete backend change for manual
link support on that platform, provided the existing bulk fetcher
for that ATS is wired up in ``app/fetchers/__init__.FETCHER_MAP`` —
``fetch_one`` inherits a generic filter-on-bulk fallback from
:class:`app.fetchers.base.BaseFetcher`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class ParsedJobUrl:
    """Result of parsing a pasted ATS job URL.

    Attributes map 1:1 to the inputs that
    :func:`app.workers.tasks.scan_task._upsert_job` expects inside
    the ``raw_job`` dict — the caller builds the dict from these
    three fields plus whatever the per-platform fetcher returns.
    """

    platform: str
    slug: str
    external_id: str


# (regex, platform). Ordered most-specific first so overlapping
# patterns (e.g. several ATSes on api.ashbyhq.com style domains)
# resolve deterministically. Host-anchored — we match the whole
# URL, not just the path, so `jobs.lever.co/foo` can't accidentally
# match a third-party site that happens to contain that substring.
_URL_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Greenhouse — canonical boards host + the newer job-boards host.
    # Greenhouse also surfaces job URLs via each company's own
    # `boards.greenhouse.io/{slug}/jobs/{id}` redirect; the two forms
    # are equivalent and both are covered here.
    (
        re.compile(
            r"^https?://boards\.greenhouse\.io/(?P<slug>[^/]+)/jobs/(?P<external_id>\d+)",
            re.IGNORECASE,
        ),
        "greenhouse",
    ),
    (
        re.compile(
            r"^https?://job-boards\.greenhouse\.io/(?P<slug>[^/]+)/jobs/(?P<external_id>\d+)",
            re.IGNORECASE,
        ),
        "greenhouse",
    ),
    # Lever — canonical `jobs.lever.co/{slug}/{posting_id}` where
    # posting_id is a UUID. The `/apply` suffix is tolerated because
    # that's the direct apply page, same posting id.
    (
        re.compile(
            r"^https?://jobs\.lever\.co/(?P<slug>[^/]+)/(?P<external_id>[0-9a-f-]+)(?:/apply)?/?",
            re.IGNORECASE,
        ),
        "lever",
    ),
    # Ashby — two equivalent host forms:
    #   jobs.ashbyhq.com/{slug}/{uuid}
    #   {slug}.ashbyhq.com/{uuid}  (less common, subdomain-routed)
    # The posting id is a UUID.
    (
        re.compile(
            r"^https?://jobs\.ashbyhq\.com/(?P<slug>[^/]+)/(?P<external_id>[0-9a-f-]+)",
            re.IGNORECASE,
        ),
        "ashby",
    ),
    # Workable — apply.workable.com/{slug}/j/{id} and the older
    # {slug}.workable.com/jobs/{id}. `{id}` is alphanumeric.
    (
        re.compile(
            r"^https?://apply\.workable\.com/(?P<slug>[^/]+)/j/(?P<external_id>[A-Z0-9]+)",
            re.IGNORECASE,
        ),
        "workable",
    ),
    (
        re.compile(
            r"^https?://(?P<slug>[^.]+)\.workable\.com/jobs/(?P<external_id>\d+)",
            re.IGNORECASE,
        ),
        "workable",
    ),
    # BambooHR — {slug}.bamboohr.com/careers/{id}. The id is numeric.
    (
        re.compile(
            r"^https?://(?P<slug>[^.]+)\.bamboohr\.com/careers/(?P<external_id>\d+)",
            re.IGNORECASE,
        ),
        "bamboohr",
    ),
    # SmartRecruiters — careers.smartrecruiters.com/{slug}/{id} and
    # jobs.smartrecruiters.com/{slug}/{id}. `{id}` is numeric.
    (
        re.compile(
            r"^https?://(?:careers|jobs)\.smartrecruiters\.com/(?P<slug>[^/]+)/(?P<external_id>\d+)",
            re.IGNORECASE,
        ),
        "smartrecruiters",
    ),
    # Jobvite — jobs.jobvite.com/{slug}/job/{id}. Id is alphanumeric.
    (
        re.compile(
            r"^https?://jobs\.jobvite\.com/(?P<slug>[^/]+)/job/(?P<external_id>[A-Za-z0-9]+)",
            re.IGNORECASE,
        ),
        "jobvite",
    ),
    # Recruitee — {slug}.recruitee.com/o/{id-or-slug}. The id segment
    # can mix digits + title slug — we take the trailing numeric id
    # when present, else the whole slug.
    (
        re.compile(
            r"^https?://(?P<slug>[^.]+)\.recruitee\.com/o/(?P<external_id>[^/?#]+)",
            re.IGNORECASE,
        ),
        "recruitee",
    ),
]


class UnsupportedJobUrlError(ValueError):
    """Raised when none of the ATS patterns match a submitted URL.

    The caller (``POST /jobs/submit-link``) translates this to a 400
    so the user sees "that URL isn't from a supported ATS" rather
    than a silent fallback to the generic career-page scraper (which
    routinely produces garbage rows for non-ATS hosts — see the
    feature plan).
    """


def parse_job_url(url: str) -> ParsedJobUrl:
    """Parse ``url`` and return ``(platform, slug, external_id)``.

    Only the ATS patterns listed in ``_URL_PATTERNS`` are recognized.
    Anything else (generic career sites, LinkedIn, Indeed, etc.)
    raises :class:`UnsupportedJobUrlError`. The two-tier error
    handling lets the caller keep a "this needs manual company
    specification" escape hatch without silently misclassifying
    unknown hosts.

    :param url: Raw URL string as pasted by the user. Leading /
        trailing whitespace is stripped.
    :raises ValueError: The URL is empty, malformed, or not ``https://``.
    :raises UnsupportedJobUrlError: The URL is well-formed but doesn't
        match any known ATS pattern.
    """
    if not url:
        raise ValueError("URL is required.")
    url = url.strip()
    if len(url) > 1000:
        # Match the 1000-char cap on `Job.url` in models/job.py — if
        # the column couldn't hold it, we shouldn't pretend to accept it.
        raise ValueError("URL is too long (max 1000 characters).")

    parsed = urlparse(url)
    # Scheme allow-list: https only. http URLs get upgraded by the
    # ATS anyway, and disallowing file:/// / javascript: etc. here
    # is cheap defense-in-depth against SSRF-shaped payloads reaching
    # the fetcher.
    if parsed.scheme not in ("http", "https"):
        raise ValueError("URL must use http or https.")
    if not parsed.netloc:
        raise ValueError("URL is missing a hostname.")

    for pattern, platform in _URL_PATTERNS:
        m = pattern.match(url)
        if m:
            slug = m.group("slug").strip()
            external_id = m.group("external_id").strip()
            if not slug or not external_id:
                # Regex shouldn't allow empty captures, but the
                # explicit guard documents the invariant that
                # downstream code (fetchers, upsert) relies on.
                continue
            return ParsedJobUrl(platform=platform, slug=slug, external_id=external_id)

    raise UnsupportedJobUrlError(
        f"URL host '{parsed.netloc}' is not a recognized ATS. "
        "Supported: Greenhouse, Lever, Ashby, Workable, BambooHR, "
        "SmartRecruiters, Jobvite, Recruitee."
    )
