"""Cross-platform job dedup — unit tests for the Tier-1 quality fix.

The new logic sits inside ``_upsert_job`` in ``scan_task.py``. When a
scan finds a job whose ``external_id`` is new AND whose exact title
doesn't match an existing row (both conditions already handled by
earlier dedup layers), we do a third check: does the SAME company
already have a still-active Job with the same ``title_normalized``?
If yes, we treat the new job as an update of the existing row and
record the cross-platform sighting in ``raw_json._also_seen_on``.

Test surface — four decision points that collectively prove the
feature behaves:

1. **Exact dedup key** — a new listing with a DIFFERENT literal title
   but the SAME normalized title on a DIFFERENT platform collapses
   into the existing row, and the new sighting lands in ``_also_seen_on``.

2. **Load-bearing empty-title guard** — when ``title_normalized`` is
   empty (e.g. a job the role-matcher couldn't classify), we must NOT
   match against other empty-normalized jobs. That'd collapse every
   unclassified job at a company into one row. Catastrophic.

3. **Staleness cutoff** — a matching row from >90 days ago does NOT
   block a fresh insert. Companies re-post roles they closed months
   ago; those are legitimately new listings.

4. **Same-platform no-op** — the cross-platform branch only writes to
   ``_also_seen_on`` when the MATCHING row is on a DIFFERENT platform.
   Within-platform matches already flow through F88 (exact-title) and
   the external_id UNIQUE — they're not our concern here.

Why mocks not a live DB: ``_upsert_job`` is 100+ lines of synchronous
SQLAlchemy with role_matching + geography + scoring side-effects.
Exercising it against real Postgres would require fixture scaffolding
we don't have today. The decision points above are tightly-scoped
branches inside that function, and stubbing the three DB calls (lookup
by external_id, lookup by title, lookup by title_normalized) isolates
them cleanly.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest


# Minimum env so app.config imports cleanly — matches test_smoke.py pattern.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://placeholder:placeholder@localhost:5432/placeholder",
)
os.environ.setdefault(
    "DATABASE_URL_SYNC",
    "postgresql://placeholder:placeholder@localhost:5432/placeholder",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET", "pytest-dedup")


# ── Test harness ───────────────────────────────────────────────────


class _FakeJob:
    """Duck-typed stand-in for a Job ORM row.

    ``_upsert_job`` does a lot of mutation against the returned row
    (``existing.title = …``, ``existing.relevance_score = …``, etc.)
    — anything that's not a plain attribute would fail. Plain object
    works because SQLAlchemy's change tracker isn't involved in the
    test (we never commit).
    """

    def __init__(
        self,
        *,
        title: str,
        title_normalized: str,
        platform: str,
        status: str = "new",
        first_seen_at: datetime | None = None,
        raw_json: dict | None = None,
    ):
        import uuid as _uuid
        self.id = _uuid.uuid4()
        self.external_id = f"ext-{_uuid.uuid4().hex[:8]}"
        self.title = title
        self.title_normalized = title_normalized
        self.platform = platform
        self.status = status
        self.first_seen_at = first_seen_at or datetime.now(timezone.utc)
        self.last_seen_at = self.first_seen_at
        self.posted_at = None
        self.raw_json = raw_json or {}
        # Fields _upsert_job writes into — initialised so mutation works.
        self.url = ""
        self.location_raw = ""
        self.remote_scope = ""
        self.department = ""
        self.employment_type = ""
        self.salary_range = ""
        self.matched_role = ""
        self.role_cluster = ""
        self.geography_bucket = ""
        self.relevance_score = 0.0


class _FakeCompany:
    def __init__(self, *, slug="acme", name="ACME", is_target=False):
        import uuid as _uuid
        self.id = _uuid.uuid4()
        self.slug = slug
        self.name = name
        self.is_target = is_target


class _FakeBoard:
    def __init__(self, *, platform="greenhouse", slug="acme"):
        self.platform = platform
        self.slug = slug


def _stub_session(*, existing_by_external_id=None, existing_by_exact_title=None,
                  existing_by_normalized_title=None):
    """Build a session whose .execute() returns the three lookup results
    in the order ``_upsert_job`` issues them.

    The function makes exactly three selects before the "insert vs
    update" branch (in order):
      1. WHERE external_id = :ext
      2. WHERE company_id = :co AND title = :title     (F88)
      3. WHERE company_id = :co AND title_normalized   (new cross-platform)

    Each returns either a row or None. Any of the three may be skipped
    if a previous lookup found a match (the function short-circuits
    with ``if not existing``). Here we return canned results for all
    three positions; unused ones are harmless.
    """
    session = MagicMock()

    def make_scalar_result(value):
        m = MagicMock()
        m.scalar_one_or_none.return_value = value
        return m

    session.execute.side_effect = [
        make_scalar_result(existing_by_external_id),
        make_scalar_result(existing_by_exact_title),
        make_scalar_result(existing_by_normalized_title),
    ]
    session.add = MagicMock()
    session.flush = MagicMock()
    return session


# ── Tests ──────────────────────────────────────────────────────────


def test_cross_platform_soft_match_collapses_into_existing_row():
    """Different literal title, same normalized title, different
    platform → new listing collapses into existing row. Key value
    ``_also_seen_on`` records the new platform+external_id.
    """
    from app.workers.tasks import scan_task

    # Existing Job on Greenhouse. title_normalized set by an earlier
    # role-matcher run (e.g. both "Senior SRE" and "Sr. SRE" normalize
    # to the cluster role "site_reliability_engineer").
    existing = _FakeJob(
        title="Senior SRE",
        title_normalized="site_reliability_engineer",
        platform="greenhouse",
        status="new",
    )
    session = _stub_session(
        existing_by_external_id=None,
        existing_by_exact_title=None,
        existing_by_normalized_title=existing,
    )

    raw_job = {
        "external_id": "lever-xyz-123",
        # Different literal title, same normalized role.
        "title": "Sr. Site Reliability Engineer",
        "url": "https://jobs.lever.co/acme/xyz",
        "platform": "lever",
        "location_raw": "Remote",
        "remote_scope": "worldwide",
        "raw_json": {"lever_payload": True},
    }

    # Stub the role matcher so both titles return the same
    # title_normalized — the preconditions for our new check.
    with patch.object(
        scan_task, "match_role_with_config",
        return_value={
            "matched_role": "site_reliability_engineer",
            "role_cluster": "infra",
            "title_normalized": "site_reliability_engineer",
        },
    ), patch.object(scan_task, "classify_geography", return_value="global_remote"):
        result = scan_task._upsert_job(
            session,
            _FakeCompany(),
            _FakeBoard(platform="lever"),
            raw_job,
        )

    # Behavior assertions — the heart of the test.
    assert result == "updated", (
        f"Expected 'updated' (dedup hit) but got {result!r} — new Job row "
        "was created despite the same normalized role existing on another platform"
    )
    # Cross-platform sighting recorded.
    also_seen = existing.raw_json.get("_also_seen_on", [])
    assert "lever:lever-xyz-123" in also_seen, (
        f"_also_seen_on should contain the new sighting, got {also_seen!r}"
    )
    # session.add must NOT have been called — that's the insert path.
    assert session.add.call_count == 0, (
        "session.add() was called — a duplicate Job row was inserted"
    )


def test_cross_platform_match_ignored_when_title_normalized_is_empty():
    """If ``title_normalized`` is empty (role-matcher couldn't classify
    the title), the normalized-title branch MUST NOT match. Otherwise
    every unclassified job at a company would collapse into one row.
    """
    from app.workers.tasks import scan_task

    # This row has an empty `title_normalized` — the role-matcher
    # couldn't classify its title. If the guard is missing, the new
    # job (also with empty `title_normalized`) would collide with it.
    existing_empty = _FakeJob(
        title="Some Unclassified Role",
        title_normalized="",  # critical — the trap the guard protects against
        platform="greenhouse",
    )
    session = _stub_session(
        existing_by_external_id=None,
        existing_by_exact_title=None,
        # Even if we *returned* this row from the normalized-title
        # query, the guard should skip the branch entirely and never
        # reach the assignment. We return it anyway to prove the guard
        # fires BEFORE the query result is examined.
        existing_by_normalized_title=existing_empty,
    )

    raw_job = {
        "external_id": "lever-abc-789",
        "title": "Completely Different Thing",  # also unclassifiable
        "url": "https://jobs.lever.co/acme/abc",
        "platform": "lever",
        "location_raw": "",
        "remote_scope": "",
        "raw_json": {},
    }

    # match_role_with_config returns empty title_normalized — triggers the guard.
    with patch.object(
        scan_task, "match_role_with_config",
        return_value={"matched_role": "", "role_cluster": "", "title_normalized": ""},
    ), patch.object(scan_task, "classify_geography", return_value=""):
        result = scan_task._upsert_job(
            session,
            _FakeCompany(),
            _FakeBoard(platform="lever"),
            raw_job,
        )

    # No cross-platform hit → new row path was taken → session.add() called.
    assert result == "new", (
        f"Expected 'new' (fresh insert, guard worked) but got {result!r} — "
        "two unclassified jobs collided into one row"
    )
    assert session.add.call_count == 1
    # Existing row's raw_json must NOT have been mutated.
    assert existing_empty.raw_json == {}, (
        f"Existing unclassified row was mutated: {existing_empty.raw_json!r}"
    )


def test_cross_platform_match_respects_90_day_cutoff():
    """A matching row from >90 days ago must NOT block a fresh insert.
    The normalized-title query filters on ``first_seen_at >= cutoff``,
    so we stub the session to return None (simulating the filter
    excluding the stale row) and verify the fresh-insert path runs.

    The staleness guard lives inside the SQL query, not in Python
    post-filter — so this test primarily documents the expected
    behavior. The SQL filter is directly asserted via the query
    construction (covered by the query inspection below).
    """
    from app.workers.tasks import scan_task

    session = _stub_session(
        existing_by_external_id=None,
        existing_by_exact_title=None,
        # SQL filter excludes the stale row — query returns None.
        existing_by_normalized_title=None,
    )

    raw_job = {
        "external_id": "gh-new-555",
        "title": "Site Reliability Engineer",
        "url": "https://boards.greenhouse.io/acme/jobs/555",
        "platform": "greenhouse",
        "location_raw": "NYC",
        "remote_scope": "",
        "raw_json": {},
    }

    with patch.object(
        scan_task, "match_role_with_config",
        return_value={
            "matched_role": "site_reliability_engineer",
            "role_cluster": "infra",
            "title_normalized": "site_reliability_engineer",
        },
    ), patch.object(scan_task, "classify_geography", return_value=""):
        result = scan_task._upsert_job(
            session,
            _FakeCompany(),
            _FakeBoard(platform="greenhouse"),
            raw_job,
        )

    # No active-recent match → fresh insert.
    assert result == "new"
    assert session.add.call_count == 1

    # Directly assert the 90-day filter is in the SQL query structure.
    # This is the load-bearing assertion — if someone removes the
    # `first_seen_at >= cutoff` filter, a 2-year-old "SWE" row would
    # block every new "SWE" listing from ever landing.
    import inspect
    src = inspect.getsource(scan_task._upsert_job)
    assert "timedelta(days=90)" in src, (
        "90-day staleness cutoff missing from _upsert_job — stale rows "
        "will swallow legitimate fresh listings"
    )
    assert "Job.first_seen_at >= cutoff" in src, (
        "SQL filter on first_seen_at missing — staleness guard inoperative"
    )


def test_cross_platform_same_platform_match_does_not_write_also_seen_on():
    """When a normalized-title match finds a row on the SAME platform
    as the new listing, ``_also_seen_on`` must NOT be populated — it's
    meant to track CROSS-platform sightings, not within-platform
    repeats (those flow through F88 / external_id dedup).
    """
    from app.workers.tasks import scan_task

    existing = _FakeJob(
        title="Senior SRE",
        title_normalized="site_reliability_engineer",
        platform="greenhouse",  # SAME platform as the incoming job
    )
    session = _stub_session(
        existing_by_external_id=None,
        existing_by_exact_title=None,
        existing_by_normalized_title=existing,
    )

    raw_job = {
        "external_id": "gh-same-platform-999",
        "title": "Sr. SRE",
        "url": "https://boards.greenhouse.io/acme/jobs/999",
        "platform": "greenhouse",  # same platform
        "location_raw": "",
        "remote_scope": "",
        "raw_json": {},
    }

    with patch.object(
        scan_task, "match_role_with_config",
        return_value={
            "matched_role": "site_reliability_engineer",
            "role_cluster": "infra",
            "title_normalized": "site_reliability_engineer",
        },
    ), patch.object(scan_task, "classify_geography", return_value=""):
        result = scan_task._upsert_job(
            session,
            _FakeCompany(),
            _FakeBoard(platform="greenhouse"),  # SAME
            raw_job,
        )

    # Still collapses (normalized-title dedup fired) but doesn't add
    # a cross-platform sighting marker.
    assert result == "updated"
    assert "_also_seen_on" not in existing.raw_json, (
        f"Same-platform dedup polluted _also_seen_on: {existing.raw_json!r}"
    )
