"""F275 — pg_trgm GIN index on companies.name for fast ILIKE search.

Revision ID: h4i5j6k7l8m9
Revises: g3h4i5j6k7l8
Create Date: 2026-04-29

Companion to F274 (which added the same index on jobs.title). The
``/jobs?search=...`` endpoint matches against BOTH ``Job.title`` AND
``Company.name`` via ``or_(...)``, so even with a fast jobs.title
index the planner has to scan companies for the OR-branch.

  EXPLAIN before:  Seq Scan on companies (12,639 rows filtered)
  EXPLAIN after:   Bitmap Index Scan on idx_companies_name_trgm

Note: the OR-pattern (jobs.title OR companies.name-via-subquery)
still forces the outer planner to seq-scan jobs because Postgres
can't use jobs.title's trigram index when its predicate is OR'd
with a sub-EXISTS clause. The companies-side index does help in
isolation (when the search hits ONLY company-name matches) and
keeps the EXISTS subquery cheap. A future F-feature could rewrite
the query as UNION to let both indexes fire — out of scope here.

Idempotent via inspector check; index was created manually on
prod during the F274 perf probe and this migration just makes it
canonical for fresh installs.
"""

import sqlalchemy as sa
from alembic import op


revision = "h4i5j6k7l8m9"
down_revision = "g3h4i5j6k7l8"
branch_labels = None
depends_on = None


def _index_exists(table: str, name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    try:
        return name in {ix["name"] for ix in inspector.get_indexes(table)}
    except Exception:
        return False


def upgrade() -> None:
    # pg_trgm should already be enabled by F274's migration; the
    # IF NOT EXISTS guard makes a re-run cheap if it isn't.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # Index on RAW name (not lower(name)) — same reasoning as F274(b):
    # ``Company.name.ilike(...)`` compiles to ``name ~~* pattern`` with
    # no LOWER wrapper, so the index expression must match the raw
    # column for the planner to apply it. ``gin_trgm_ops`` is itself
    # case-insensitive.
    if not _index_exists("companies", "idx_companies_name_trgm"):
        op.execute(
            "CREATE INDEX idx_companies_name_trgm "
            "ON companies USING gin (name gin_trgm_ops)"
        )


def downgrade() -> None:
    if _index_exists("companies", "idx_companies_name_trgm"):
        op.execute("DROP INDEX idx_companies_name_trgm")
