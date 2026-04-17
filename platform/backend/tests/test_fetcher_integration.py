"""Integration tests that hit live ATS APIs to prove the fetchers work.

These are **opt-in**, marked ``@pytest.mark.integration``. They're
skipped by default in CI (``pytest tests/``) because hitting real
upstreams is flaky (rate limits, transient 5xx, network) and we don't
want infra wobble to block deploys. Run explicitly with:

    python -m pytest tests/test_fetcher_integration.py -v -m integration

When to run:
    * After any edit to a fetcher's ``fetch()`` / ``_normalize()``.
    * Whenever the tester or operator reports "platform X has zero jobs".
    * Quarterly as a sanity pass — ATS APIs silently drift.

The tests are **self-documenting as a survey** of which platforms are
healthy vs platform-dead. A green run means every ATS we still scan
returns non-empty for its seed slug; a fail here is either the probe
slug leaving the platform (refresh the slug list) or the upstream API
changing shape (fetcher code update).

Jobvite and Wellfound are covered by a ``xfail_platform_broken`` case
that asserts they gracefully return ``[]`` rather than crash — that's
the contract those fetchers promise while their upstreams are broken
(Jobvite: public API retired, Wellfound: Cloudflare block). A future
"they're fixed" run should flip those to a positive assertion — see
the comments on each file.
"""
from __future__ import annotations

import os

import pytest


pytestmark = [pytest.mark.integration]


# Keep the minimum set small. Each tuple is `(fetcher_class_path, slug,
# min_expected_jobs)`. One per platform is enough — the goal is "did
# anything come back" not "exhaustive coverage of upstream".
#
# Keep in sync with ``discovery_task.RECRUITEE_PROBE_SLUGS`` etc. Pick
# slugs that have consistently produced jobs on the last several checks
# (not bleeding-edge startups that might close their board next week).
HEALTHY_FETCHERS = [
    # (dotted-path to fetcher class, slug, minimum expected count).
    # Every entry here was live-verified against the real upstream
    # on 2026-04-17. A flake here usually means the slug has retired
    # from the platform, not a fetcher bug.
    ("app.fetchers.greenhouse.GreenhouseFetcher",           "stripe",   5),
    # Lever: `palantir` (235 jobs @ 2026-04-17) is stable and
    # high-volume. The old `zapier` seed went 404 — that slug is
    # dead on Lever now. Avoid small startups as seeds — they close
    # their Lever board during quiet hiring periods and flake the test.
    ("app.fetchers.lever.LeverFetcher",                     "palantir", 5),
    ("app.fetchers.ashby.AshbyFetcher",                     "ramp",     3),
    # BambooHR: `rei` was the only known-live tenant with >0 jobs at
    # the 2026-04-17 survey (the rest — toggl / aha / zapier / linear
    # / asana / dashlane / bluecore / algolia — are live tenants with
    # zero current openings). If this flakes, widen to those.
    ("app.fetchers.bamboohr.BambooHRFetcher",               "rei",      1),
    # Recruitee: `bunq` returned 42 jobs at the 2026-04-17 survey.
    # Stable, high-volume Recruitee customer.
    ("app.fetchers.recruitee.RecruiteeFetcher",             "bunq",     5),
    # SmartRecruiters: CASE-SENSITIVE slug. The old `bosch` seed 404'd;
    # `BoschGroup` returned 4385 jobs and `Visa` returned 832 at the
    # survey. Keeping `Visa` as the seed — stable, huge, well-known.
    ("app.fetchers.smartrecruiters.SmartRecruitersFetcher", "Visa",     5),
]

BROKEN_FETCHERS = [
    # (dotted-path, slug, reason) — assert the fetcher returns [] rather
    # than raising. When/if the upstream is fixed, move the entry into
    # HEALTHY_FETCHERS above and delete from here. The probe list in
    # ``discovery_task.py`` should mirror this status — platforms here
    # should have an empty probe list so discovery doesn't waste cycles.
    (
        "app.fetchers.jobvite.JobviteFetcher",
        "unity",
        "Jobvite public API retired 2026-04 — every slug 302s to invalid=1",
    ),
    (
        "app.fetchers.wellfound.WellfoundFetcher",
        "superside",
        "Wellfound GraphQL behind Cloudflare Bot Management — 403s httpx",
    ),
    (
        "app.fetchers.himalayas.HimalayasFetcher",
        "gitlab",
        "Himalayas /jobs/api 403s httpx as of 2026-04-17 — endpoint protected",
    ),
    (
        "app.fetchers.workable.WorkableFetcher",
        "workable",
        (
            "Workable widget API (apply.workable.com/api/v1/widget/accounts) "
            "404s every customer slug we've tried as of 2026-04-17. The "
            "fetcher code is fine (older workable rows in prod were ingested "
            "successfully before the API change); the upstream stopped "
            "serving the public endpoint. Needs follow-up via Workable's "
            "official partner documentation."
        ),
    ),
]


