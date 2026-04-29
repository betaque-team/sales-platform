"""F270 — seed_remote_companies must tolerate pre-existing slugs.

Manual sweep of prod logs found ``startup-seed: seed_remote_companies
failed (non-fatal)`` traceback dumped on every backend restart with
``UniqueViolationError on companies_slug_key``. Pre-fix the seed
looked up Companies by ``name`` only but the unique constraint is
on ``slug`` — if a scan had inserted a row with the same slug under
a different name (or a previous seed half-completed and a partial
state remained), the new seed's INSERT would collide.

The error was caught at the outermost level and tagged "non-fatal"
— but it dumped a multi-frame traceback into stderr on every
restart and aborted the rest of the seed loop's work. Real bugs
elsewhere got buried in the noise.

Fix: lookup by EITHER name OR computed slug; wrap the INSERT in a
savepoint and recover on IntegrityError.

These tests lock the policy down by source-grepping the seed
function for the markers we expect (``or_(Company.name`` matching
the broadened lookup; ``begin_nested`` for the savepoint;
``IntegrityError`` for the recovery branch).
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
os.environ.setdefault("JWT_SECRET", "pytest-f270")


def test_seed_remote_uses_or_lookup_by_name_and_slug():
    """The lookup must match on name OR slug, not just name. A
    regression that drops the slug branch re-opens the
    UniqueViolationError-on-restart bug.
    """
    from app import seed_remote_companies
    src = inspect.getsource(seed_remote_companies.seed_remote)
    assert "or_" in src, (
        "F270 regression: seed_remote no longer uses sqlalchemy.or_ "
        "in the company lookup. Restore the OR(name, slug) match — "
        "lookup-by-name-only re-opens the slug-conflict bug."
    )
    # Both branches must reference the canonical columns.
    assert "Company.name" in src
    assert "Company.slug" in src


def test_seed_remote_wraps_insert_in_savepoint():
    """The INSERT must run inside a SAVEPOINT (``begin_nested``) so a
    slug conflict caught after the lookup (concurrent scan, partial
    earlier seed state) doesn't poison the outer transaction.
    Without the savepoint, a single conflict aborts the whole seed
    loop — which was the pre-fix behaviour.
    """
    from app import seed_remote_companies
    src = inspect.getsource(seed_remote_companies.seed_remote)
    assert "begin_nested" in src, (
        "F270 regression: seed_remote no longer wraps the Company "
        "INSERT in begin_nested(). Without the savepoint, a residual "
        "slug conflict (e.g. race with discovery scan) crashes the "
        "whole loop and the rest of the seed's work is lost."
    )


def test_seed_remote_catches_integrity_error_and_recovers():
    """The except branch must catch IntegrityError specifically
    (not bare Exception) and re-fetch by slug to continue. A regression
    here would either silently swallow real bugs (bare except) or
    fail to recover (no re-fetch).
    """
    from app import seed_remote_companies
    src = inspect.getsource(seed_remote_companies.seed_remote)
    assert "IntegrityError" in src, (
        "F270 regression: seed_remote no longer catches IntegrityError "
        "explicitly. The recovery branch is needed for the rare race "
        "where a concurrent scan inserts the same slug between our "
        "lookup and INSERT."
    )
    # The except branch must re-fetch and continue, not skip.
    assert "Company.slug == company_slug" in src or 'where(Company.slug ==' in src, (
        "F270 regression: the recovery branch no longer re-fetches "
        "the conflicted Company by slug. Without the re-fetch, "
        "subsequent CompanyATSBoard inserts have no company reference."
    )
