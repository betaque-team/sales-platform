"""Tests for the HackerNews ``Who is hiring?`` fetcher.

Two categories:

1. **Parser tests** — the real complexity. HN comments are free-form
   HTML in a convention that's ~60% regular. We exercise the parser
   against representative real-world shapes (copied verbatim from
   actual HN threads, with URLs lightly anonymised) so regressions
   on format changes are caught without a live network call.

2. **Rate-limit guard tests** — verify the descendants-count cache
   short-circuits repeat fetches. Uses an in-memory fake Redis so
   the test exercises the code path without a running broker.

Network tests are intentionally absent — the parser + cache tests
together cover every branch that isn't a thin HTTP wrapper.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest


# Minimum env so app.config imports cleanly when the fetcher module
# pulls in the base class.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://placeholder:placeholder@localhost:5432/placeholder",
)
os.environ.setdefault(
    "DATABASE_URL_SYNC",
    "postgresql://placeholder:placeholder@localhost:5432/placeholder",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET", "pytest-hn-fetcher")


# ── Parser — real-world comment shapes ──────────────────────────────


@pytest.fixture
def parser():
    from app.fetchers.hackernews import HackerNewsFetcher
    return HackerNewsFetcher._parse_header


def test_parser_pipe_separated_happy_path(parser):
    """The canonical shape: ``Company | Role | Location | REMOTE | url``.
    Accounts for ~50% of real postings in a typical thread.
    """
    text = (
        "Acme Corp | Senior Infrastructure Engineer | Austin, TX | REMOTE | "
        "FULL-TIME | $180-250k\n"
        "We're building cloud-native systems…\n"
        "Apply: https://acme.example.com/careers/infra"
    )
    out = parser(text)
    assert out["company"] == "Acme Corp"
    assert "Infrastructure Engineer" in out["title"]
    assert out["url"] == "https://acme.example.com/careers/infra"
    assert out["remote_scope"] == "remote"
    assert "Austin" in out["location"]


def test_parser_strips_yc_batch_suffix(parser):
    """``(YC Wxx)`` / ``(YC S21)`` polluted Company rows for months
    before this regex went in. The batch identifier is interesting
    metadata but doesn't belong in Company.name — keep the clean
    name for deduping against Greenhouse/Lever slugs.
    """
    text = "Anthropic (YC S21) | Software Engineer | SF | ONSITE | https://anthropic.com/careers"
    out = parser(text)
    assert out["company"] == "Anthropic"
    assert "Engineer" in out["title"]


def test_parser_em_dash_fallback(parser):
    """Some posters use em-dashes instead of pipes."""
    text = "Example Labs — Senior DevOps — Remote (US) — https://example.co/jobs"
    out = parser(text)
    assert out["company"] == "Example Labs"
    assert "DevOps" in out["title"]
    assert out["remote_scope"] == "remote"
    assert out["url"] == "https://example.co/jobs"


def test_parser_plain_hyphen_fallback(parser):
    """No pipe, no em-dash — plain ``Company - Role - Location - url``."""
    text = "Widget.io - Staff Security Engineer - Remote US - https://widget.io/careers"
    out = parser(text)
    assert out["company"] == "Widget.io"
    assert "Security" in out["title"]
    assert out["url"] == "https://widget.io/careers"


def test_parser_location_not_misread_as_title(parser):
    """Regression: the 2nd segment was briefly getting picked up as
    title even when it was obviously a city. The role-keyword scan
    walks all segments before falling back to position-2.
    """
    text = (
        "ExampleCo | San Francisco, CA | Senior Platform Engineer | ONSITE | "
        "https://example.com/jobs"
    )
    out = parser(text)
    assert out["company"] == "ExampleCo"
    assert "Platform Engineer" in out["title"]
    assert "San Francisco" in out["location"]


def test_parser_detects_worldwide_remote(parser):
    """``work from anywhere`` / ``worldwide`` → remote_scope=worldwide
    (more specific than plain ``remote``). Checked via the base
    class's _detect_remote_scope on the full body.
    """
    text = (
        "Globo | Frontend Engineer | Work from anywhere in the world | "
        "https://globo.example/apply"
    )
    out = parser(text)
    assert out["remote_scope"] == "worldwide"


def test_parser_returns_url_from_body_if_missing_from_header(parser):
    """Postings often write ``Apply: url`` on line 2 or 3 instead of
    the header line. The URL regex runs against the full body.
    """
    text = (
        "Cohort Labs | Site Reliability Engineer | Remote US | FULL-TIME\n"
        "We build observability tooling.\n"
        "Apply: https://cohort.example.com/careers/sre"
    )
    out = parser(text)
    assert out["url"] == "https://cohort.example.com/careers/sre"


def test_parser_drops_noise_to_punctuation(parser):
    """URL regex trails on ``.,;)`` — tests the strip."""
    text = "Acme | Engineer | https://acme.example/apply."
    out = parser(text)
    assert out["url"] == "https://acme.example/apply"


def test_parser_no_delimiter_no_url_returns_company_only(parser):
    """Free-form comment without any recognisable structure. We
    still return what we can — the fetcher caller drops it because
    it needs at least a URL to be useful.
    """
    text = "Hey HN, we're hiring. DM me if interested!"
    out = parser(text)
    # Should have company but no url → caller rejects.
    assert out.get("company")
    assert "url" not in out


def test_parser_handles_multiple_roles_placeholder_title():
    """When a comment says ``Multiple roles`` / ``Various roles``
    the parser keeps that as the title so the scan still creates a
    Job row (with a sensible title for the UI).
    """
    from app.fetchers.hackernews import HackerNewsFetcher
    text = "BigCo | Multiple roles | SF, NYC, Remote | https://bigco.example/jobs"
    out = HackerNewsFetcher._parse_header(text)
    assert out["title"] == "Multiple roles"


# ── HTML → text ─────────────────────────────────────────────────────


def test_strip_html_preserves_urls_and_breaks():
    """HN comment bodies are minimal HTML: ``<p>`` paragraphs + ``<a>``
    links. We keep the link URL so the URL regex can find it.
    """
    from app.fetchers.hackernews import HackerNewsFetcher
    body = (
        "Vercel | Infrastructure Engineer | Remote US<p>"
        'We build the fastest platform.<p>'
        'Apply: <a href="https://vercel.example/jobs" rel="nofollow">'
        "https://vercel.example/jobs</a>"
    )
    plain = HackerNewsFetcher._strip_html(body)
    assert "Vercel" in plain
    # Paragraph → newline.
    assert "\n" in plain
    # URL made it through the <a> unwrap.
    assert "https://vercel.example/jobs" in plain


def test_strip_html_unescapes_entities():
    """HN double-encodes: ``&amp;amp;`` → ``&amp;`` → ``&``."""
    from app.fetchers.hackernews import HackerNewsFetcher
    body = "Acme &amp; Co | Senior Engineer | NY"
    plain = HackerNewsFetcher._strip_html(body)
    assert plain == "Acme & Co | Senior Engineer | NY"


# ── Descendants-cache skip path ─────────────────────────────────────


class _FakeRedis:
    """Minimal Redis stand-in — `.get` / `.set` with TTL ignored.
    Used to exercise the cache-hit branch without a live broker.
    """
    def __init__(self, initial: dict | None = None):
        self._store: dict = dict(initial or {})

    def get(self, key):
        v = self._store.get(key)
        return None if v is None else str(v).encode()

    def set(self, key, value, ex=None):  # noqa: ARG002 — TTL ignored
        self._store[key] = value


def test_fetch_short_circuits_when_descendants_unchanged():
    """Cache-hit path: if the thread's `descendants` count matches
    what we stored on the previous SUCCESSFUL run, `fetch` returns []
    without fetching any comments. Protects HN Firebase from 500
    unnecessary HTTPS calls every 30 min during the quiet weeks of
    the month.

    F251 cache schema: value is a JSON dict ``{descendants, ok}``.
    Only ``ok=true`` runs are trusted for short-circuit.
    """
    import json
    from app.fetchers.hackernews import HackerNewsFetcher

    fake_redis = _FakeRedis({
        "hn:whoishiring:40000000:descendants": json.dumps(
            {"descendants": 523, "ok": True}
        ),
    })

    client = MagicMock()
    # Algolia search returns one story.
    algolia_resp = MagicMock(status_code=200)
    algolia_resp.json.return_value = {
        "hits": [
            {
                "objectID": "40000000",
                "title": "Ask HN: Who is hiring? (April 2026)",
                "_tags": ["story", "author_whoishiring"],
                "created_at": "2026-04-01T00:00:00Z",
                "created_at_i": 1743465600,
            }
        ]
    }
    # Firebase thread head returns descendants=523 — same as cache.
    head_resp = MagicMock(status_code=200)
    head_resp.json.return_value = {
        "id": 40000000,
        "title": "Ask HN: Who is hiring? (April 2026)",
        "descendants": 523,
        "kids": [40000001, 40000002, 40000003],  # Should NEVER be fetched.
        "time": 1743465600,
    }
    algolia_resp.raise_for_status = MagicMock()
    head_resp.raise_for_status = MagicMock()
    client.get.side_effect = [algolia_resp, head_resp]

    fetcher = HackerNewsFetcher(client=client, redis_client=fake_redis)
    jobs = fetcher.fetch("__all__")

    assert jobs == []
    # Exactly 2 HTTP calls — Algolia + thread head. No comment fetches.
    assert client.get.call_count == 2


def test_fetch_proceeds_when_descendants_changed():
    """Cache-miss path: descendants count has changed since last run,
    so we go ahead and fetch comments. Verifies the comment-fetch
    loop runs and the cache gets updated to the new count.
    """
    from app.fetchers.hackernews import HackerNewsFetcher

    import json
    fake_redis = _FakeRedis({
        "hn:whoishiring:40000000:descendants": json.dumps(
            {"descendants": 10, "ok": True}  # stale count, prior run was successful
        ),
    })

    client = MagicMock()

    def _stub(url, params=None, timeout=None):  # noqa: ARG001
        resp = MagicMock(status_code=200)
        resp.raise_for_status = MagicMock()
        if "algolia" in url:
            resp.json.return_value = {
                "hits": [
                    {
                        "objectID": "40000000",
                        "title": "Ask HN: Who is hiring? (April 2026)",
                        "_tags": ["story", "author_whoishiring"],
                        "created_at": "2026-04-01T00:00:00Z",
                        "created_at_i": 1743465600,
                    }
                ]
            }
        elif url.endswith("/40000000.json"):
            resp.json.return_value = {
                "id": 40000000,
                "title": "Ask HN: Who is hiring? (April 2026)",
                "descendants": 42,  # bigger than cache → proceed
                "kids": [40000001, 40000002],
                "time": 1743465600,
            }
        elif url.endswith("/40000001.json"):
            # Well-formed parseable comment.
            resp.json.return_value = {
                "id": 40000001,
                "by": "some_user",
                "time": 1743466000,
                "text": (
                    "Acme Corp | Senior Infra Engineer | Remote US | "
                    "<a href=\"https://acme.example.com/careers\">apply</a>"
                ),
            }
        elif url.endswith("/40000002.json"):
            # Deleted comment — should be silently skipped.
            resp.json.return_value = {
                "id": 40000002,
                "deleted": True,
            }
        else:
            resp.json.return_value = {}
        return resp

    client.get.side_effect = _stub

    fetcher = HackerNewsFetcher(client=client, redis_client=fake_redis)
    jobs = fetcher.fetch("__all__")

    # One parseable comment, one deleted → exactly 1 job.
    assert len(jobs) == 1
    job = jobs[0]
    assert job["platform"] == "hackernews"
    assert job["external_id"] == "hn-40000001"
    assert job["company_name"] == "Acme Corp"
    assert "Infra Engineer" in job["title"]
    assert job["url"] == "https://acme.example.com/careers"
    assert job["remote_scope"] == "remote"
    # Cache was updated to the new JSON-dict schema with the new
    # descendants count and ok=True (run produced 1 job).
    cached = fake_redis._store["hn:whoishiring:40000000:descendants"]
    payload = json.loads(cached)
    assert payload["descendants"] == 42
    assert payload["ok"] is True
    # HN comment id propagated into raw_json.
    assert job["raw_json"]["hn_comment_id"] == "40000001"
    assert job["raw_json"]["hn_thread_id"] == "40000000"


def test_fetch_does_not_cache_descendants_when_zero_jobs_emitted():
    """F249 regression — a 0-job result must NOT update the cache.

    Pre-fix the cache was set unconditionally after the parse loop, so
    a single empty run (parser regression, transient upstream hiccup,
    every comment deleted/dead, etc.) silently locked the fetcher into
    a "nothing new" short-circuit until the thread's descendants count
    changed upstream — which on multi-week-old threads can be hours
    or days. Live-observed on 2026-04-26: HN had been registered for
    hours, scans returned ``jobs_found=0`` repeatedly, prod
    ``hackernews`` platform had zero rows in ``Job``.

    Refusing to cache empty results means the next scheduled tick
    re-attempts the full fetch, so a transient zero is self-healing.
    The happy-path (jobs > 0) still updates the cache so the
    rate-limit benefit is preserved during steady state.
    """
    from app.fetchers.hackernews import HackerNewsFetcher

    fake_redis = _FakeRedis()  # empty cache → don't short-circuit

    client = MagicMock()

    def _stub(url, params=None, timeout=None):  # noqa: ARG001
        resp = MagicMock(status_code=200)
        resp.raise_for_status = MagicMock()
        if "algolia" in url:
            resp.json.return_value = {
                "hits": [
                    {
                        "objectID": "40000000",
                        "title": "Ask HN: Who is hiring? (April 2026)",
                        "_tags": ["story", "author_whoishiring"],
                        "created_at": "2026-04-01T00:00:00Z",
                        "created_at_i": 1743465600,
                    }
                ]
            }
        elif url.endswith("/40000000.json"):
            resp.json.return_value = {
                "id": 40000000,
                "title": "Ask HN: Who is hiring? (April 2026)",
                "descendants": 99,
                # Two kids — one deleted, one with no parseable header.
                # Neither produces a job.
                "kids": [40000001, 40000002],
                "time": 1743465600,
            }
        elif url.endswith("/40000001.json"):
            # Deleted — fetcher skips.
            resp.json.return_value = {"id": 40000001, "deleted": True}
        elif url.endswith("/40000002.json"):
            # No company / no URL — parser returns nothing usable, skipped.
            resp.json.return_value = {
                "id": 40000002,
                "by": "some_user",
                "time": 1743466000,
                "text": "Just some unrelated commentary, no job here.",
            }
        else:
            resp.json.return_value = {}
        return resp

    client.get.side_effect = _stub

    fetcher = HackerNewsFetcher(client=client, redis_client=fake_redis)
    jobs = fetcher.fetch("__all__")

    # 0 jobs emitted. Under F251 we DO write the cache, but with
    # ``ok=False`` — the next ``_should_skip`` will refuse to short-
    # circuit on that flag. The cache key existing isn't enough to
    # cause the regression; what matters is whether ``ok`` is True.
    import json
    assert jobs == []
    cache_key = "hn:whoishiring:40000000:descendants"
    cached = fake_redis._store.get(cache_key)
    assert cached is not None, (
        "Expected the cache to record the run with ok=False so the "
        "tick cadence stays observable in Redis. Got missing key."
    )
    payload = json.loads(cached)
    assert payload.get("ok") is False, (
        f"F251: 0-job run must cache ok=False so next tick refetches. "
        f"Got payload={payload!r}"
    )


def test_legacy_int_cache_value_triggers_refetch_and_schema_upgrade():
    """F251 auto-heal — pre-F251 prod runs wrote the descendants count
    as a raw int. Those rows can outlive the deploy that introduced
    the JSON-dict schema. The new ``_should_skip`` must:

      1. Recognise the legacy int form.
      2. NOT short-circuit on it (untrusted).
      3. Force a full fetch.
      4. Overwrite the cache with the new JSON-dict schema after the
         fetch completes, so subsequent ticks use the modern path.

    This is the path that unsticks prod hackernews from a cache
    poisoned by a pre-F249 0-job run, without needing manual Redis
    intervention.
    """
    import json
    from app.fetchers.hackernews import HackerNewsFetcher

    # Legacy int form, descendants count matches upstream — pre-F251
    # this would have been a hit-and-skip.
    fake_redis = _FakeRedis({
        "hn:whoishiring:40000000:descendants": "474",
    })

    client = MagicMock()

    def _stub(url, params=None, timeout=None):  # noqa: ARG001
        resp = MagicMock(status_code=200)
        resp.raise_for_status = MagicMock()
        if "algolia" in url:
            resp.json.return_value = {
                "hits": [
                    {
                        "objectID": "40000000",
                        "title": "Ask HN: Who is hiring? (April 2026)",
                        "_tags": ["story", "author_whoishiring"],
                        "created_at": "2026-04-01T00:00:00Z",
                        "created_at_i": 1743465600,
                    }
                ]
            }
        elif url.endswith("/40000000.json"):
            resp.json.return_value = {
                "id": 40000000,
                "title": "Ask HN: Who is hiring? (April 2026)",
                "descendants": 474,  # SAME as legacy cache
                "kids": [40000001],
                "time": 1743465600,
            }
        elif url.endswith("/40000001.json"):
            resp.json.return_value = {
                "id": 40000001,
                "by": "u",
                "time": 1743466000,
                "text": (
                    "Acme | Senior Infra Engineer | Remote | "
                    "<a href=\"https://acme.example.com/careers\">apply</a>"
                ),
            }
        else:
            resp.json.return_value = {}
        return resp

    client.get.side_effect = _stub

    fetcher = HackerNewsFetcher(client=client, redis_client=fake_redis)
    jobs = fetcher.fetch("__all__")

    # Despite the legacy int matching upstream descendants, the fetcher
    # treats it as untrusted and DID fetch the comment.
    assert len(jobs) == 1, (
        "F251 regression: legacy int cache form short-circuited the "
        "fetch, so prod stays stuck in the poisoned-cache state."
    )
    # And the cache has been upgraded to the new JSON-dict schema with
    # ok=True (run produced 1 job).
    cached_after = fake_redis._store["hn:whoishiring:40000000:descendants"]
    payload = json.loads(cached_after)
    assert payload == {"descendants": 474, "ok": True}, (
        f"Expected schema upgrade on cache write; got {payload!r}"
    )


def test_fetch_gracefully_handles_no_thread_found():
    """Algolia returns no whoishiring stories (outage / off-month).
    Must not crash; returns [].
    """
    from app.fetchers.hackernews import HackerNewsFetcher

    client = MagicMock()
    algolia_resp = MagicMock(status_code=200)
    algolia_resp.raise_for_status = MagicMock()
    algolia_resp.json.return_value = {"hits": []}
    client.get.return_value = algolia_resp

    fetcher = HackerNewsFetcher(client=client, redis_client=_FakeRedis())
    assert fetcher.fetch("__all__") == []


def test_fetch_rejects_non_whoishiring_story():
    """Algolia surfaces ``whoishiring`` stories — but the user also
    posts "Ask HN: Who wants to be hired?" and "Ask HN: Freelancer?".
    The title regex rejects those so we don't ingest the wrong thread.
    """
    from app.fetchers.hackernews import HackerNewsFetcher

    client = MagicMock()
    algolia_resp = MagicMock(status_code=200)
    algolia_resp.raise_for_status = MagicMock()
    algolia_resp.json.return_value = {
        "hits": [
            {
                "objectID": "40000000",
                "title": "Ask HN: Freelancer? Seeking freelancer? (April 2026)",
                "_tags": ["story", "author_whoishiring"],
                "created_at": "2026-04-01T00:00:00Z",
                "created_at_i": 1743465600,
            }
        ]
    }
    client.get.return_value = algolia_resp

    fetcher = HackerNewsFetcher(client=client, redis_client=_FakeRedis())
    assert fetcher.fetch("__all__") == []
    # Only 1 HTTP call — we bail before fetching the thread head.
    assert client.get.call_count == 1


# ── Integration with the fetcher registry ──────────────────────────


def test_registered_in_fetcher_map():
    """Guardrail against wiring regressions: if someone removes the
    HN entry from ``FETCHER_MAP`` the scan task would silently
    degrade to "platform hackernews has no fetcher — skip board".
    """
    from app.fetchers import FETCHER_MAP, HackerNewsFetcher
    assert "hackernews" in FETCHER_MAP
    assert FETCHER_MAP["hackernews"] is HackerNewsFetcher


def test_registered_as_aggregator_in_scan_task():
    """The scan task's aggregator branch resolves per-job company
    names from the fetcher output. Without `hackernews` in that set,
    every HN job would collapse into the single "HN Who's Hiring"
    Company — unusable for sales.
    """
    import inspect
    from app.workers.tasks import scan_task
    src = inspect.getsource(scan_task)
    # Same assertion style as other aggregator regressions in this
    # repo — grep the source for the literal so a rename of the set
    # also breaks this test (which is the intent).
    assert '"hackernews"' in src
    assert "_AGGREGATOR_PLATFORMS" in src


def test_doctype_platform_filter_accepts_hackernews():
    """The Literal in schemas/job.py gates the `?platform=` query
    param on /api/v1/jobs. A missing entry means admins can't filter
    'show only HN jobs' from the UI even though the rows exist.
    """
    from typing import get_args
    from app.schemas.job import PlatformFilter
    assert "hackernews" in get_args(PlatformFilter)
