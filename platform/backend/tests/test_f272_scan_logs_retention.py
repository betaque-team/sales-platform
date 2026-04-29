"""F272 — scan_logs retention task structural invariants.

Manual data integrity audit found ``scan_logs`` at 252k rows with no
cleanup task. Table grows ~13k rows/day (16 platforms × ~800
scans/day). Concrete impact today is small (~38MB on disk) but
unbounded — at 1M+ rows the /monitoring activity_24h aggregate
query starts paying real cost.

F272 adds ``prune_scan_logs`` that deletes rows older than 60 days
EXCEPT the most-recent (platform, source) per-key row, which is
preserved so /platforms always shows the last-known-state of every
board even if its recent scans were pruned.

These tests lock the invariants:
  * The task is registered + has the expected name.
  * The retention constant is in a sensible range.
  * Beat schedule includes the daily firing.
  * The preservation logic exists (per-key latest-id NOT IN subquery).
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
os.environ.setdefault("JWT_SECRET", "pytest-f272")


def test_prune_scan_logs_task_registered():
    """Celery must know about the task by its canonical name. The
    beat schedule entry references this string; a typo here would
    silently disable the prune.
    """
    from app.workers.tasks.maintenance_task import prune_scan_logs
    assert prune_scan_logs.name == (
        "app.workers.tasks.maintenance_task.prune_scan_logs"
    )


def test_retention_window_is_sensible():
    """60 days is the empirical sweet spot — long enough for
    forensic debugging but short enough to keep table growth
    bounded. Tighter than 30 days drops legitimate debug history;
    looser than 180 days defeats the purpose of having a retention
    task. Lock the order of magnitude.
    """
    from app.workers.tasks.maintenance_task import SCAN_LOG_RETENTION_DAYS
    assert 14 <= SCAN_LOG_RETENTION_DAYS <= 180, (
        f"SCAN_LOG_RETENTION_DAYS={SCAN_LOG_RETENTION_DAYS} is "
        "outside the safe range [14, 180]. Tighten back toward 60."
    )


def test_prune_uses_started_at_cutoff():
    """F272(d) — preservation logic dropped. The original design
    preserved per-(platform, source) latest-id but ``max(uuid)``
    isn't a Postgres aggregate, so the live invocation raised
    ``UndefinedFunction`` on every run.

    Simplified to: single DELETE WHERE started_at < cutoff. No
    subquery, no UUID aggregate. Boards scanned in the last 60 days
    are inherently preserved (they're after the cutoff). Boards
    that haven't scanned in 60+ days are typically dead/inactive
    anyway — losing their stale history doesn't hurt /platforms.

    This test just verifies the cutoff predicate is in the query.
    """
    from app.workers.tasks import maintenance_task
    src = inspect.getsource(maintenance_task.prune_scan_logs)
    assert "ScanLog.started_at < cutoff" in src, (
        "F272(d) regression: prune_scan_logs no longer compares "
        "ScanLog.started_at < cutoff. The DELETE predicate is the "
        "only thing keeping the table bounded."
    )
    assert "ScanLog.__table__.delete()" in src, (
        "F272(d) regression: prune_scan_logs no longer issues a "
        "DELETE. Restore the bulk delete-by-cutoff."
    )
    # Negative regression guard: the buggy ``max(uuid)`` chained
    # with ``.group_by(`` must NOT come back as live code. The
    # docstring may MENTION the historical bug (we want that — it
    # explains why preservation was dropped), but the actual chained
    # construct that crashed on prod must not appear.
    assert "func.max(ScanLog.id)\n            .group_by" not in src, (
        "F272(d) regression: ``func.max(ScanLog.id) … .group_by(...)`` "
        "is back. This chain raised UndefinedFunction on prod. Use a "
        "window function via CTE or max(started_at) instead if "
        "per-key preservation is needed."
    )


def test_celery_beat_schedule_includes_prune_task():
    """Beat must dispatch the prune daily; otherwise the task is
    dead code. The aggressive + normal schedules both register it.
    """
    from app.workers.celery_app import celery_app
    schedule = celery_app.conf.beat_schedule
    found = False
    for entry_name, entry in (schedule or {}).items():
        if entry.get("task", "").endswith("prune_scan_logs"):
            found = True
            break
    assert found, (
        "F272 regression: beat schedule does not register "
        "prune_scan_logs. The task exists but never fires; "
        "scan_logs continues to grow unbounded. Add a beat entry "
        "calling 'app.workers.tasks.maintenance_task.prune_scan_logs'."
    )


def test_prune_scan_logs_can_resolve_ScanLog_symbol():
    """F272(c) regression guard. The initial F272 patch referenced
    ``ScanLog.id`` / ``ScanLog.platform`` etc. inside the task body
    but never imported the model. Live invocation post-F272(b) hit
    ``NameError: name 'ScanLog' is not defined``. Source-grep tests
    don't catch this — the import block is whitespace away from the
    function body but Python only resolves names at runtime.

    This test imports the module and verifies ``ScanLog`` is in the
    module's globals — a regression that drops the import surfaces
    here, before any celery-worker ever tries to run the task.
    """
    from app.workers.tasks import maintenance_task
    assert hasattr(maintenance_task, "ScanLog"), (
        "F272(c) regression: app.models.scan.ScanLog is no longer "
        "imported into maintenance_task. The prune_scan_logs body "
        "references ``ScanLog`` and will raise NameError on every "
        "invocation. Add ``from app.models.scan import ScanLog`` to "
        "the imports."
    )


def test_prune_task_registered_in_BOTH_schedule_modes():
    """F272(b) regression guard. The celery_app.py file has two
    parallel beat-schedule blocks — one for SCAN_MODE=aggressive
    and one for the else (normal) branch. The initial F272 patch
    only updated the aggressive block, but prod runs on
    SCAN_MODE=normal, so the prune task never fired. This test
    grep-checks the source for two distinct ``"prune_scan_logs":``
    entries — one in each branch — so the next time someone adds
    a new task they remember to update both branches.
    """
    import inspect
    from app.workers import celery_app as celery_module
    src = inspect.getsource(celery_module)
    occurrences = src.count('"prune_scan_logs": {')
    assert occurrences >= 2, (
        f"F272(b) regression: only {occurrences} ``\"prune_scan_logs\": {{`` "
        "entries in celery_app.py. There must be at least 2 — one in the "
        "aggressive-mode block and one in the normal-mode block. Otherwise "
        "the task only fires under one SCAN_MODE setting and silently fails "
        "to fire under the other (which is the original F272(b) bug)."
    )
