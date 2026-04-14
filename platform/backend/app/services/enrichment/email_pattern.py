"""Discover a person's email given their name and company domain.

Tries common email patterns ordered by industry frequency and verifies each via SMTP.

Pattern frequency (from industry analysis of ~10M professional emails):
  first.last  ~38%   john.doe@
  flast       ~26%   jdoe@
  first       ~12%   john@
  f.last      ~11%   j.doe@
  firstl      ~6%    johns@
  first_last  ~4%    john_doe@
  last.first  ~2%    doe.john@
  first-last  ~1%    john-doe@
  last        ~0.5%  doe@
"""

import logging
import re

from app.services.enrichment.email_verifier import verify_email_smtp

logger = logging.getLogger(__name__)

# Ordered by industry frequency (most common first)
_PATTERNS: list[tuple[str, callable]] = [
    ("first.last",  lambda f, l: f"{f}.{l}"),
    ("flast",       lambda f, l: f"{f[0]}{l}"),
    ("first",       lambda f, l: f),
    ("f.last",      lambda f, l: f"{f[0]}.{l}"),
    ("firstl",      lambda f, l: f"{f}{l[0]}"),
    ("first_last",  lambda f, l: f"{f}_{l}"),
    ("last.first",  lambda f, l: f"{l}.{f}"),
    ("first-last",  lambda f, l: f"{f}-{l}"),
    ("last",        lambda f, l: l),
    ("firstlast",   lambda f, l: f"{f}{l}"),
]


def _normalize_name(name: str) -> str:
    """Lowercase, strip whitespace, remove non-alpha characters."""
    name = name.strip().lower()
    name = re.sub(r"[^a-z]", "", name)
    return name


def detect_email_pattern(first_name: str, last_name: str, domain: str) -> dict:
    """Try common email patterns and verify via SMTP.

    Args:
        first_name: Person's first name.
        last_name: Person's last name.
        domain: Company domain (e.g., "canonical.com").

    Returns:
        {"email": str, "status": "valid"|"catch_all"|"not_found", "pattern": str}
    """
    first = _normalize_name(first_name)
    last = _normalize_name(last_name)

    if not first or not last or not domain:
        return {"email": "", "status": "not_found", "pattern": ""}

    # Skip single-char first or last (reduces false SMTP connections)
    if len(first) < 2 or len(last) < 2:
        return {"email": "", "status": "not_found", "pattern": ""}

    best_catch_all: dict | None = None

    for pattern_name, fmt_fn in _PATTERNS:
        try:
            local_part = fmt_fn(first, last)
        except (IndexError, TypeError):
            continue

        # Skip if local part is too short (likely noise)
        if len(local_part) < 3:
            continue

        email = f"{local_part}@{domain}"
        logger.debug("Trying email pattern %s: %s", pattern_name, email)

        try:
            result = verify_email_smtp(email)
        except Exception as exc:
            logger.debug("Verification error for %s: %s", email, exc)
            continue

        status = result.get("status", "unknown")

        if status == "valid":
            logger.info("Found valid email via pattern %s: %s", pattern_name, email)
            return {"email": email, "status": "valid", "pattern": pattern_name}

        if status == "catch_all" and best_catch_all is None:
            best_catch_all = {"email": email, "status": "catch_all", "pattern": pattern_name}

    if best_catch_all:
        logger.info("Domain is catch-all, returning first pattern: %s", best_catch_all["email"])
        return best_catch_all

    return {"email": "", "status": "not_found", "pattern": ""}
