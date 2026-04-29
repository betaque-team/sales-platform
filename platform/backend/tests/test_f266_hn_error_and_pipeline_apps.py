"""F266 — HN scan error_message propagation + Pipeline applications_count.

Manual sweep findings (post-F264) surfaced two real but small issues:

  1. HN fetcher logged ``errors=2`` every nightly run but
     ``ScanLog.error_message`` was empty — admins on /monitoring
     /scan-errors saw a count without any hint of cause. Root cause
     was the per-job exception handler in scan_task incrementing
     ``stats["errors"]`` but never touching ``stats["error_message"]``.
     Fix: capture the FIRST per-job error (with external_id prefix)
     into the message so the count has a string companion.

  2. ``/pipeline`` audit found 19/23 cards had zero applications
     under them when drilled-down. Pre-fix the kanban surfaced no
     signal of which cards had apply activity vs were research-only
     /stalled-after-accept. Fix: emit ``applications_count`` on each
     ``PipelineItemOut`` (live count via the F261 denormalised
     ``Application.company_id`` column) so the frontend can render
     a count badge + gate the "Apps" drill-down button.

These tests lock both invariants without needing a live DB —
structural / source-grep / schema-shape only.
"""
from __future__ import annotations

import inspect
import os

# Minimum env so app.config imports cleanly.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://placeholder:placeholder@localhost:5432/placeholder",
)
os.environ.setdefault(
    "DATABASE_URL_SYNC",
    "postgresql://placeholder:placeholder@localhost:5432/placeholder",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET", "pytest-f266")


# ── HN error_message propagation ──────────────────────────────────


def test_per_job_exception_populates_stats_error_message():
    """The per-job upsert exception handler in ``scan_task`` must
    write the error message to ``stats["error_message"]`` so
    ``ScanLog.error_message`` is non-empty when ``errors > 0``.

    Pre-fix, the only signal admins had on /monitoring/scan-errors
    was a numeric count — they couldn't tell whether the HN scanner
    was failing on the same 2 comments every day or on different
    comments. Post-fix, the first per-job error's message lands in
    ``stats["error_message"]`` so the count has a debuggable
    companion.
    """
    import app.workers.tasks.scan_task as scan_module

    # Find the per-job exception handler — distinguished by the
    # logger.error("Error upserting job ...") line that's adjacent
    # to ``stats["errors"] += 1``.
    src = inspect.getsource(scan_module)
    needle = 'Error upserting job'
    pos = src.find(needle)
    assert pos > 0, "Could not locate per-job exception handler in scan_task"
    # Look at the next ~600 chars after the marker for the assignment.
    window = src[pos:pos + 600]
    assert "stats[\"errors\"] += 1" in window, (
        "Per-job handler no longer increments stats['errors']; check "
        "the scan_task fix is still in place."
    )
    assert "stats[\"error_message\"]" in window, (
        "F266 regression: per-job exception handler in scan_task no "
        "longer writes to stats['error_message']. ScanLog rows will "
        "go back to errors>0 with empty message — admins on "
        "/monitoring/scan-errors will see a count with no hint of "
        "cause. Restore the assignment that captures the FIRST "
        "per-job error message into stats['error_message']."
    )


# ── Pipeline applications_count surfacing ─────────────────────────


def test_pipeline_item_out_has_applications_count_field():
    """The schema must declare the field. Removing it would cause
    Pydantic to silently drop the value when serialising, and the
    frontend's count badge would never render.
    """
    from app.schemas.pipeline import PipelineItemOut

    fields = PipelineItemOut.model_fields
    assert "applications_count" in fields, (
        "F266 regression: PipelineItemOut.applications_count is "
        "missing. The frontend kanban card relies on this field "
        "to render the per-card 'N apps' badge + gate the Apps "
        "drill-down button."
    )
    # Default 0 — keeps backwards compatibility for callers that
    # don't populate the field (e.g. legacy fixtures, mock helpers).
    assert fields["applications_count"].default == 0, (
        "applications_count must default to 0 so legacy / partial "
        "responses don't crash the frontend's renderer."
    )


def test_pipeline_get_endpoint_populates_applications_count():
    """The list endpoint (``GET /pipeline``) must run the per-card
    apps count query and write the result into the response payload.
    Source-grep ensures the helper map (``apps_map``) and the
    payload assignment (``d["applications_count"] = ...``) are both
    present. A regression that drops either makes the field stuck
    at 0 across every card.
    """
    import app.api.v1.pipeline as pipeline_module
    src = inspect.getsource(pipeline_module.get_pipeline)
    assert "apps_map" in src, (
        "F266 regression: get_pipeline no longer builds an apps_map. "
        "Restore the COUNT(*) GROUP BY company_id query against "
        "Application.company_id."
    )
    assert 'applications_count' in src, (
        "F266 regression: get_pipeline no longer assigns "
        "applications_count into the response payload. The badge "
        "won't render."
    )


def test_pipeline_get_client_endpoint_populates_applications_count():
    """The detail endpoint must be in lockstep with the list
    endpoint — both render to the same card on the frontend, so
    drift between them shows up as a badge that flickers when the
    user drills in / out.
    """
    import app.api.v1.pipeline as pipeline_module
    src = inspect.getsource(pipeline_module.get_client)
    assert "applications_count" in src, (
        "F266 regression: get_client (detail endpoint) no longer "
        "populates applications_count. List + detail will disagree."
    )
