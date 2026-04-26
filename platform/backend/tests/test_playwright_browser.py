"""Tests for ``app.services.playwright_browser``.

We do NOT spin up a real Chromium for these tests — the unit test
pass needs to stay fast (~1s per file) and CI shouldn't depend on
Chromium being launchable. Browser interactions are mocked at the
``async_playwright`` boundary so the test exercises:

  * pool lifecycle (lazy launch, single-instance, idempotent shutdown)
  * session ergonomics (context manager, fill/click/upload primitives)
  * graceful degradation when Playwright isn't installed

Live browser-driving coverage lives in script-mode tests
(``tests/test_api.py`` pattern) — added when concrete apply
workflows ship.
"""
from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

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
os.environ.setdefault("JWT_SECRET", "pytest-playwright")


@pytest.fixture(autouse=True)
def _reset_pool():
    """Drop singleton state before AND after every test so a mock
    leaking between tests can't poison a later one."""
    from app.services.playwright_browser import reset_pool_for_tests
    reset_pool_for_tests()
    yield
    reset_pool_for_tests()


def test_module_imports_without_playwright_installed(monkeypatch):
    """The service module must import even if Playwright isn't on the
    PYTHONPATH — the rest of the app shouldn't crash for environments
    that don't need browser automation. The actual Playwright import
    happens only inside ``_ensure_browser`` so import-time is clean.
    """
    # Import the module fresh — if anything tries Playwright at import
    # time, this fails with ImportError before reaching the assert.
    import importlib
    import app.services.playwright_browser as mod
    importlib.reload(mod)
    assert hasattr(mod, "BrowserSession")
    assert hasattr(mod, "shutdown_pool")
    assert hasattr(mod, "fetch_html")


