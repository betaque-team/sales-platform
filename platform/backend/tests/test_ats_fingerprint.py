"""Tests for :mod:`app.services.ats_fingerprint`.

Two kinds of test here:

1. **Unit tests** (default pytest run): HTML-fixture parsing — verify
   the regex patterns correctly extract ``(platform, slug)`` pairs from
   synthetic HTML without hitting the network. Fast + stable.
2. **Integration tests** (``-m integration`` only): hit one real
   company careers page per platform and assert we find a fingerprint.
   These are the "does this still work in the real world" checks —
   skipped by default in CI because upstream outages would flake
   otherwise.

When a detection breaks in practice, replicate the failure as a fixture
in HTML_FIXTURES below rather than loosening the regex blindly — the
test then documents WHY the regex needs adjusting.
"""
from __future__ import annotations

import pytest

from app.services.ats_fingerprint import (
    ATSFingerprint,
    _extract_fingerprints,
    detect_ats_from_url,
)


# ── Fixtures (synthetic HTML snippets, stable) ──────────────────────────

HTML_FIXTURES: dict[str, tuple[str, list[ATSFingerprint]]] = {
    # (name → (html body, expected fingerprints))
    "workday_canonical": (
        # AT&T-shape: multiple workday sites on one page
        '<a href="https://att.wd1.myworkdayjobs.com/en-US/ATTGeneral">Careers</a>'
        '<a href="https://att.wd1.myworkdayjobs.com/en-US/ATTcollege">College</a>',
        [
            ATSFingerprint(
                platform="workday",
                slug="att/wd1/ATTGeneral",
                careers_url="https://att.wd1.myworkdayjobs.com/en-US/ATTGeneral",
            ),
            ATSFingerprint(
                platform="workday",
                slug="att/wd1/ATTcollege",
                careers_url="https://att.wd1.myworkdayjobs.com/en-US/ATTcollege",
            ),
        ],
    ),
    "greenhouse_boards": (
        '<iframe src="https://boards.greenhouse.io/stripe"></iframe>',
        [
            ATSFingerprint(
                platform="greenhouse",
                slug="stripe",
                careers_url="https://boards.greenhouse.io/stripe",
            ),
        ],
    ),
    "lever_plus_ashby_one_page": (
        # Company with BOTH Lever + Ashby embeds (rare but real — e.g.
        # engineering on Lever, marketing on Ashby, during migration)
        '<a href="https://jobs.lever.co/examplecorp">Eng</a>'
        '<a href="https://jobs.ashbyhq.com/examplecorp">Sales</a>',
        [
            ATSFingerprint(
                platform="lever",
                slug="examplecorp",
                careers_url="https://jobs.lever.co/examplecorp",
            ),
            ATSFingerprint(
                platform="ashby",
                slug="examplecorp",
                careers_url="https://jobs.ashbyhq.com/examplecorp",
            ),
        ],
    ),
    "duplicate_references_deduped": (
        # Same slug appearing twice (inline link + footer link) must
        # yield ONE fingerprint. Guards against the scanner getting
        # two DiscoveredCompany rows for the same board.
        '<a href="https://boards.greenhouse.io/stripe">Jobs</a>'
        '<footer><a href="https://boards.greenhouse.io/stripe/jobs/123">Apply</a></footer>',
        [
            ATSFingerprint(
                platform="greenhouse",
                slug="stripe",
                careers_url="https://boards.greenhouse.io/stripe",
            ),
        ],
    ),
    "no_ats_detected": (
        '<html><body><h1>Come work with us</h1>'
        '<a href="mailto:jobs@example.com">Email us</a></body></html>',
        [],
    ),
    "workday_old_pattern_no_locale": (
        # Some older Workday sites don't prefix with /en-US/
        '<a href="https://jpmc.wd5.myworkdayjobs.com/jpmc">Careers</a>',
        [
            ATSFingerprint(
                platform="workday",
                slug="jpmc/wd5/jpmc",
                careers_url="https://jpmc.wd5.myworkdayjobs.com/en-US/jpmc",
            ),
        ],
    ),
}


@pytest.mark.parametrize(
    "name,html_and_expected",
    list(HTML_FIXTURES.items()),
    ids=list(HTML_FIXTURES.keys()),
)
def test_extract_fingerprints_parses_html(name, html_and_expected):
    """Regex-level unit tests — fixed HTML in, expected fingerprints out.

    Runs in the default pytest pass (no marker). If one of these fails,
    either a regex changed or a new input shape needs a new fixture —
    DON'T just fix the test, understand the regression first.
    """
    html, expected = html_and_expected
    got = _extract_fingerprints(html, source_url="https://fixture.example.com")
    assert got == expected, (
        f"fixture {name!r}: expected {expected}, got {got}"
    )


# ── Integration tests (live upstream, opt-in) ──────────────────────────


@pytest.mark.integration
def test_detect_ats_from_real_careers_page():
    """Live test: AT&T's careers page embeds 3+ Workday URLs.

    Chosen because it's an enterprise page that's been stable for
    years and has multiple Workday sites — exercises both the "did we
    fetch HTML successfully" path AND the dedup-by-(platform,slug)
    path at once.

    Flakes here mean either (a) AT&T changed their careers page host,
    (b) Cloudflare escalated its block on our IP, (c) the fingerprint
    regex broke. Swap to a different enterprise page before loosening
    the assertion.
    """
    fps = detect_ats_from_url("https://careers.att.jobs/")
    # At least ONE workday fingerprint must be found. Specific sites
    # AT&T has on Workday change periodically (ATTGeneral / Cricket /
    # ATTcollege etc.), so assert the platform not the exact slug.
    workday_fps = [f for f in fps if f.platform == "workday"]
    assert workday_fps, (
        f"Expected ≥1 Workday fingerprint on careers.att.jobs/, got {fps}"
    )
    # Every Workday fp must have a well-formed composite slug.
    for fp in workday_fps:
        parts = fp.slug.split("/")
        assert len(parts) == 3, (
            f"Workday slug must be 'tenant/cluster/site', got {fp.slug!r}"
        )
        assert parts[1].startswith("wd"), (
            f"Workday cluster must start with 'wd', got {parts[1]!r}"
        )


@pytest.mark.integration
def test_detect_ats_gracefully_returns_empty_on_404():
    """Unreachable URL → empty list, no raise.

    A fetch failure must never bubble as an exception — callers run
    this in batch against hundreds of domains and expect it to return
    per-domain results. Using a TEST-NET IP (RFC 5737) so we don't
    DNS-hammer a real domain.
    """
    fps = detect_ats_from_url("https://203.0.113.1/careers")
    assert fps == []
