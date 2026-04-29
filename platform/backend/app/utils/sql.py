"""SQL-helper utilities shared by the FastAPI routers (Finding 84).

Before this module existed, seven endpoints (`jobs`, `companies`,
`applications`, `resume`, `feedback`) all built ILIKE patterns with
Python f-strings like `f"%{search}%"`. PostgreSQL ILIKE treats `%` as
"zero or more chars" and `_` as "exactly one char", so user-legal
characters in search terms (e.g., `"100%"`, `"dev_ops"`,
`"DynamoDB_table"`) were silently reinterpreted as wildcards and
returned garbage matches.

Parameterisation stayed intact — no SQL injection was ever possible —
but search correctness was broken for any term containing `%`, `_`,
or a literal backslash.

`escape_like` prefixes every LIKE metacharacter with `\\` so it's
matched literally, and every call site pairs it with
`.ilike(pattern, escape="\\")` (SQLAlchemy passes `ESCAPE '\'` through
to the DB).
"""

from __future__ import annotations


# F267 — characters PostgreSQL UTF-8 refuses or that are pointless in
# a search term. Null byte (0x00) crashes the asyncpg driver with
# ``CharacterNotInRepertoireError: invalid byte sequence for encoding
# "UTF8": 0x00`` — bubbles up as a 500. Other C0 control chars are
# accepted by Postgres but never legitimate user input; stripping them
# keeps LIKE patterns clean and makes the helper a single-source-of-
# truth for "search input sanitisation". Tab (0x09), LF (0x0A), CR
# (0x0D) stay since they occasionally appear in pasted input.
_CONTROL_CHARS_TO_DROP = {
    i: None for i in range(0x20) if i not in (0x09, 0x0A, 0x0D)
}


def escape_like(value: str) -> str:
    """Escape LIKE/ILIKE metacharacters so `value` is matched literally.

    Must be paired with `.ilike(pattern, escape="\\\\")` at the call
    site — the `ESCAPE '\\'` clause tells PostgreSQL that a literal
    backslash is the escape char. Without the `escape=` kwarg the
    backslashes stay inert and the `%`/`_` still act as wildcards.

    Order matters: escape `\\` first so we don't double-escape the
    backslashes we insert for `%` and `_`.

    F267 — null + control chars are dropped BEFORE the LIKE escape
    pass. The asyncpg driver crashes the request with
    ``CharacterNotInRepertoireError`` on a single null byte
    (PostgreSQL's UTF-8 encoding rejects 0x00). Pre-fix,
    ``?search=test%00admin`` returned a 500 (DoS vector if hit at
    scale, plus log noise on every curious probe). Now the helper
    strips them transparently — every callsite that already routes
    through ``escape_like`` is auto-protected; no per-callsite
    change required.

    Example:
        user types "100%" →
        escape_like("100%") == "100\\%" →
        f"%{escape_like('100%')}%" == "%100\\%%" →
        `.ilike("%100\\%%", escape="\\\\")` matches rows whose
        column contains the literal substring "100%".
    """
    cleaned = value.translate(_CONTROL_CHARS_TO_DROP)
    return cleaned.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
