"""Tests for ``classify_geography`` — F263 regression coverage.

Pre-fix, ``classify_geography`` had two collaborating defects that
combined to mis-classify region-restricted multi-country listings as
``global_remote``:

  (1) ``MULTI_COUNTRY_PATTERN`` (regex matching 3+ "remote" mentions)
      promoted any listing with that shape to global. So a job whose
      location was "France, Remote; Netherlands, Remote; Spain,
      Remote; UK, Remote" — clearly region-locked to those 4 EU
      countries — got the ``global_remote`` bucket.

  (2) The ``REGION_LOCKED_SIGNALS`` substring list had "remote france"
      and "france (remote)" but NOT "france, remote". So the
      Greenhouse-style comma-form (which is the dominant emit format
      we see in the wild) silently bypassed the region-locked guard.

User reported via feedback 3fc6b5c5: Dataiku 5973407004 / 5963977004
display "global remote" on the platform but the career page is
location-restricted.

Fix: defang ``MULTI_COUNTRY_PATTERN`` to a no-op regex + add a
``_REGION_LOCKED_COMMA_RE`` that catches "<country>, remote" /
"remote, <country>" forms across a known country list. This module
locks down both invariants so a careless regression on either one
fails CI rather than mis-tagging tens of thousands of jobs in prod.
"""
from __future__ import annotations

import os

# Minimum env so app.config imports cleanly (mirrors other test modules).
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://placeholder:placeholder@localhost:5432/placeholder",
)
os.environ.setdefault(
    "DATABASE_URL_SYNC",
    "postgresql://placeholder:placeholder@localhost:5432/placeholder",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET", "pytest-geo-classify")


# ── F263 — the Dataiku scenario that motivated this fix ───────────


def test_dataiku_multi_country_eu_listing_is_not_global_remote():
    """The exact failure mode reported in feedback 3fc6b5c5.

    ``classify_geography`` was returning ``"global_remote"`` for a
    Dataiku posting restricted to four EU countries. The user opened
    the career page and saw on-site/hybrid/region-restricted, not
    worldwide remote.

    Expected post-fix: ``""`` (unclassified) — the honest answer
    when the listing names specific countries that span only one
    region. We don't try to guess "EU only" because we don't have a
    bucket for it; ``""`` (renders as "unclassified" in the UI per
    F263) is correct.
    """
    from app.workers.tasks._role_matching import classify_geography

    location_raw = (
        "France, Remote; Netherlands, Remote; "
        "Spain, Remote; United Kingdom, Remote"
    )
    bucket = classify_geography(location_raw, "remote")
    assert bucket == "", (
        f"Got {bucket!r} — F263 regression. The Dataiku-style "
        "multi-country EU listing must NOT be classified as "
        "global_remote. The MULTI_COUNTRY_PATTERN heuristic that "
        "promoted any 3+-remote-mentions listing to global was the "
        "root cause. Restore F263's defang + comma-form guard."
    )


def test_country_comma_remote_form_is_region_locked():
    """The Greenhouse "<country>, remote" form is the most common
    emit shape we see and was the gap in the original substring list.
    Any country in the F263 ``_REGION_COUNTRIES`` tuple should fail
    this case if the regex regresses.
    """
    from app.workers.tasks._role_matching import classify_geography

    # Single-country comma form — should be region-locked, not global.
    for loc in [
        "France, Remote",
        "Germany, Remote",
        "United Kingdom, Remote",
        "Netherlands, Remote",
        "Spain, Remote",
        "Italy, Remote",
    ]:
        bucket = classify_geography(loc, "remote")
        assert bucket == "", (
            f"{loc!r} → {bucket!r}; expected '' (region-locked). "
            "The comma-form regex in classify_geography must catch "
            "'<country>, remote' for every country in _REGION_COUNTRIES."
        )


def test_remote_comma_country_form_is_region_locked():
    """The reversed form "Remote, <country>" — slightly less common
    but seen in the wild on Lever and BambooHR boards. Same regex
    handles it.
    """
    from app.workers.tasks._role_matching import classify_geography

    for loc in [
        "Remote, France",
        "Remote, Germany",
        "Remote, Singapore",
    ]:
        bucket = classify_geography(loc, "remote")
        assert bucket == "", (
            f"{loc!r} → {bucket!r}; expected '' (region-locked)."
        )


# ── Multi-country pattern defang — the OTHER half of the fix ──────


def test_multi_country_pattern_does_not_promote_to_global():
    """``MULTI_COUNTRY_PATTERN`` was the original heuristic that
    over-promoted any 3+-remote-mentions listing to global. Post-fix
    it's a no-op regex. If anyone replaces it with a heuristic again,
    the Dataiku case re-breaks — this test guards the constant
    directly so a future regression is caught without needing to
    reproduce the full Dataiku string.
    """
    from app.workers.tasks._role_matching import MULTI_COUNTRY_PATTERN

    # The defanged regex should NOT match anything containing "remote".
    samples = [
        "remote, us; remote, uk; remote, de",
        "Remote, France; Remote, Germany; Remote, Spain",
        "remote remote remote",
    ]
    for s in samples:
        assert MULTI_COUNTRY_PATTERN.search(s) is None, (
            f"MULTI_COUNTRY_PATTERN matched {s!r} — F263 regression. "
            "The pattern was defanged to a no-op regex; a real "
            "match here means someone restored the old over-eager "
            "heuristic. Use the explicit GLOBAL_REMOTE_SIGNALS list "
            "to pick up worldwide jobs instead."
        )


# ── Genuinely-global signals still classify correctly ─────────────


def test_worldwide_keyword_still_classifies_as_global():
    """Sanity check: the F263 fix narrowed our global-remote signal
    surface, but explicit worldwide framing should still work. If
    this test starts failing, the fix went too far and we'd be
    leaving real global jobs unclassified.
    """
    from app.workers.tasks._role_matching import classify_geography

    # Explicit global signals from GLOBAL_REMOTE_SIGNALS.
    for loc, scope in [
        ("Remote — Worldwide", "remote"),
        ("Anywhere in the world", "remote"),
        ("Work from anywhere", ""),
        ("100% Remote", "remote"),
    ]:
        bucket = classify_geography(loc, scope)
        assert bucket == "global_remote", (
            f"{loc!r}/{scope!r} → {bucket!r}; expected 'global_remote'. "
            "F263 fix must not have narrowed the global-signal surface "
            "so far that explicit 'worldwide' framing is missed."
        )


# ── USA + UAE buckets unchanged ────────────────────────────────────


def test_usa_only_classification_preserved():
    """The F263 fix only touched the global / region-locked path —
    USA classification should be unchanged. If this fails, the
    region-locked regex is over-matching and stealing US jobs.
    """
    from app.workers.tasks._role_matching import classify_geography

    for loc, scope in [
        ("United States (Remote)", "remote"),
        ("Remote, USA", "remote"),
        ("US Only", ""),
    ]:
        bucket = classify_geography(loc, scope)
        assert bucket == "usa_only", (
            f"{loc!r} → {bucket!r}; expected 'usa_only'."
        )


def test_unknown_location_still_returns_empty():
    """Unparseable location strings return empty bucket — same
    behaviour as before F263, no regressions expected here.
    """
    from app.workers.tasks._role_matching import classify_geography

    for loc in ["", "Office, Tokyo", "Some unknown place"]:
        bucket = classify_geography(loc, "")
        assert bucket == "", f"{loc!r} → {bucket!r}; expected ''."
