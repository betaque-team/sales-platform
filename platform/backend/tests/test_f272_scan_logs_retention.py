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


def test_prune_preserves_per_key_latest():
    """Source-grep — the function MUST query per-(platform, source)
    max ids and exclude them from the delete. Without preservation,
    a board that hasn't been scanned in 61 days would have all its
    history wiped and /platforms would show "no scans ever" instead
    of "last scan was 65 days ago".
    """
    from app.workers.tasks import maintenance_task
    src = inspect.getsource(maintenance_task.prune_scan_logs)
    assert "func.max(ScanLog.id)" in src or "max(ScanLog.id)" in src, (
        "F272 regression: prune_scan_logs no longer queries the "
        "per-key max id. The preservation guard is gone — a 61+ day "
        "stale board would have its entire history wiped."
    )
    assert "group_by(ScanLog.platform, ScanLog.source)" in src, (
        "F272 regression: per-key grouping dropped. Without the "
        "(platform, source) GROUP BY, preservation degrades to "
        "'most recent overall' which is wrong."
    )
    # The NOT IN exclusion must be present.
    assert "~ScanLog.id.in_" in src, (
        "F272 regression: NOT IN exclusion dropped. The preserved "
        "latest-id rows must be excluded from the DELETE."
    )


def test_prune_handles_empty_table():
    """Edge case: first run on a fresh DB. The empty-set branch
    must handle ``latest_ids_set`` being empty without hitting an
    empty-IN-clause SQLAlchemy oddity.
    """
    from app.workers.tasks import maintenance_task
    src = inspect.getsource(maintenance_task.prune_scan_logs)
    assert "if latest_ids_set:" in src, (
        "F272 regression: empty-set guard removed. An empty "
        "ScanLog table would hit ``~ScanLog.id.in_(set())`` which "
        "SQLAlchemy treats unpredictably across versions."
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
