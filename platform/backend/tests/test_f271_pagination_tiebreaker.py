"""F271 — stable pagination via secondary sort tiebreaker.

Manual sweep finding: paginating /jobs by ``relevance_score:desc``
showed page 1 ending at score=93.16 and page 2 starting at score=
93.16. Many jobs share the same score (especially the top tier), so
without a stable secondary key Postgres returns ties in
implementation-defined order — different requests can produce
different orderings, and a reviewer flipping pages can see the same
row appear on both or vanish entirely.

Fix: append ``Job.id`` (btree-indexed UUID) as a final tiebreaker on
every sort chain. Cheap on the planner (Postgres uses the index for
the secondary key), deterministic across requests.

These tests lock the invariant down via source inspection. A live-DB
test would prove the actual ordering but the structural test catches
99% of regressions (someone removing the line) and runs without DB.
"""
from __future__ import annotations

import inspect
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
os.environ.setdefault("JWT_SECRET", "pytest-f271")


def test_jobs_list_appends_id_tiebreaker():
    """The list-jobs handler must append ``Job.id`` to its order
    clauses. A regression that drops this re-opens the unstable-
    pagination bug.
    """
    from app.api.v1 import jobs as jobs_module
    src = inspect.getsource(jobs_module.list_jobs)
    # The F271 marker comment is one signal; the actual append line is
    # the load-bearing one. Both should be present.
    assert "F271" in src, (
        "F271 regression: marker comment dropped — the tiebreaker "
        "logic likely went with it."
    )
    assert "Job.id.asc()" in src, (
        "F271 regression: ``Job.id.asc()`` no longer appended to "
        "the ORDER BY chain. Without this, sorts that have ties "
        "(e.g. relevance_score) produce different orderings on "
        "different requests. Reviewers flipping pages see rows "
        "appear/vanish."
    )


def test_jobs_list_skips_id_tiebreaker_when_already_present():
    """Pragmatic optimisation — if the user already sorted by id,
    we don't append a redundant ``id ASC`` after their ``id DESC``.
    Source check: the conditional that gates the append must be
    present.
    """
    from app.api.v1 import jobs as jobs_module
    src = inspect.getsource(jobs_module.list_jobs)
    assert "explicit_id_sort" in src, (
        "F271 regression: lost the explicit-id-sort guard. The "
        "append-id line should be conditional so users who explicitly "
        "sort by id don't get a duplicate clause."
    )
    assert "if not explicit_id_sort" in src
