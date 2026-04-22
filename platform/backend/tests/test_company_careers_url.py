"""Coverage tests for the Phase-A careers_url feature.

Four focused tests covering the surface we actually shipped:

1. **Schema exposure** — ``CompanyOut`` must include ``careers_url``
   + ``careers_url_fetched_at``. Catches the easy regression where
   someone adds a column to the model but forgets the schema and
   the API silently stops returning it.

2. **Task success path** — ``fingerprint_existing_companies`` sets
   ``company.careers_url`` + ``careers_url_fetched_at`` on the
   Company row when the fingerprint service finds at least one ATS.
   Mocked-session + mocked-fingerprint so we don't need a live DB.

3. **Task no-match path** — when the fingerprint service returns
   ``[]`` for every candidate URL, the Company row must be left
   UNTOUCHED (no careers_url write, no timestamp write). Guards
   against the failure mode where we'd silently save a URL that
   didn't actually resolve to an ATS.

4. **Migration symmetry** — the alembic migration upgrades add the
   columns and the downgrade drops them. Static check on the file
   contents; doesn't run the migration (that's covered by CI's
   ``alembic upgrade head`` step).

Not in scope: live end-to-end with real DB + real HTTP. The existing
``test_ats_fingerprint.py`` integration suite already covers the
fingerprint-service half of that path against real careers pages
(Palantir/Ramp/AT&T) — so if those pass and these unit tests pass,
the only remaining failure surface is the SQLAlchemy session
integration, which is exercised on every deploy when the migration
auto-runs.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import MagicMock

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
os.environ.setdefault("JWT_SECRET", "pytest-careers-url")


# ── Test 1: schema exposure ────────────────────────────────────────

def test_company_out_exposes_careers_url_fields():
    """``CompanyOut`` must serialize ``careers_url`` + ``careers_url_fetched_at``.

    If someone adds a column to the model but forgets the schema, the
    API stops returning it and the frontend silently breaks. This
    test exercises the schema contract, not the model. Looks at both
    the field list AND the dumped JSON with a populated instance so
    regressions in either direction fail loud.
    """
    from app.schemas.company import CompanyOut

    field_names = set(CompanyOut.model_fields.keys())
    assert "careers_url" in field_names, (
        "CompanyOut schema missing `careers_url` — frontend will not see it. "
        "Add it to app/schemas/company.py:CompanyOut alongside `website`."
    )
    assert "careers_url_fetched_at" in field_names, (
        "CompanyOut schema missing `careers_url_fetched_at` — admins can't "
        "tell whether a company was recently fingerprinted."
    )

    # Exercise a populated instance through model_dump. A field that
    # exists in `model_fields` but is somehow filtered out of
    # `.model_dump(mode='json')` would slip past a naive field-only
    # check; dumping catches both.
    from uuid import uuid4
    from datetime import datetime, timezone
    sample = CompanyOut(
        id=uuid4(),
        name="ACME",
        slug="acme",
        careers_url="https://acme.com/careers",
        careers_url_fetched_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    dumped = sample.model_dump(mode="json")
    assert dumped["careers_url"] == "https://acme.com/careers"
    assert dumped["careers_url_fetched_at"] is not None


# ── Tests 2 + 3: fingerprint task behavior ─────────────────────────


class _FakeCompany:
    """Minimal duck-typed Company for the task to iterate over.

    The real Company model has dozens of columns. For this unit test
    we only need the ones the task reads/writes. Using a plain object
    (not a real SQLAlchemy instance) sidesteps the need to spin up a
    DB just to construct a Company row.
    """

    def __init__(self, *, website: str = "https://acme.com", name: str = "ACME"):
        import uuid as _uuid
        self.id = _uuid.uuid4()
        self.website = website
        self.name = name
        self.careers_url: str | None = None
        self.careers_url_fetched_at = None
        self.created_at = datetime.now(timezone.utc)


def _make_fake_session(companies_to_return: list[_FakeCompany]):
    """Build a mock SyncSession whose .execute() returns the given list
    on the first 'select Company' call, and empty on the existing-pairs
    lookup.

    The task calls session.execute three times meaningfully:
      1. Load candidate companies (.scalars().all() → list of Company)
      2. Load existing (platform, slug) pairs (.all() → list of tuples)
      3. (per-company) add() + flush() inside the loop

    We return two canned results in order: first call → companies,
    second call → empty existing-pairs. Subsequent .execute calls
    shouldn't happen in a single-company test.
    """
    session = MagicMock()

    # First .execute() returns a result whose .scalars().all() is the
    # companies. Second returns a result whose .all() is the
    # existing-pairs iterable. MagicMock's side_effect lets us stage
    # both responses in order.
    companies_result = MagicMock()
    companies_result.scalars.return_value.all.return_value = companies_to_return
    pairs_result = MagicMock()
    pairs_result.all.return_value = []  # no pre-existing pairs

    # The task's first DB call is for DiscoveryRun insert; it calls
    # session.add() and session.flush() but doesn't execute(). So the
    # first real execute() is for the company list.
    session.execute.side_effect = [companies_result, pairs_result]

    # Track writes — the test asserts on these later.
    session._added = []

    def fake_add(obj):
        session._added.append(obj)
    session.add.side_effect = fake_add

    # commit + flush are no-ops in the mock (real session would hit DB)
    session.flush = MagicMock()
    session.commit = MagicMock()
    session.rollback = MagicMock()
    session.close = MagicMock()

    return session


def test_fingerprint_task_writes_careers_url_on_match(monkeypatch):
    """When `detect_ats_from_url` returns a fingerprint, the task must
    set ``company.careers_url`` + ``careers_url_fetched_at`` to the
    URL that actually matched.

    This is the primary value the feature ships — skipping this write
    means the whole Phase-A fallback groundwork is inert.
    """
    from app.workers.tasks import discovery_task
    from app.services.ats_fingerprint import ATSFingerprint

    company = _FakeCompany(website="https://acme.com")

    # Stub SyncSession to return our fake session — the task's
    # ``session = SyncSession()`` line hits this.
    fake_session = _make_fake_session([company])
    monkeypatch.setattr(
        discovery_task, "SyncSession",
        MagicMock(return_value=fake_session),
    )

    # Stub detect_ats_from_url to return a Greenhouse fingerprint
    # on the FIRST candidate URL (`/careers`), nothing on the
    # others. Matches the task's try-order.
    call_log: list[str] = []

    def fake_detect(url, **kwargs):
        call_log.append(url)
        if url.endswith("/careers"):
            return [ATSFingerprint(
                platform="greenhouse",
                slug="acme",
                careers_url="https://boards.greenhouse.io/acme",
            )]
        return []

    monkeypatch.setattr(
        "app.services.ats_fingerprint.detect_ats_from_url",
        fake_detect,
    )
    # The task does `from app.services.ats_fingerprint import detect_ats_from_url`
    # inside the function body, so patching the source module is what
    # matters — but if the import was already executed in an earlier
    # test, we also patch the already-imported binding defensively.
    import app.services.ats_fingerprint as ats_mod
    monkeypatch.setattr(ats_mod, "detect_ats_from_url", fake_detect)

    # Call the task's underlying function directly (not via Celery) —
    # `.run(self, ...)` is how bound-task Celery tasks are invoked
    # synchronously in tests. An explicit ``self`` stub matches the
    # Celery convention.
    result = discovery_task.fingerprint_existing_companies.run(
        limit=10, only_unfingerprinted=True,
    )

    # `/careers` returned a match — the task should NOT have tried
    # /jobs or / (short-circuit on first match).
    assert call_log == ["https://acme.com/careers"], (
        f"Expected single /careers probe but got {call_log}"
    )

    # The primary assertion — careers_url got saved.
    assert company.careers_url == "https://acme.com/careers"
    assert company.careers_url_fetched_at is not None
    assert isinstance(company.careers_url_fetched_at, datetime)

    # Result shape sanity-check.
    assert result["scanned"] == 1
    assert result["new"] == 1  # one new (greenhouse, acme) pair
    assert result["errors"] == 0


def test_fingerprint_task_does_not_write_when_no_match(monkeypatch):
    """When every probe returns ``[]``, ``company.careers_url`` must
    stay NULL. Guards against the bug class where a well-meaning
    future change sets the URL to e.g. the first attempted path even
    on no-match — poisoning the column with URLs that don't actually
    resolve to an ATS.
    """
    from app.workers.tasks import discovery_task

    company = _FakeCompany(website="https://unknown-company.example.com")

    fake_session = _make_fake_session([company])
    monkeypatch.setattr(
        discovery_task, "SyncSession",
        MagicMock(return_value=fake_session),
    )

    # detect_ats_from_url returns [] for every URL — simulates a
    # company whose careers page doesn't embed any known ATS.
    def fake_detect(url, **kwargs):
        return []

    import app.services.ats_fingerprint as ats_mod
    monkeypatch.setattr(ats_mod, "detect_ats_from_url", fake_detect)

    result = discovery_task.fingerprint_existing_companies.run(
        limit=10, only_unfingerprinted=True,
    )

    # The critical assertion — NO write to careers_url.
    assert company.careers_url is None, (
        f"careers_url was set to {company.careers_url!r} despite no ATS match "
        "— this would poison the column with URLs that don't resolve to an ATS"
    )
    assert company.careers_url_fetched_at is None

    # Sanity: the task should have scanned the company without error.
    assert result["scanned"] == 1
    assert result["new"] == 0
    assert result["errors"] == 0


# ── Test 4: migration file structure ───────────────────────────────

def test_migration_adds_and_drops_both_columns():
    """The Phase-A migration must add both columns in ``upgrade()`` and
    drop both in ``downgrade()``. An asymmetric migration leaves the
    DB in a bad state on rollback.

    Reads the migration file as source code rather than running it —
    keeps the test fast and independent of a live Postgres. The
    integration check (actually applying the migration) is done on
    every deploy when ``ci-deploy.sh`` calls ``alembic upgrade head``.
    """
    import pathlib

    migration_path = pathlib.Path(__file__).parent.parent / (
        "alembic/versions/2026_04_17_w3r4s5t6u7v8_add_company_careers_url.py"
    )
    assert migration_path.exists(), f"Migration file missing: {migration_path}"

    content = migration_path.read_text()

    # Upgrade: both columns added
    assert 'add_column(\n        "companies",\n        sa.Column("careers_url"' in content, (
        "Migration upgrade() missing add_column for careers_url"
    )
    assert '"careers_url_fetched_at"' in content and 'DateTime(timezone=True)' in content, (
        "Migration upgrade() missing add_column for careers_url_fetched_at"
    )

    # Downgrade: both columns dropped
    assert 'drop_column("companies", "careers_url_fetched_at")' in content, (
        "Migration downgrade() missing drop_column for careers_url_fetched_at"
    )
    assert 'drop_column("companies", "careers_url")' in content, (
        "Migration downgrade() missing drop_column for careers_url"
    )

    # Revision chain — must reference the prior revision so `alembic
    # upgrade head` includes this file. Checks the literal revision
    # IDs rather than regex-parsing to catch bit-rot where someone
    # renames the migration without updating its references.
    assert 'revision = "w3r4s5t6u7v8"' in content
    assert 'down_revision = "v2q3r4s5t6u7"' in content