def test_playwright_unavailable_raises_clear_error(monkeypatch):
    """When Playwright really isn't installed, ``_ensure_browser``
    must raise ``PlaywrightUnavailable`` with an actionable message —
    NOT bubble up the bare ``ImportError`` that confused the caller
    about which dep was missing.
    """
    from app.services.playwright_browser import (
        PlaywrightUnavailable,
        _ensure_browser,
    )

    # Force the inner ``from playwright.async_api import async_playwright``
    # to fail by stubbing ``builtins.__import__`` for that module name.
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __import__

    def fake_import(name, *args, **kwargs):
        if name == "playwright.async_api":
            raise ImportError("No module named 'playwright'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)

    async def go():
        with pytest.raises(PlaywrightUnavailable, match="not installed"):
            await _ensure_browser()

    asyncio.run(go())


def test_session_open_close_uses_pool_browser():
    """``BrowserSession`` should reuse the pool browser rather than
    launching a fresh one per session — that's the whole point of
    the pool. Each session DOES get its own context + page."""
    from app.services import playwright_browser as mod

    fake_browser = AsyncMock()
    fake_browser.is_connected = MagicMock(return_value=True)
    fake_context = AsyncMock()
    fake_page = AsyncMock()
    fake_browser.new_context.return_value = fake_context
    fake_context.new_page.return_value = fake_page

    async def fake_ensure():
        return fake_browser

    async def go():
        with patch.object(mod, "_ensure_browser", side_effect=fake_ensure):
            async with mod.BrowserSession() as s1:
                pass
            async with mod.BrowserSession() as s2:
                pass

        # Both sessions used the same pool browser …
        assert fake_browser.new_context.call_count == 2
        # … but each got its own context (cookie isolation).
        assert fake_context.close.call_count == 2

    asyncio.run(go())


def test_session_methods_proxy_to_underlying_page():
    """The convenience methods (``fill``, ``click``, ``upload``,
    ``wait_for_selector``) should each translate to a single call on
    the underlying Playwright Page — no extra round-trips, no silent
    drops, no kwargs swallowed.
    """
    from app.services import playwright_browser as mod

    fake_browser = AsyncMock()
    fake_browser.is_connected = MagicMock(return_value=True)
    fake_context = AsyncMock()
    fake_page = AsyncMock()
    fake_page.url = "https://example.com/done"
    fake_browser.new_context.return_value = fake_context
    fake_context.new_page.return_value = fake_page

    async def fake_ensure():
        return fake_browser

    async def go():
        with patch.object(mod, "_ensure_browser", side_effect=fake_ensure):
            async with mod.BrowserSession() as s:
                await s.navigate("https://x.com")
                await s.fill("#email", "user@example.com")
                await s.click("button[type=submit]")
                await s.upload("input[type=file]", "/tmp/resume.pdf")
                await s.wait_for_selector(".dashboard")
                got_url = await s.url()

        fake_page.goto.assert_called_once_with("https://x.com", wait_until="domcontentloaded")
        fake_page.fill.assert_called_once_with("#email", "user@example.com")
        fake_page.click.assert_called_once()
        fake_page.set_input_files.assert_called_once_with("input[type=file]", "/tmp/resume.pdf")
        fake_page.wait_for_selector.assert_called()
        assert got_url == "https://example.com/done"

    asyncio.run(go())


def test_browser_error_wraps_underlying_playwright_failure():
    """When the underlying page operation raises (anything: timeout,
    selector not found, browser crashed), the session method must
    re-raise as ``BrowserError`` so callers can catch ONE class.
    """
    from app.services import playwright_browser as mod

    fake_browser = AsyncMock()
    fake_browser.is_connected = MagicMock(return_value=True)
    fake_context = AsyncMock()
    fake_page = AsyncMock()
    fake_page.fill.side_effect = RuntimeError("element not found")
    fake_browser.new_context.return_value = fake_context
    fake_context.new_page.return_value = fake_page

    async def fake_ensure():
        return fake_browser

    async def go():
        with patch.object(mod, "_ensure_browser", side_effect=fake_ensure):
            async with mod.BrowserSession() as s:
                with pytest.raises(mod.BrowserError, match="fill"):
                    await s.fill("#nope", "x")

    asyncio.run(go())


def test_shutdown_pool_is_idempotent():
    """``shutdown_pool`` must be safe to call zero, one, or many times
    in any order — FastAPI lifespan can fire it on graceful shutdown
    AND a panic exit can also fire it. Idempotent + non-raising is
    the contract."""
    from app.services.playwright_browser import shutdown_pool

    async def go():
        # Never launched — should no-op.
        await shutdown_pool()
        # Twice in a row — still no-op.
        await shutdown_pool()
        await shutdown_pool()

    asyncio.run(go())


def test_wellfound_fetcher_returns_empty_on_browser_unavailable(monkeypatch):
    """``WellfoundFetcher.fetch`` must NEVER raise — every failure
    mode (no Playwright, browser launch failed, DataDome blocked,
    timeout) returns an empty list so the platform-scan pipeline
    survives a Wellfound outage. F254 contract."""
    import app.fetchers.wellfound as wf

    # Make the async path raise unconditionally — simulates the worst
    # case of Playwright completely broken.
    async def boom(self, slug):
        raise RuntimeError("browser launch unavailable")

    monkeypatch.setattr(wf.WellfoundFetcher, "_fetch_async", boom)

    f = wf.WellfoundFetcher()
    jobs = f.fetch("figma")
    assert jobs == [], (
        "WellfoundFetcher.fetch must always return [] on failure — "
        "raising would crash the per-platform scan loop."
    )


def test_wellfound_normalizes_graphql_response_with_field_caps():
    """The GraphQL → job-dict normalisation must apply the same
    field caps as F253 (HN fetcher) so an oversized title from a
    future GraphQL revision can't overflow ``Job.title_normalized
    String(500)`` and poison the upsert batch.
    """
    from app.fetchers.wellfound import WellfoundFetcher

    f = WellfoundFetcher()
    payload = {
        "data": {
            "startup": {
                "name": "Acme Corp",
                "jobListings": [
                    {
                        "id": 12345,
                        "title": "Senior Software Engineer " * 50,  # 1300+ chars
                        "slug": "senior-swe",
                        "remote": True,
                        "locationNames": ["Remote", "San Francisco"],
                        "compensation": "$150k-$200k",
                        "jobType": "full_time",
                    }
                ],
            }
        }
    }
    jobs = f._normalize_graphql(payload, slug="acme")
    assert len(jobs) == 1
    job = jobs[0]
    assert job["external_id"] == "wf-12345"
    assert job["platform"] == "wellfound"
    assert len(job["title"]) <= 200, (
        f"title is {len(job['title'])} chars; F253-class regression "
        "(must be ≤200 to fit String(500) with headroom)."
    )
    assert job["company_name"] == "Acme Corp"
    assert job["remote_scope"] == "remote"
    assert "wellfound.com/company/acme/jobs/12345" in job["url"]


def test_wellfound_detects_datadome_challenge_shell():
    """The ~2.5KB DataDome challenge HTML is consistently structured.
    The detector must recognise the shell and route the fetcher to
    return [] cleanly — not try to parse it as a real page (which
    would yield 0 jobs anyway but with confusing log noise).
    """
    from app.fetchers.wellfound import WellfoundFetcher

    challenge_html = (
        '<html lang="en"><head><title>wellfound.com</title>'
        '<style>#cmsg{animation: A 1.5s;}</style></head>'
        '<body style="margin:0"><p id="cmsg">Please enable JS '
        'and disable any ad blocker</p>'
        '<script data-cfasync="false">var dd={"rt":"c"...</script>'
        '</body></html>'
    )
    assert WellfoundFetcher._looks_like_datadome_challenge(challenge_html) is True

    # Real content should NOT trigger the detector.
    real_html = "<html><body>" + ("<a href='/company/acme/jobs/1'>Engineer</a>" * 50) + "</body></html>"
    assert WellfoundFetcher._looks_like_datadome_challenge(real_html) is False

    # Empty / very large HTML is also not the challenge.
    assert WellfoundFetcher._looks_like_datadome_challenge("") is False
    assert WellfoundFetcher._looks_like_datadome_challenge("a" * 100_000) is False
