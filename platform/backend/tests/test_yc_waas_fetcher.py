"""Tests for the YC Work at a Startup fetcher.

Three categories:

1. **Stage-1 company enumeration** — reading batch files, filtering
   by ``isHiring``, tolerating missing batches.

2. **Stage-2 jobs search + dedup** — keyword iteration with
   response merging; dedup by ``job.id``.

3. **Join + normalize** — the emitted job dict carries both the
   WaaS job fields and the richer ``yc_company_*`` metadata from
   the batch file.

Plus the usual registry / aggregator-set / PlatformFilter
guardrails that match the HN fetcher test pattern.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest


os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://placeholder:placeholder@localhost:5432/placeholder",
)
os.environ.setdefault(
    "DATABASE_URL_SYNC",
    "postgresql://placeholder:placeholder@localhost:5432/placeholder",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET", "pytest-yc-waas")


# Sample batch file row — mirrors the 29-field shape from
# yc-oss.github.io. Trimmed to what the fetcher actually reads.
_SAMPLE_BATCH_COMPANIES = [
    {
        "id": 1001,
        "name": "Ramp",
        "slug": "ramp",
        "batch": "W20",
        "status": "Active",
        "isHiring": True,
        "website": "https://ramp.com",
        "all_locations": "San Francisco, CA",
        "one_liner": "Corporate cards + spend management.",
        "industry": "Fintech",
        "team_size": 800,
        "tags": ["Fintech", "B2B"],
        "stage": "Growth",
    },
    {
        "id": 1002,
        "name": "Cal.com",
        "slug": "cal-com",
        "batch": "W22",
        "status": "Active",
        "isHiring": True,
        "website": "https://cal.com",
        "industry": "SaaS",
        "team_size": 40,
        "tags": ["Scheduling"],
        "stage": "Seed",
    },
    {
        "id": 1003,
        "name": "DefunctCo",
        "slug": "defunct",
        "batch": "S20",
        "status": "Inactive",
        "isHiring": False,   # Must be filtered out of the company map.
        "team_size": 0,
    },
]

# Sample WaaS /jobs/search response.
_SAMPLE_JOBS_ENGINEER = {
    "jobs": [
        {
            "id": 200001,
            "title": "Senior Platform Engineer",
            "jobType": "fulltime",
            "roleType": "REMOTE",
            "location": "Remote (US)",
            "salary": "$180K - $250K",
            "companyName": "Ramp",
            "companySlug": "ramp",
            "applyUrl": "/companies/ramp/jobs/200001",
        },
        {
            "id": 200002,
            "title": "Founding Engineer",
            "jobType": "fulltime",
            "roleType": "ONSITE",
            "location": "New York, NY",
            "salary": "$150K - $200K",
            "companyName": "Cal.com",
            "companySlug": "cal-com",
            "applyUrl": "https://cal.com/careers/founding-eng",
        },
    ]
}
_SAMPLE_JOBS_SECURITY = {
    "jobs": [
        # Duplicate of engineer keyword's 200001 — must be deduped.
        {
            "id": 200001,
            "title": "Senior Platform Engineer",
            "jobType": "fulltime",
            "roleType": "REMOTE",
            "location": "Remote (US)",
            "salary": "$180K - $250K",
            "companyName": "Ramp",
            "companySlug": "ramp",
            "applyUrl": "/companies/ramp/jobs/200001",
        },
        {
            "id": 200003,
            "title": "Security Engineer",
            "jobType": "fulltime",
            "location": "Remote",
            "companyName": "Orphan Startup",
            "companySlug": "orphan-startup",  # Not in any batch we fetched.
            "applyUrl": "/companies/orphan-startup/jobs/200003",
        },
    ]
}


def _make_client(batch_responses: dict, job_responses: dict) -> MagicMock:
    """Builds a MagicMock httpx.Client that returns:
      - batch_responses[url] for the batch JSON fetches
      - job_responses[keyword] for the /jobs/search fetches with q=keyword
    Any unregistered URL returns 404.
    """
    client = MagicMock()

    def _stub(url, params=None, headers=None, timeout=None):  # noqa: ARG001
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        if "yc-oss.github.io" in url:
            body = batch_responses.get(url)
            if body is None:
                resp.status_code = 404
                resp.raise_for_status.side_effect = Exception("404 not our fixture")
            else:
                resp.status_code = 200
                resp.json.return_value = body
        elif "workatastartup.com/jobs/search" in url:
            keyword = (params or {}).get("q", "")
            resp.status_code = 200
            resp.json.return_value = job_responses.get(keyword, {"jobs": []})
        else:
            resp.status_code = 404
            resp.raise_for_status.side_effect = Exception(f"unexpected URL {url}")
        return resp

    client.get.side_effect = _stub
    return client


# ── Stage 1: company enumeration ───────────────────────────────────


def test_fetch_companies_filters_on_is_hiring():
    """Companies with ``isHiring: false`` must not end up in the
    slug → record map. Otherwise the join at stage 2 would attribute
    richer metadata to cos that aren't actually open.
    """
    from app.fetchers.yc_waas import YCWaaSFetcher, _YC_BATCH_URL

    # Only one batch file has data; the rest 404. That's a realistic
    # scenario — yc-oss doesn't publish every season.
    url_w25 = _YC_BATCH_URL.format(season="winter", year=2025)
    client = _make_client(
        batch_responses={url_w25: _SAMPLE_BATCH_COMPANIES},
        job_responses={},
    )
    fetcher = YCWaaSFetcher(client=client)
    cos = fetcher._fetch_companies(client)

    assert "ramp" in cos
    assert "cal-com" in cos
    # DefunctCo had isHiring=False.
    assert "defunct" not in cos


def test_fetch_companies_tolerates_malformed_batch_file():
    """A batch file that returns a non-list body (e.g. an error object
    from a CDN hiccup) must not crash the whole run.
    """
    from app.fetchers.yc_waas import YCWaaSFetcher, _YC_BATCH_URL

    url_w25 = _YC_BATCH_URL.format(season="winter", year=2025)
    client = _make_client(
        batch_responses={url_w25: {"error": "something broke"}},  # not a list
        job_responses={},
    )
    fetcher = YCWaaSFetcher(client=client)
    cos = fetcher._fetch_companies(client)
    assert cos == {}


# ── Stage 2: jobs search + dedup ──────────────────────────────────


def test_fetch_jobs_deduplicates_by_id_across_keywords():
    """The keyword list is long and overlapping by design — most
    jobs surface for multiple terms. Dedup by ``job.id`` prevents
    the same posting landing 3× in a single run.
    """
    from app.fetchers.yc_waas import YCWaaSFetcher, _YC_BATCH_URL

    url_w25 = _YC_BATCH_URL.format(season="winter", year=2025)
    client = _make_client(
        batch_responses={url_w25: _SAMPLE_BATCH_COMPANIES},
        job_responses={
            "engineer": _SAMPLE_JOBS_ENGINEER,
            "security": _SAMPLE_JOBS_SECURITY,
        },
    )
    fetcher = YCWaaSFetcher(client=client)
    jobs = fetcher.fetch("__all__")

    ids = [j["external_id"] for j in jobs]
    assert "yc-200001" in ids
    assert "yc-200002" in ids
    assert "yc-200003" in ids
    # No duplicates despite 200001 appearing in both keyword responses.
    assert len(ids) == len(set(ids))


# ── Normalization: join + field mapping ────────────────────────────


def test_normalize_joins_company_metadata_from_batch():
    """When a job's ``companySlug`` matches a batch record, the
    emitted job carries the richer company fields (batch, industry,
    team size, one-liner, website, tags). This is the main payoff
    of the two-stage design — without it we'd have just 13 fields
    per job.
    """
    from app.fetchers.yc_waas import YCWaaSFetcher

    fetcher = YCWaaSFetcher(client=MagicMock())
    job = _SAMPLE_JOBS_ENGINEER["jobs"][0]     # id=200001, companySlug=ramp
    company = _SAMPLE_BATCH_COMPANIES[0]        # Ramp W20
    out = fetcher._normalize(job, company)

    assert out["external_id"] == "yc-200001"
    assert out["company_name"] == "Ramp"
    assert out["company_slug"] == "ramp"
    assert out["platform"] == "yc_waas"
    assert out["title"] == "Senior Platform Engineer"
    assert out["remote_scope"] == "remote"
    assert out["salary_range"] == "$180K - $250K"
    # Joined company fields should live in raw_json (not top-level).
    rj = out["raw_json"]
    assert rj["yc_company_batch"] == "W20"
    assert rj["yc_company_industry"] == "Fintech"
    assert rj["yc_company_team_size"] == 800
    assert rj["yc_company_website"] == "https://ramp.com"
    assert rj["yc_company_tags"] == ["Fintech", "B2B"]


def test_normalize_orphan_job_without_batch_metadata_still_emits():
    """A job whose ``companySlug`` doesn't match any batch file we
    crawled should still be emitted — we don't want to blackhole
    jobs from very-recent batches we haven't indexed yet (or from
    YC cos classified under a season name we didn't probe).

    The normalized dict falls back to WaaS-reported name/slug.
    """
    from app.fetchers.yc_waas import YCWaaSFetcher

    fetcher = YCWaaSFetcher(client=MagicMock())
    orphan = _SAMPLE_JOBS_SECURITY["jobs"][1]  # companySlug=orphan-startup, not in batch
    out = fetcher._normalize(orphan, {})

    assert out["company_name"] == "Orphan Startup"
    assert out["company_slug"] == "orphan-startup"
    # No joined metadata in raw_json.
    assert out["raw_json"]["yc_company_batch"] is None


def test_normalize_resolves_relative_apply_url_to_absolute():
    """WaaS reports either a full ``https://...`` URL or a relative
    ``/companies/…/jobs/…`` path. The base URL must be prepended in
    the second case so the stored Job.url is clickable from the UI.
    """
    from app.fetchers.yc_waas import YCWaaSFetcher

    fetcher = YCWaaSFetcher(client=MagicMock())
    out = fetcher._normalize(_SAMPLE_JOBS_ENGINEER["jobs"][0], _SAMPLE_BATCH_COMPANIES[0])
    assert out["url"].startswith("https://www.workatastartup.com/")
    assert "/companies/ramp/jobs/200001" in out["url"]

    # Fully-qualified URL passes through unchanged.
    out2 = fetcher._normalize(_SAMPLE_JOBS_ENGINEER["jobs"][1], _SAMPLE_BATCH_COMPANIES[1])
    assert out2["url"] == "https://cal.com/careers/founding-eng"


def test_normalize_drops_untitled_jobs():
    """A job with an empty title can't be surfaced in the UI — drop
    it rather than polluting the pool with "Job at Ramp" placeholder
    rows.
    """
    from app.fetchers.yc_waas import YCWaaSFetcher

    fetcher = YCWaaSFetcher(client=MagicMock())
    assert fetcher._normalize({"title": ""}, {}) == {}
    assert fetcher._normalize({"title": "   "}, {}) == {}
    assert fetcher._normalize({}, {}) == {}


def test_normalize_drops_jobs_with_no_company():
    """WaaS occasionally returns rows with a title but no company
    name/slug (probably an indexing race). Drop — we can't route
    outreach on it.
    """
    from app.fetchers.yc_waas import YCWaaSFetcher

    fetcher = YCWaaSFetcher(client=MagicMock())
    ghost = {"title": "Senior Eng", "companyName": "", "companySlug": ""}
    assert fetcher._normalize(ghost, {}) == {}


# ── Registry guardrails ────────────────────────────────────────────


def test_registered_in_fetcher_map():
    from app.fetchers import FETCHER_MAP, YCWaaSFetcher
    assert "yc_waas" in FETCHER_MAP
    assert FETCHER_MAP["yc_waas"] is YCWaaSFetcher


def test_registered_as_aggregator_in_scan_task():
    """Same reasoning as the HN equivalent: without `yc_waas` in
    the aggregator set, every YC job collapses to the single
    "YC Work at a Startup" meta-company — which breaks every
    per-company query (contacts, pipeline, relevance).
    """
    import inspect
    from app.workers.tasks import scan_task
    src = inspect.getsource(scan_task)
    assert '"yc_waas"' in src
    assert "_AGGREGATOR_PLATFORMS" in src


def test_platform_filter_accepts_yc_waas():
    from typing import get_args
    from app.schemas.job import PlatformFilter
    assert "yc_waas" in get_args(PlatformFilter)
