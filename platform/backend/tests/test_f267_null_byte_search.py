"""F267 — null-byte sanitisation in escape_like.

Manual sweep finding: ``?search=test%00admin`` (URL-encoded null
byte) hits PostgreSQL's UTF-8 encoding rejection
(``asyncpg.exceptions.CharacterNotInRepertoireError: invalid byte
sequence for encoding "UTF8": 0x00``) and bubbles up as a 500. Real
DoS vector if hit at scale, plus log noise on every probe.

Fix: ``escape_like`` strips null + C0 control bytes (except tab/LF/CR)
BEFORE the LIKE-metachar escape pass. Every search endpoint that
routes through ``escape_like`` is now auto-protected — no per-
callsite change required.

These tests lock the invariant down. The fix lives in a hot path
shared by 7 endpoints; a regression that drops the strip would
silently re-open the DoS for every one of them.
"""
from __future__ import annotations

import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://placeholder:placeholder@localhost:5432/placeholder",
)
os.environ.setdefault(
    "DATABASE_URL_SYNC",
    "postgresql://placeholder:placeholder@localhost:5432/placeholder",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET", "pytest-f267")


def test_null_byte_is_stripped():
    """The exact failure mode reported in the manual sweep. A null
    byte in the search term must NOT survive escape_like — otherwise
    the asyncpg driver crashes on the LIKE pattern.
    """
    from app.utils.sql import escape_like

    out = escape_like("test\x00admin")
    assert "\x00" not in out, (
        f"F267 regression: null byte survived escape_like: {out!r}. "
        "PostgreSQL's UTF-8 encoding rejects 0x00; leaving it in the "
        "LIKE pattern crashes the request with a 500."
    )
    # The visible chars survive intact.
    assert out == "testadmin", (
        f"F267: expected null byte stripped to 'testadmin', got {out!r}"
    )


def test_other_control_chars_stripped():
    """C0 control range (0x00-0x1F) is mostly noise in search input.
    We drop everything except tab/LF/CR since those occasionally
    appear in pasted input. Bell (0x07), ESC (0x1B), DEL adjacent
    chars all go.
    """
    from app.utils.sql import escape_like

    raw = "abc\x01\x07\x1b\x1fxyz"
    out = escape_like(raw)
    assert out == "abcxyz", (
        f"F267 regression: control chars not stripped. Got {out!r}, "
        "expected 'abcxyz'."
    )


def test_tab_lf_cr_preserved():
    """Tab/LF/CR are kept because pasted input occasionally has them
    (e.g. multi-line copy from a job description). They're harmless
    in a LIKE pattern.
    """
    from app.utils.sql import escape_like

    out = escape_like("foo\tbar\nbaz\rqux")
    assert "\t" in out and "\n" in out and "\r" in out, (
        f"Whitespace control chars should be preserved. Got {out!r}"
    )


def test_existing_like_metachar_escape_still_works():
    """Regression guard — F267 must not break the original
    escape_like semantics. ``%`` and ``_`` must still be escaped
    with backslash, and the order ``\\`` first → ``%``/``_`` after
    must be preserved (otherwise our own backslash inserts get
    double-escaped).
    """
    from app.utils.sql import escape_like

    assert escape_like("100%") == "100\\%"
    assert escape_like("dev_ops") == "dev\\_ops"
    assert escape_like("a\\b") == "a\\\\b"
    # Combined — null + LIKE metachars in the same string.
    assert escape_like("a\x00b%c_d") == "ab\\%c\\_d"


def test_empty_string_no_op():
    """Edge case — empty input should pass through cleanly."""
    from app.utils.sql import escape_like

    assert escape_like("") == ""


def test_pure_null_string_becomes_empty():
    """Pure-null input becomes empty string. Callers that build
    ``f"%{escape_like(s)}%"`` then get ``"%%"`` which matches
    everything — that's slightly weird semantically, but the
    alternative (raising) is worse for caller ergonomics. The
    request reaching this function is malicious anyway; returning
    a no-op match is graceful degradation.
    """
    from app.utils.sql import escape_like

    assert escape_like("\x00\x00\x00") == ""
