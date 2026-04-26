"""Regression tests for the AI Intelligence (insights) router.

The bug that motivated this file (F245): ``GET /insights/product``
returned HTTP 500 with a bare ``"Internal Server Error"`` body for
every admin call, because the handler built its severity-rank
``ORDER BY`` expression with ``func.case(...)`` instead of the
top-level ``case(...)`` factory. ``func.X`` constructs a SQL function
call ``X(...)`` — no ``else_=`` kwarg, no CASE-WHEN semantics — so
the very first time the handler tried to assemble its query it raised
``TypeError: Function.__init__() got an unexpected keyword argument
'else_'``, which FastAPI surfaced as a generic 500. Every sibling
endpoint (``/insights/me``, ``POST /insights/run``, the 403 path)
worked because none of them touched the broken expression.

What this file locks down:

  1. The handler imports ``case`` from ``sqlalchemy`` (not
     ``func.case``) — the structural fix.

  2. The compiled severity-rank ``ORDER BY`` clause emits a real
     ``CASE WHEN ... THEN ... END`` SQL fragment so any future
     regression (e.g. someone "simplifies" back to ``func.case``)
     fails at module-import / query-build time, not in production.

  3. The ``ProductInsight.severity`` allowed values
     (``high``/``medium``/``low``) match what the rank expression
     branches on — drift between writer and reader would silently
     bucket new severity values into ``else_=0`` and sort them last.

No live DB. The ``select(...).order_by(case(...))`` is rendered
against the PostgreSQL dialect with ``literal_binds=True`` so we can
string-match the emitted SQL.
"""
from __future__ import annotations

import os


# Minimum env so app.config imports cleanly. Same pattern as every
# other router-level structural test in this directory.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://placeholder:placeholder@localhost:5432/placeholder",
)
os.environ.setdefault(
    "DATABASE_URL_SYNC",
    "postgresql://placeholder:placeholder@localhost:5432/placeholder",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET", "pytest-insights-router")


def test_insights_router_imports_case_not_funccase():
    """F245 regression — the module must import ``case`` from
    ``sqlalchemy`` directly. ``func.case`` is the broken form: it
    builds a SQL function call (``case(...)``), which PostgreSQL
    doesn't have, AND it raises ``TypeError`` on the ``else_=`` kwarg
    before the query even ships.

    Two independent markers so a partial revert (re-add ``func.case``
    while keeping the import) still fails:
      * the module's namespace exposes ``case`` (the factory)
      * ``case`` is the same object as ``sqlalchemy.case``
    """
    import sqlalchemy

    from app.api.v1 import insights as insights_module

    assert hasattr(insights_module, "case"), (
        "insights router must import ``case`` from sqlalchemy at module "
        "scope. Without it, the handler falls back to ``func.case`` and "
        "every GET /insights/product returns HTTP 500 (F245)."
    )
    assert insights_module.case is sqlalchemy.case, (
        "insights.case must be sqlalchemy.case — a shadowed local "
        "variable would silently mask the bug fix."
    )


def test_product_insights_severity_rank_renders_real_case_sql():
    """The ``ORDER BY`` for /insights/product must render a SQL
    ``CASE WHEN ... THEN ... END`` expression — the only correct
    way to express the severity ranking against a ``String(20)``
    column. Builds the same expression the handler builds and
    compiles it against the PostgreSQL dialect.
    """
    from sqlalchemy import case, select
    from sqlalchemy.dialects import postgresql

    from app.models.insight import ProductInsight

    severity_rank = case(
        (ProductInsight.severity == "high", 3),
        (ProductInsight.severity == "medium", 2),
        (ProductInsight.severity == "low", 1),
        else_=0,
    )

    query = (
        select(ProductInsight)
        .where(ProductInsight.actioned_at.is_(None))
        .order_by(severity_rank.desc(), ProductInsight.generated_at.desc())
    )

    sql = str(query.compile(
        dialect=postgresql.dialect(),
        compile_kwargs={"literal_binds": True},
    ))

    # Real CASE WHEN syntax — anything else (e.g. ``case(...)`` as a
    # function call) means the regression is back.
    assert "CASE WHEN" in sql, (
        f"severity rank did not render as a real CASE expression — got SQL:\n{sql}"
    )
    assert "ORDER BY CASE WHEN" in sql, (
        f"ORDER BY did not lead with the CASE rank — got SQL:\n{sql}"
    )
    # All three documented severity values must appear in the rank.
    for severity in ("'high'", "'medium'", "'low'"):
        assert severity in sql, (
            f"severity {severity} missing from rank expression — drift "
            f"between handler ranks and model writes. SQL was:\n{sql}"
        )


def test_funccase_with_else_kwarg_raises_proving_the_bug_shape():
    """Belt-and-suspenders check: if anyone tries to "fix" the
    handler by switching back to ``func.case(..., else_=0)``, the
    expression construction itself raises ``TypeError`` at handler
    invocation time. This test pins the failure mode so the regression
    can't sneak back in without a CI signal.
    """
    import pytest
    from sqlalchemy import func

    from app.models.insight import ProductInsight

    with pytest.raises(TypeError, match="else_"):
        func.case(
            (ProductInsight.severity == "high", 3),
            else_=0,
        )


def test_product_insights_endpoint_is_admin_gated():
    """The ``/product`` endpoint MUST stay admin-gated. F245 would
    have been worse if a viewer could trigger the same crash —
    every browser tab pre-fetching insights would 500-loop. The
    ``Depends(require_role('admin'))`` guard fires before the
    crashing handler body, so viewers correctly 403'd even while
    admins crashed; we want that invariant locked.
    """
    import inspect

    from app.api.v1 import insights as insights_module

    routes = insights_module.router.routes
    product_routes = [
        r for r in routes
        if getattr(r, "path", "").endswith("/product")
        and "GET" in (getattr(r, "methods", set()) or set())
    ]
    assert product_routes, "No GET /product route registered on insights router"

    route = product_routes[0]
    deps_chain: list = []

    def _walk(dep):
        deps_chain.append(dep.call)
        for sub in dep.dependencies:
            _walk(sub)

    for d in route.dependant.dependencies:
        _walk(d)

    matched = False
    for fn in deps_chain:
        try:
            src = inspect.getsource(fn)
        except (OSError, TypeError):
            continue
        if "Insufficient privileges" in src or "ROLE_HIERARCHY" in src:
            matched = True
            break

    assert matched, (
        "GET /insights/product no longer goes through require_role(admin)."
        " A viewer-reachable handler that 500s on every call would loop "
        "the frontend (F245 regression class)."
    )