def _import_fetcher(dotted_path: str):
    """Import a fetcher class from a dotted path at call time.

    Lazy so that a missing optional module (or a broken fetcher import)
    fails only the tests that touch it, not collection of the whole
    file.
    """
    module_path, cls_name = dotted_path.rsplit(".", 1)
    mod = __import__(module_path, fromlist=[cls_name])
    return getattr(mod, cls_name)


@pytest.fixture(autouse=True)
def _stub_env_for_fetcher_imports(monkeypatch):
    """Fetchers don't touch the DB but importing ``app.fetchers.*``
    can pull in ``app.config`` which requires a DATABASE_URL. Stub the
    minimum so test collection doesn't explode outside a real Docker
    environment.
    """
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://placeholder:placeholder@localhost:5432/placeholder")
    monkeypatch.setenv("DATABASE_URL_SYNC", "postgresql://placeholder:placeholder@localhost:5432/placeholder")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("JWT_SECRET", "fetcher-integration-test")


@pytest.mark.parametrize(
    "dotted_path,slug,min_expected",
    HEALTHY_FETCHERS,
    ids=[h[0].rsplit(".", 1)[-1] for h in HEALTHY_FETCHERS],
)
def test_healthy_fetcher_returns_nonempty(dotted_path, slug, min_expected):
    """Each fetcher hits its upstream and returns >= min_expected jobs.

    Hard assertion on count rather than "truthy" because a fetcher that
    returns [] on a bug and [] on "no jobs today" are indistinguishable
    to the caller. Setting a minimum makes the test fail loudly when
    either the slug goes cold (update the list) or the fetcher starts
    silently dropping jobs (real bug).
    """
    FetcherClass = _import_fetcher(dotted_path)
    with FetcherClass() as fetcher:
        jobs = fetcher.fetch(slug)
    assert isinstance(jobs, list), (
        f"{dotted_path}.fetch({slug!r}) must return a list, got {type(jobs).__name__}"
    )
    assert len(jobs) >= min_expected, (
        f"{dotted_path}.fetch({slug!r}) returned {len(jobs)} jobs; "
        f"expected >= {min_expected}. Either {slug!r} left the platform "
        f"(update HEALTHY_FETCHERS) or the fetcher silently dropped jobs."
    )
    # Every job must carry the identity fields the scan pipeline reads
    # downstream. A fetcher that returns dicts missing `external_id`
    # crashes `_upsert_job` at runtime — catch that here.
    for job in jobs[:3]:
        assert isinstance(job, dict), f"{dotted_path} returned non-dict job: {job!r}"
        assert job.get("external_id"), f"{dotted_path} job missing external_id: {job!r}"
        assert job.get("title"), f"{dotted_path} job missing title: {job!r}"
        assert job.get("platform"), f"{dotted_path} job missing platform: {job!r}"


@pytest.mark.parametrize(
    "dotted_path,slug,reason",
    BROKEN_FETCHERS,
    ids=[b[0].rsplit(".", 1)[-1] for b in BROKEN_FETCHERS],
)
def test_broken_fetcher_returns_empty_gracefully(dotted_path, slug, reason):
    """Fetchers whose upstream is currently broken must still return ``[]``
    cleanly — no raises, no None, no crashes in the scan loop.

    ``reason`` is purely documentation; it lands in the test ID so
    ``pytest -v`` prints why each fetcher is on the broken list.
    """
    FetcherClass = _import_fetcher(dotted_path)
    with FetcherClass() as fetcher:
        jobs = fetcher.fetch(slug)
    assert jobs == [], (
        f"{dotted_path}.fetch({slug!r}) was expected to return [] "
        f"(known broken: {reason}) but returned {len(jobs)} items — "
        f"the upstream may have recovered. Move this case to "
        f"HEALTHY_FETCHERS and assert a real count."
    )
