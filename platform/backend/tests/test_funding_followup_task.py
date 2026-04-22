"""Tests for the funding-followup auto-probe task.

Strategy:

* **Pure helper tests** — the cooldown-filtering decision logic
  lives in ``_pick_candidates`` which takes a plain list of
  company-shaped objects, so we can exercise every branch without
  a database.
* **Registration tests** — verify the Celery task is registered
  under the expected name and that the beat schedule entry
  points at it. These catch the "task written but not wired up"
  regression.

What we deliberately don't test here: the Celery task body end-to-
end (would require either a real Postgres session or heavy
SQLAlchemy mocking). The pure helper covers the only non-trivial
decision logic; the rest of the task is DB plumbing + a passthrough
to ``detect_ats_from_url`` which has its own tests.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest


os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://placeholder:placeholder@localhost:5432/placeholder",
)
os.environ.setdefault(
    "DATABASE_URL_SYNC",
    "postgresql://placeholder:placeholder@localhost:5432/placeholder",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET", "pytest-funding-followup")


# ── Test fixtures ─────────────────────────────────────────────────


@dataclass
class _FakeCompany:
    """Minimal duck-type for what ``_pick_candidates`` reads off a
    Company row. Lets us build test scenarios without dragging in
    the real SQLAlchemy model + session.
    """
    name: str
    careers_url_fetched_at: datetime | None


_NOW = datetime(2026, 4, 22, 12, 0, 0, tzinfo=timezone.utc)


# ── Pure helper: cooldown filtering ───────────────────────────────


def test_pick_candidates_never_probed_passes_through():
    """Cos with ``careers_url_fetched_at = NULL`` have never been
    probed — they always make the cut regardless of the cutoff.
    """
    from app.workers.tasks.funding_followup_task import _pick_candidates

    cos = [_FakeCompany(name="A", careers_url_fetched_at=None),
           _FakeCompany(name="B", careers_url_fetched_at=None)]
    cutoff = _NOW - timedelta(days=7)
    to_probe, skipped = _pick_candidates(cos, cutoff, limit=10)
    assert [c.name for c in to_probe] == ["A", "B"]
    assert skipped == 0


def test_pick_candidates_skips_cos_probed_within_cooldown():
    """A company probed 3 days ago with a 7-day cooldown must be
    skipped. A company probed 8 days ago (older than cutoff) must
    pass through.
    """
    from app.workers.tasks.funding_followup_task import _pick_candidates

    cos = [
        _FakeCompany(name="Recent", careers_url_fetched_at=_NOW - timedelta(days=3)),
        _FakeCompany(name="Stale",  careers_url_fetched_at=_NOW - timedelta(days=8)),
        _FakeCompany(name="Never",  careers_url_fetched_at=None),
    ]
    cutoff = _NOW - timedelta(days=7)  # 7-day cooldown
    to_probe, skipped = _pick_candidates(cos, cutoff, limit=10)
    assert [c.name for c in to_probe] == ["Stale", "Never"]
    assert skipped == 1


def test_pick_candidates_respects_limit_and_preserves_order():
    """Limit caps the output count; ordering comes from the caller's
    query (``ORDER BY funded_at DESC``), so the helper must not
    reshuffle. Newer-funded cos should always win if we cap.
    """
    from app.workers.tasks.funding_followup_task import _pick_candidates

    cos = [_FakeCompany(name=f"co-{i}", careers_url_fetched_at=None) for i in range(10)]
    cutoff = _NOW - timedelta(days=7)
    to_probe, skipped = _pick_candidates(cos, cutoff, limit=3)
    assert len(to_probe) == 3
    assert [c.name for c in to_probe] == ["co-0", "co-1", "co-2"]
    assert skipped == 0


def test_pick_candidates_exact_boundary_condition():
    """A company probed EXACTLY at the cutoff instant is considered
    "still in cooldown" (``>= cutoff``) — skip. Paranoia regression
    guard because `<` vs `<=` bugs on datetime boundaries are a
    classic source of "feature worked in dev but skipped in prod
    because NTP nudged timing by a microsecond" reports.
    """
    from app.workers.tasks.funding_followup_task import _pick_candidates

    cutoff = _NOW - timedelta(days=7)
    cos = [_FakeCompany(name="Edge", careers_url_fetched_at=cutoff)]
    to_probe, skipped = _pick_candidates(cos, cutoff, limit=10)
    assert to_probe == []
    assert skipped == 1


def test_pick_candidates_empty_input():
    """Zero candidates → zero output. Doesn't crash.
    """
    from app.workers.tasks.funding_followup_task import _pick_candidates
    to_probe, skipped = _pick_candidates([], _NOW, limit=10)
    assert to_probe == []
    assert skipped == 0


# ── Celery registration + beat schedule wiring ────────────────────


def test_task_registered_in_celery_registry():
    """Celery discovers tasks by name at runtime. If the task isn't
    registered, a beat tick will silently log "task not found" and
    the auto-probe never runs in prod. Guardrail.
    """
    from app.workers.celery_app import celery_app
    from app.workers.tasks import funding_followup_task  # noqa: F401 — side-effect import
    assert (
        "app.workers.tasks.funding_followup_task.auto_probe_recent_funding"
        in celery_app.tasks
    )


def test_beat_schedule_entry_wired():
    """The aggressive beat schedule must include the funding probe
    entry. Runs Mon + Thu 04:30 UTC (staggered 30 min after the
    weekly AI insights task to avoid collision).
    """
    import os
    # The beat schedule bifurcates on SCAN_MODE. Force aggressive
    # mode for this test so we exercise the branch that prod runs.
    os.environ["SCAN_MODE"] = "aggressive"
    # Re-import inside the test so the module-level `if SCAN_MODE`
    # branch evaluates under the patched env.
    import importlib
    from app.workers import celery_app as ca_mod
    importlib.reload(ca_mod)

    schedule = ca_mod.celery_app.conf.beat_schedule
    assert "funding_followup_probe" in schedule, (
        "funding_followup_probe missing from aggressive beat schedule — "
        "the task would never get auto-invoked in prod"
    )
    entry = schedule["funding_followup_probe"]
    assert entry["task"] == (
        "app.workers.tasks.funding_followup_task.auto_probe_recent_funding"
    )


def test_beat_schedule_entry_also_in_normal_mode():
    """Same assertion for the non-aggressive branch. Catches drift
    where one mode has the entry and the other doesn't — would
    mean cycling SCAN_MODE=normal via env var silently disables
    the whole funding signal pipeline.
    """
    import os, importlib
    os.environ["SCAN_MODE"] = "normal"
    from app.workers import celery_app as ca_mod
    importlib.reload(ca_mod)
    try:
        assert "funding_followup_probe" in ca_mod.celery_app.conf.beat_schedule
    finally:
        # Reset env so other tests (or test ordering) aren't affected.
        os.environ["SCAN_MODE"] = "aggressive"
        importlib.reload(ca_mod)


def test_module_constants_expose_sane_defaults():
    """Defaults that shouldn't silently drift. If someone changes
    the window to 30 days → 3 days in a hotfix, we want the test
    suite to catch the review.
    """
    from app.workers.tasks import funding_followup_task as m
    assert 1 <= m.RECENT_FUNDING_WINDOW_DAYS <= 90
    assert 1 <= m.PROBE_COOLDOWN_DAYS <= 30
    # Cooldown should be strictly shorter than the window — otherwise
    # a co funded exactly at the window edge would never get re-probed
    # before the window kicks it out of the candidate set entirely.
    assert m.PROBE_COOLDOWN_DAYS < m.RECENT_FUNDING_WINDOW_DAYS
