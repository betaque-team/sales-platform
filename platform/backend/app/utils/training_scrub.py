"""PII scrub + user-id hashing for the training-data capture pipeline (F238).

Two responsibilities:

  1. ``scrub_pii(text)`` — replace emails, phones, URLs containing
     personal handles, and obvious-looking names in free-text inputs
     before they get persisted to ``training_examples.inputs``. The
     placeholder tokens (``[EMAIL]`` etc.) preserve the FACT that
     contact info was present (a model trained on resumes legitimately
     learns "resumes have email near the top") without exposing the
     value.

  2. ``hash_user_id(user_id)`` — SHA-256(JWT_SECRET + user_id) hex,
     truncated to 32 chars. Stable per-environment (so the same user
     gets the same hash across runs, enabling per-user train/eval
     splits) but irreversible without the secret. Production secret
     is the same `JWT_SECRET` env var the auth layer uses, which
     means a compromised secret would also compromise auth — but
     compromising the user_id_hash gives the attacker nothing that
     `auth.users` doesn't already give them, so re-using the secret
     here doesn't widen the blast radius.

The scrub is conservative — false positives ("[NAME] is the project
lead") are better than false negatives (a real email leaking into a
training set). If a downstream model needs more aggressive
de-identification (e.g. for HIPAA / GDPR Article 89), this is the
single chokepoint to tighten.
"""

from __future__ import annotations

import hashlib
import re
from uuid import UUID

from app.config import get_settings


# ── Email ────────────────────────────────────────────────────────────────────
# RFC 5322 simplified — covers the common shapes:
#   foo@bar.com
#   foo.bar+tag@sub.example.co.uk
#   foo_bar@example.io
# Doesn't try to handle quoted local-parts (rare in resumes) — false
# negatives there are acceptable; the scrub fires elsewhere too.
_EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
)

# ── Phone ────────────────────────────────────────────────────────────────────
# International + US formats. Loose because resumes use every variant:
#   +1 (555) 123-4567
#   555-123-4567
#   555.123.4567
#   +91 98765 43210
#   +44 20 7946 0958
# Anchored to require at least 7 digits total to avoid stripping
# "Reference 1234" or "Section 5.6.7" type sequences.
_PHONE_RE = re.compile(
    r"(?:(?<!\w)\+?\d{1,3}[\s.\-]?)?\(?\d{2,4}\)?[\s.\-]?\d{2,4}[\s.\-]?\d{3,4}(?:[\s.\-]?\d{1,4})?"
)

# ── URLs with personal handles ───────────────────────────────────────────────
# Strip LinkedIn / GitHub / Twitter-X / Telegram URLs that include a
# personal slug. We DON'T want to strip generic URLs (a job posting's
# "apply at https://example.com/jobs" is signal not PII) — only ones
# that point at a person.
_PERSONAL_URL_RE = re.compile(
    r"\bhttps?://(?:www\.)?(?:linkedin\.com/in|github\.com|twitter\.com|x\.com|t\.me)/[A-Za-z0-9_\-./]+",
    re.IGNORECASE,
)

# ── Phrases that look like name lines ────────────────────────────────────────
# Resumes typically open with the name on its own line: "Ayushi
# Shrotriya" / "AYUSHI SHROTRIYA". We're conservative here — only
# capture the FIRST line of the input that looks like a 2-4 word
# Title-Case sequence. False positives like "Senior Software Engineer"
# would also be redacted, but "[NAME]" still trains correctly because
# the model learns "the top of a resume is a name token". Tradeoff
# accepted.
_NAME_LINE_RE = re.compile(
    r"^\s*([A-Z][a-zA-Z'\-]+(?:\s+[A-Z][a-zA-Z'\-]+){1,3})\s*$",
    re.MULTILINE,
)


def scrub_pii(text: str | None) -> str:
    """Replace email / phone / personal URLs / opening name with tokens.

    Returns the scrubbed string. Empty / None input returns "".
    Idempotent — running on already-scrubbed text is a no-op (the
    placeholder tokens don't match any of the regexes).
    """
    if not text:
        return ""

    out = text

    # Phone first because emails and URLs would otherwise gobble the
    # leading + of an international number into other patterns.
    out = _PHONE_RE.sub("[PHONE]", out)
    out = _EMAIL_RE.sub("[EMAIL]", out)
    out = _PERSONAL_URL_RE.sub("[PERSONAL_URL]", out)

    # Only redact the FIRST name-shaped line (resume header). Doing it
    # globally would over-aggressively strip every Title-Case bullet.
    # `count=1` on re.sub keeps it conservative.
    out = _NAME_LINE_RE.sub("[NAME]", out, count=1)

    return out


def hash_user_id(user_id: UUID | str) -> str:
    """SHA-256(JWT_SECRET + user_id) hex, truncated to 32 chars.

    Stable per-environment. Two requests for the same user produce
    the same hash so per-user train/eval splits work. Two different
    environments with different JWT_SECRETs produce different hashes
    for the same user — desired, prevents cross-env data leakage.

    The 32-char truncation is collision-safe at the user-population
    sizes we care about (>10^19 hash space; collision probability at
    1M users is ~5e-26).
    """
    secret = get_settings().jwt_secret
    h = hashlib.sha256()
    h.update(secret.encode("utf-8"))
    h.update(b"\x00")  # delimiter so secret + uid != different secret + different uid
    h.update(str(user_id).encode("utf-8"))
    return h.hexdigest()[:32]
