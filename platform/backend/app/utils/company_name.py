"""Heuristics for rejecting junk Company rows at ingest time.

Finding 37 surfaced dozens of junk rows on `/companies` that came from
scraper-side artifacts — LinkedIn search-hashtag harvesting (`#WalkAway
Campaign`, `#twiceasnice Recruiting`), retail call-center brands, staffing
agencies, and names that are just digits. They all made it into `Company`
because nothing upstream checked whether the extracted name looked like
a legitimate employer.

`looks_like_junk_company_name(name)` centralizes the check so every code
path that creates a `Company` row can skip the obvious junk consistently
(instead of each ingest task reinventing its own filter).

Finding 39 (and the still-open Finding 10) also surfaced `name` and
`1name` as literal strings stored as company names — clear scratch/test
data. A tight length+alphabet check catches both without false-flagging
anything realistic.
"""

from __future__ import annotations

import re

# Matches generic staffing / recruiting / consulting shell names. Not
# comprehensive — intentionally conservative to avoid false positives on
# real companies whose names happen to contain these words.
_STAFFING_RE = re.compile(
    r"""(?:
        \brecruiting\b
      | \bstaffing\b
      | \bsolutions\s+llc\b
      | \bconsulting\s+co(?:\.|\b)
      | \bconsultancy\s+co(?:\.|\b)
      | \btalent\s+partners\b
      | \btalent\s+solutions\b
    )""",
    re.IGNORECASE | re.VERBOSE,
)

# Short all-lowercase-alphabetic-only strings (e.g. "name", "abc", "foo")
# are almost certainly scratch data — the regex is deliberately narrow
# to avoid false-flagging real short brand names that happen to be
# lowercase + contain digits: `0x` (crypto protocol), `100ms` (video SDK),
# `37signals` (publisher), etc. Real acronyms like `IBM` / `HP` / `3M` are
# uppercase so they don't hit this rule either.
_SCRATCH_NAME_RE = re.compile(r"^[a-z]{1,4}$")

# A small explicit list of known-scratch strings that don't fit the regex
# above but have been observed on prod (see Findings 10 and 39). Grows
# over time as more typo / test-harness names surface.
_KNOWN_SCRATCH_NAMES = frozenset({"1name"})

# Purely numeric names (e.g. "123", "1800") are never real companies on
# their own — legitimate cases like "7-Eleven" or "1-800 Flowers"
# have a hyphen and additional words that keep them out of this class.
_PURELY_NUMERIC_RE = re.compile(r"^[\d\s]+$")


def looks_like_junk_company_name(name: str | None) -> bool:
    """Return True if `name` should be rejected as a Company row.

    Called from ingest paths before Company creation and from the
    cleanup script `app/cleanup_junk_companies.py` for retroactive
    deletion. Keep the rules in one place so "added on ingest" and
    "cleaned up after the fact" stay in lockstep.
    """
    if not name:
        return True
    stripped = name.strip()
    if not stripped:
        return True

    # (a) LinkedIn hashtag harvest: names that begin with `#` are
    # search-result hashtags, not companies.
    if stripped.startswith("#"):
        return True

    # (b) Purely numeric — never a real employer on its own.
    if _PURELY_NUMERIC_RE.match(stripped):
        return True

    # (c) Staffing-agency / recruiter shell names. Conservative regex;
    # grows over time as more patterns surface.
    if _STAFFING_RE.search(stripped):
        return True

    # (d) Scratch/test names — two narrow rules, both conservative enough
    # that real short brand names (`0x`, `100ms`, `37signals`, `IBM`, `3M`)
    # pass. See _SCRATCH_NAME_RE and _KNOWN_SCRATCH_NAMES for the exact
    # shape.
    if _SCRATCH_NAME_RE.match(stripped):
        return True
    if stripped.lower() in _KNOWN_SCRATCH_NAMES:
        return True

    return False
