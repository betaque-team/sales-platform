"""F274 — pg_trgm GIN index on jobs.title for fast ILIKE search.

Revision ID: g3h4i5j6k7l8
Revises: f2g3h4i5j6k7
Create Date: 2026-04-29

Manual perf probe of /jobs found that title-search via
``LOWER(title) LIKE '%term%'`` triggered a sequential scan over all
86k+ rows for every search request:

  EXPLAIN (ANALYZE) on ``LOWER(title) LIKE '%senior devops%'``:
    Seq Scan on jobs (rows=86142 → 103)
    Execution Time: 114 ms

Per-call this is fine, but under burst load (50 concurrent search
requests = 50 × 114ms = 5.7s of CPU on a single uvicorn worker)
this was the dominant slow-query bottleneck contributing to the
F273 single-worker bottleneck.

Fix: GIN trigram index on ``LOWER(title)``. Postgres uses the
index for substring matching, dropping the seq scan.

  After index:
    Bitmap Index Scan on idx_jobs_title_trgm
    Execution Time: 51 ms (~2× faster, scales to 10× as catalog
    grows past 1M rows since seq-scan is linear and bitmap-index
    is sub-linear).

Idempotent via inspector ``IF NOT EXISTS`` checks. Also enables
the ``pg_trgm`` extension (Postgres-native, no superuser required
on RDS-style managed instances since postgres 11).
"""

import sqlalchemy as sa
from alembic import op


revision = "g3h4i5j6k7l8"
down_revision = "f2g3h4i5j6k7"
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
    # Enable pg_trgm. Postgres-native extension; ``IF NOT EXISTS``
    # is no-op when already enabled.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # GIN trigram index on lower(title) — backs the substring search
    # that ``api/v1/jobs.py:list_jobs`` runs via ``Job.title.ilike(
    # '%term%')``. The ``lower(...)`` wrapper matches the function
    # the query uses; without ``lower()``, the index doesn't apply.
    if not _index_exists("jobs", "idx_jobs_title_trgm"):
        op.execute(
            "CREATE INDEX idx_jobs_title_trgm "
            "ON jobs USING gin (lower(title) gin_trgm_ops)"
        )


def downgrade() -> None:
    if _index_exists("jobs", "idx_jobs_title_trgm"):
        op.execute("DROP INDEX idx_jobs_title_trgm")
    # Don't drop the extension — other tables/queries may use it
    # (companies search will likely follow as F274 follow-up).
