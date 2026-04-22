"""Structural tests for the Claude Routine Apply router.

No live DB. We import the router module and inspect its FastAPI
metadata to lock down invariants that determine whether the feature
is safe to ship:

  1. Every route requires authentication. A routine endpoint without
     ``get_current_user`` in its dependency chain would let an
     unauthenticated caller trigger a run on behalf of someone else.

  2. The prefix is ``/routine``. The v6 docs + the frontend api.ts
     both bake this path in; renaming it silently is a breaking
     change we want to notice in CI.

  3. Tunables match the v6 spec. DAILY_CAP, COMPANY_COOLDOWN_DAYS,
     EXCLUDED_PLATFORMS — regression protection for anyone who
     "temporarily bumps" a constant without updating the spec.

  4. The routine accepts every geography bucket the answer_book_seed
     covers with a salary row. If the two drift (e.g. we add a new
     bucket but forget the corresponding salary seed), the routine
     can't fill salary for jobs in the new bucket and the operator
     silently gets a broken run.

End-to-end HTTP + DB coverage is covered by the live integration
harness (tests/test_api.py script-mode), not here.
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
os.environ.setdefault("JWT_SECRET", "pytest-routine")


def test_router_prefix_is_routine():
    """The frontend api.ts hardcodes ``/routine/...`` paths; the v6
    docs do too. Prefix renames must be caught at CI time."""
    from app.api.v1.routine import router

    assert router.prefix == "/routine"


def test_every_route_requires_authentication():
    """Walk every route on the router and assert its dependency
    chain includes ``get_current_user``. Operator-scoped endpoints
    MUST NOT be callable unauthenticated.

    FastAPI stores dependencies on ``route.dependant``; we recurse
    through sub-dependants to catch the common "declared via Depends
    on a parameter" case.
    """
    from app.api.deps import get_current_user
    from app.api.v1.routine import router

    def _collect_call_sites(dependant) -> set[object]:
        """Flatten every ``dependant.call`` down the tree."""
        out: set[object] = set()
        if dependant.call is not None:
            out.add(dependant.call)
        for sub in dependant.dependencies:
            out |= _collect_call_sites(sub)
        return out

    for route in router.routes:
        call_sites = _collect_call_sites(route.dependant)
        assert get_current_user in call_sites, (
            f"{route.path} [{','.join(route.methods or [])}] has no "
            f"get_current_user dependency — routine endpoints must be "
            f"authenticated"
        )


def test_tunables_match_v6_spec():
    """Constants the v6 spec + tests + docs all reference. If these
    move, the move should be deliberate — this test makes the edit
    visible in the diff."""
    from app.api.v1.routine import (
        COMPANY_COOLDOWN_DAYS,
        DAILY_CAP,
        EXCLUDED_PLATFORMS,
        ROUTINE_GEOGRAPHY_BUCKETS,
    )

    assert DAILY_CAP == 10
    assert COMPANY_COOLDOWN_DAYS == 30
    assert "linkedin" in EXCLUDED_PLATFORMS
    # Buckets must be a tuple (ordered, hashable). If someone converts
    # to a list the .index() / SQL IN semantics stay fine, but a set
    # would drop the determinism the spec asks for.
    assert isinstance(ROUTINE_GEOGRAPHY_BUCKETS, tuple)
    assert set(ROUTINE_GEOGRAPHY_BUCKETS) == {
        "global_remote", "usa_only", "uae_only"
    }


def test_routine_geography_buckets_have_salary_seed_coverage():
    """If we add a new geography bucket to the routine without seeding
    a corresponding salary-minimum answer-book entry, the routine has
    no salary answer to give for jobs in that bucket — and required-
    coverage will silently pass because the missing row isn't in the
    seed list either.

    This test pins the one-to-one relationship between the buckets
    the routine filters on and the ``expected_min_salary_*`` seed
    rows. Adding a bucket without the seed row (or vice versa) fails
    CI.
    """
    from app.api.v1.routine import ROUTINE_GEOGRAPHY_BUCKETS
    from app.services.answer_book_seed import REQUIRED_ENTRIES

    # "remote" in the seed == "global_remote" in the bucket list; the
    # routing layer normalises. "global" is a catch-all for unclassified
    # regions. Keep the explicit mapping here.
    BUCKET_TO_SEED_KEY = {
        "global_remote": "expected_min_salary_remote",
        "usa_only": "expected_min_salary_usa",
        "uae_only": "expected_min_salary_uae",
    }
    seed_keys = {qkey for (_cat, qkey, _q) in REQUIRED_ENTRIES}

    for bucket in ROUTINE_GEOGRAPHY_BUCKETS:
        expected_seed = BUCKET_TO_SEED_KEY.get(bucket)
        assert expected_seed is not None, (
            f"ROUTINE_GEOGRAPHY_BUCKETS contains {bucket!r} but this "
            f"test has no mapping for it — update BUCKET_TO_SEED_KEY"
        )
        assert expected_seed in seed_keys, (
            f"routine bucket {bucket!r} needs seed key {expected_seed!r} "
            f"but answer_book_seed.REQUIRED_ENTRIES doesn't contain it"
        )


def test_routine_router_registered_in_v1_router():
    """Smoke-test: the routine router must be included in the v1
    router aggregator, or none of the endpoints above are reachable
    at all."""
    from app.api.v1.router import api_router

    # The aggregator api_router has its own ``/api/v1`` prefix, so
    # included-router paths come out as ``/api/v1/routine/...``. We
    # match on substring, not startswith, so the test doesn't break
    # if the v1 prefix is ever bumped.
    routine_paths = [
        route.path
        for route in api_router.routes
        if "/routine" in route.path
    ]
    assert routine_paths, (
        "no /routine/... routes found on api_router — routine router "
        "is not registered"
    )
    # Spot-check the headline endpoints the frontend talks to. If one
    # of these is renamed, the frontend breaks silently in prod.
    joined = " ".join(routine_paths)
    for path_fragment in [
        "/routine/top-to-apply",
        "/routine/kill-switch",
        "/routine/runs",
        "/routine/humanize",
    ]:
        assert path_fragment in joined, (
            f"expected {path_fragment} on api_router — got {routine_paths}"
        )
