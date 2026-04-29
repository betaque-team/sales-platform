"""F274 — jobs.title trigram index migration structural test.

Manual perf probe found that ``/jobs?search=...`` was triggering
seq scans on the jobs table (114ms per call). Under the F273
multi-worker rollout this is still the dominant slow-query — 2
workers × 114ms per concurrent search = real wall-clock
degradation at burst.

Fix: pg_trgm GIN index on ``LOWER(title)`` via Alembic migration
``g3h4i5j6k7l8``. Drops the seq-scan path; bitmap-index-scan is
sub-linear so the speedup grows as the catalog scales past 1M
rows.

These tests verify the migration file structure (revision IDs,
extension creation, index creation). The actual EXPLAIN-ANALYZE
verification runs as a one-off live-DB probe at deploy time —
captured in the migration docstring.
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
os.environ.setdefault("JWT_SECRET", "pytest-f274")


_MIGRATIONS_DIR = (
    pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions"
)


def _find_migration() -> pathlib.Path:
    matches = list(_MIGRATIONS_DIR.glob("*_g3h4i5j6k7l8_*.py"))
    assert len(matches) == 1, (
        f"F274 regression: expected exactly 1 migration with revision "
        f"id g3h4i5j6k7l8, found {len(matches)}: {matches}"
    )
    return matches[0]


def test_migration_chains_correctly():
    """The F274 migration must descend from the prior head
    ``f2g3h4i5j6k7`` (remote_scope). A regression that breaks the
    chain (e.g. someone changes the down_revision) shows up as
    alembic refusing to upgrade with a "multiple heads" error or
    a missing-link error at deploy.
    """
    src = _find_migration().read_text()
    assert 'revision = "g3h4i5j6k7l8"' in src
    assert 'down_revision = "f2g3h4i5j6k7"' in src


def test_migration_creates_pg_trgm_extension():
    """``pg_trgm`` must be enabled before the GIN index can use
    ``gin_trgm_ops``. The migration must call ``CREATE EXTENSION
    IF NOT EXISTS pg_trgm`` — without it, prod deploy errors with
    'operator class gin_trgm_ops does not exist'.
    """
    src = _find_migration().read_text()
    assert "CREATE EXTENSION IF NOT EXISTS pg_trgm" in src, (
        "F274 regression: migration no longer enables pg_trgm. "
        "The GIN index ``gin_trgm_ops`` will fail at create time "
        "without the extension."
    )


def test_migration_creates_raw_title_gin_index():
    """F274(b) — the GIN index must be on RAW ``title``, NOT
    ``lower(title)``.

    The original F274 patch put the index on ``lower(title)`` thinking
    that would back the ILIKE search. But ``Job.title.ilike(...)``
    compiles to ``title ~~* pattern`` (the ILIKE operator) with NO
    ``LOWER(...)`` wrapper. Postgres requires indexed expression to
    EXACTLY match the query expression to apply the index — so the
    lower-wrapped index never fired and queries fell back to seq
    scan (146ms on 86k rows).

    The correct shape is ``USING gin (title gin_trgm_ops)`` — the
    pg_trgm extension's trigram extraction is inherently case-
    insensitive, so the raw-column index supports both LIKE and
    ILIKE. With the correct index, the same query drops to ~3ms.
    """
    src = _find_migration().read_text()
    # The DDL must NOT wrap title in lower() — that's the bug.
    # We check the actual CREATE INDEX line, not the docstring
    # (which can mention the historical bug).
    code_lines = [
        ln for ln in src.splitlines()
        if "CREATE INDEX" in ln or ("USING gin" in ln) or "gin_trgm_ops" in ln
    ]
    code = " ".join(code_lines)
    assert "lower(title)" not in code, (
        "F274(b) regression: index is on ``lower(title)`` again. "
        "ILIKE compiles to ``title ~~* pattern`` (no LOWER wrapper) "
        "so the lower-wrapped index doesn't fire. Use raw ``title``."
    )
    assert "(title gin_trgm_ops)" in code or "title gin_trgm_ops" in code, (
        "F274(b) regression: index expression must be ``title "
        "gin_trgm_ops`` (raw column). Current source: " + code[:200]
    )
    assert "using gin" in src.lower(), (
        "F274 regression: index type is no longer GIN. Btree/hash "
        "don't support substring search."
    )


def test_migration_is_idempotent_via_if_not_exists():
    """Idempotent migrations are required because alembic upgrade
    head can re-run partially against a DB where the index was
    created manually (as it was during F274 perf probe). Without
    IF NOT EXISTS, the second run errors with 'index already
    exists'.
    """
    src = _find_migration().read_text()
    # We use _index_exists() guard via inspector; the SQL itself
    # also has IF NOT EXISTS as defense-in-depth.
    assert "_index_exists" in src or "IF NOT EXISTS" in src, (
        "F274 regression: migration lacks an idempotency guard. "
        "Re-running ``alembic upgrade head`` after the index was "
        "created manually will error."
    )
