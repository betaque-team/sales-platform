"""F275 — companies.name trigram index migration structural test.

Companion to F274 (jobs.title trigram). The /jobs search endpoint
matches against BOTH ``Job.title`` AND ``Company.name`` via
``or_(...)``. F274's index helps the title-side; F275 helps the
company-name-side (used in the ``Company.name.has(.ilike())``
EXISTS subquery).

These tests verify the migration shape. The OR-pattern that forces
seq scan on the outer query is a known Postgres planner limitation
(out of scope for F275 — would need a UNION rewrite of the search
filter).
"""
from __future__ import annotations

import os
import pathlib

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://placeholder:placeholder@localhost:5432/placeholder",
)
os.environ.setdefault(
    "DATABASE_URL_SYNC",
    "postgresql://placeholder:placeholder@localhost:5432/placeholder",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET", "pytest-f275")


_MIGRATIONS_DIR = (
    pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions"
)


def _find_migration() -> pathlib.Path:
    matches = list(_MIGRATIONS_DIR.glob("*_h4i5j6k7l8m9_*.py"))
    assert len(matches) == 1, (
        f"F275 regression: expected 1 migration with revision id "
        f"h4i5j6k7l8m9, found {len(matches)}: {matches}"
    )
    return matches[0]


def test_migration_chains_from_f274():
    """F275 must descend from F274's revision (``g3h4i5j6k7l8``)
    so alembic upgrade applies them in the right order. A break
    here surfaces as a "missing parent revision" deploy error.
    """
    src = _find_migration().read_text()
    assert 'revision = "h4i5j6k7l8m9"' in src
    assert 'down_revision = "g3h4i5j6k7l8"' in src


def test_migration_creates_raw_name_gin_index():
    """The index must be on RAW ``name``, NOT ``lower(name)`` — same
    reasoning as F274(b). ``Company.name.ilike(...)`` compiles to
    ``name ~~* pattern`` with no LOWER wrapper.
    """
    src = _find_migration().read_text()
    code_lines = [
        ln for ln in src.splitlines()
        if "CREATE INDEX" in ln or "USING gin" in ln or "gin_trgm_ops" in ln
    ]
    code = " ".join(code_lines)
    assert "lower(name)" not in code, (
        "F275 regression: index is on ``lower(name)``. ILIKE "
        "compiles to ``name ~~* pattern`` (no LOWER wrapper) so "
        "the lower-wrapped index doesn't fire."
    )
    assert "(name gin_trgm_ops)" in code, (
        "F275 regression: index expression must be ``name "
        "gin_trgm_ops`` (raw column)."
    )


def test_migration_idempotent():
    """Re-running ``alembic upgrade head`` after manual creation
    must not error. The index was created manually on prod during
    the F274 perf probe; the migration must not double-create.
    """
    src = _find_migration().read_text()
    assert "_index_exists" in src or "IF NOT EXISTS" in src
