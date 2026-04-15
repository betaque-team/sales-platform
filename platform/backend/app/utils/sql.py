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


def escape_like(value: str) -> str:
    """Escape LIKE/ILIKE metacharacters so `value` is matched literally.

    Must be paired with `.ilike(pattern, escape="\\\\")` at the call
    site — the `ESCAPE '\\'` clause tells PostgreSQL that a literal
    backslash is the escape char. Without the `escape=` kwarg the
    backslashes stay inert and the `%`/`_` still act as wildcards.

    Order matters: escape `\\` first so we don't double-escape the
    backslashes we insert for `%` and `_`.

    Example:
        user types "100%" →
        escape_like("100%") == "100\\%" →
        f"%{escape_like('100%')}%" == "%100\\%%" →
        `.ilike("%100\\%%", escape="\\\\")` matches rows whose
        column contains the literal substring "100%".
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
