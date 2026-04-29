"""Remote-scope vocabulary — the canonical source of truth.

The team kept tripping over the legacy ``geography_bucket`` enum
(``global_remote`` / ``usa_only`` / ``uae_only`` / ``""``). This module
is the single place that defines:

  * the new vocabulary,
  * the labels the UI renders,
  * the legacy → new translation table used by the classifier and
    backfill migration,
  * the helper that converts a (scope, countries) pair back to the
    legacy bucket string for the shadow-write side of the cutover.

═══ DEFINITIONS ═══════════════════════════════════════════════════════

The axis is **where the candidate is allowed to work from**. The
company's headquarters location is irrelevant — a US-based company
that hires candidates anywhere is ``worldwide``, even if all the
employees happen to sit in San Francisco.

  * ``worldwide``           — the company hires remote candidates from
                              anywhere. No country gate. (A US company
                              hiring from India + Brazil + Germany
                              lands here.)
  * ``country_restricted``  — remote, but only candidates physically
                              located in one of the listed countries
                              may apply. ``remote_policy_countries`` carries
                              the ISO-3166 alpha-2 codes (e.g.
                              ``["US"]`` for the legacy "USA Only"
                              meaning).
  * ``region_restricted``   — remote, but only within a region too
                              broad to enumerate by country (EU,
                              MENA, APAC). The job description names
                              the region; we don't enumerate.
  * ``hybrid``              — mix of office + remote. The office
                              location lives in ``location_text``.
  * ``onsite``              — full office presence required. No
                              remote work.
  * ``unknown``             — classifier hasn't decided yet OR the
                              listing's wording is genuinely
                              ambiguous. NOT a fallback for "we know
                              but we don't have a bucket" — that's
                              ``region_restricted`` or ``onsite``.

═══ MIGRATION NOTE ═══════════════════════════════════════════════════

For one release after d0e1f2g3h4i5 ships, the legacy
``geography_bucket`` column is kept and shadow-written via
``legacy_bucket_for(scope, countries)``. Out-of-tree analytics queries
keep working. A follow-up migration drops the column once consumers
are updated.
"""

from __future__ import annotations

from typing import Iterable, Literal


# ── Scope enum ────────────────────────────────────────────────────

RemotePolicy = Literal[
    "worldwide",
    "country_restricted",
    "region_restricted",
    "hybrid",
    "onsite",
    "unknown",
]

ALL_POLICIES: tuple[RemotePolicy, ...] = (
    "worldwide",
    "country_restricted",
    "region_restricted",
    "hybrid",
    "onsite",
    "unknown",
)


# ── UI labels (canonical — frontend imports the same strings) ─────

POLICY_LABELS: dict[str, str] = {
    "worldwide": "Worldwide remote",
    "country_restricted": "Country-restricted remote",
    "region_restricted": "Region-restricted remote",
    "hybrid": "Hybrid",
    "onsite": "On-site",
    "unknown": "Needs classification",
}

POLICY_SHORT_LABELS: dict[str, str] = {
    "worldwide": "Worldwide",
    "country_restricted": "Country-only",
    "region_restricted": "Region-only",
    "hybrid": "Hybrid",
    "onsite": "On-site",
    "unknown": "Unknown",
}


# ── Legacy ↔ new translation tables ───────────────────────────────

# Legacy ``geography_bucket`` value → new ``remote_policy``. Used by
# the migration backfill and by any read-side fallback that still
# encounters a row with no ``remote_policy`` populated.
LEGACY_TO_POLICY: dict[str, RemotePolicy] = {
    "global_remote": "worldwide",
    "usa_only": "country_restricted",
    "uae_only": "country_restricted",
    "": "unknown",
}

# Legacy bucket → which countries the new ``remote_policy_countries`` list
# should carry. Empty for buckets that don't imply a specific country.
LEGACY_TO_COUNTRIES: dict[str, list[str]] = {
    "global_remote": [],
    "usa_only": ["US"],
    "uae_only": ["AE"],
    "": [],
}


def legacy_bucket_for(
    scope: str | None, countries: Iterable[str] | None
) -> str:
    """Compute the legacy ``geography_bucket`` for shadow-writing.

    Used in the classifier + scan task during the one-release
    transition window so the legacy column stays in sync with the
    new (scope, countries) pair. Reverse-direction translation —
    chooses the closest legacy bucket and falls back to "" when
    there's no good match.

    Rules (matches the migration's CASE expression in reverse):

      * ``worldwide`` → ``global_remote``
      * ``country_restricted`` + ``["US"]`` → ``usa_only``
      * ``country_restricted`` + ``["AE"]`` → ``uae_only``
      * ``country_restricted`` + anything else (including multi-
        country) → ``""`` (legacy schema can't represent it)
      * everything else (region_restricted / hybrid / onsite /
        unknown) → ``""``
    """
    if scope == "worldwide":
        return "global_remote"
    if scope == "country_restricted":
        codes = list(countries or [])
        if codes == ["US"]:
            return "usa_only"
        if codes == ["AE"]:
            return "uae_only"
    return ""


def normalise_country(code: str) -> str:
    """Coerce a country code to canonical ISO-3166 alpha-2 upper-case.

    Accepts case-insensitive input but rejects anything that isn't
    exactly two letters — keeps the JSONB list well-shaped for the
    GIN containment query.
    """
    s = code.strip().upper()
    if len(s) != 2 or not s.isalpha():
        raise ValueError(f"Country code must be ISO-3166 alpha-2; got {code!r}")
    return s


def normalise_countries(codes: Iterable[str]) -> list[str]:
    """De-dup, sort, and validate a list of country codes.

    Sorting keeps the JSONB literal stable across writes — important
    for the GIN index hit rate and for cache invalidation pivoting
    on the column value.
    """
    seen: set[str] = set()
    for c in codes:
        seen.add(normalise_country(c))
    return sorted(seen)
