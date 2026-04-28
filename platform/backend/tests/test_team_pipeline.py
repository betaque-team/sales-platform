"""Structural tests for F261 — Team Pipeline Tracker.

No live DB. We assert the invariants that determine whether the
feature is safe to ship:

  1. ``GET /applications/team`` and ``PATCH /applications/{id}/stage``
     are admin-gated. A regression where someone replaced the
     ``_TEAM_PIPELINE_GUARD`` dependency with ``get_current_user``
     would let any logged-in viewer/reviewer pull other users'
     resume labels + applicant emails.

  2. ``GET /pipeline/{id}/applications`` is admin-gated for the same
     reason — the drill-down panel surfaces the same applicant
     identity columns.

  3. The Application model exposes ``company_id`` + ``stage_key``
     attributes. Migration drift (column added but model not updated,
     or vice-versa) shows up here as an AttributeError.

  4. ``ApplicationStageUpdate`` rejects unknown fields (Pydantic
     ``extra="forbid"``) so a typo like ``{"stage": "..."}`` (missing
     ``_key``) 422s instead of silently no-op-ing.

End-to-end HTTP + DB coverage runs from the live integration harness.
"""
from __future__ import annotations

import inspect
import os

import pytest


# Minimum env so app.config imports cleanly. Mirrors the other test
# modules in this directory.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://placeholder:placeholder@localhost:5432/placeholder",
)
os.environ.setdefault(
    "DATABASE_URL_SYNC",
    "postgresql://placeholder:placeholder@localhost:5432/placeholder",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET", "pytest-team-pipeline")


# ── Application model: new columns are present ────────────────────


def test_application_model_has_company_id_and_stage_key():
    """The migration adds ``applications.company_id`` and
    ``applications.stage_key``; the model should mirror that. If the
    model is out of sync the team-feed endpoint will 500 on attribute
    access at the join layer.
    """
    from app.models.application import Application

    cols = {c.name for c in Application.__table__.columns}
    assert "company_id" in cols, (
        "Application.company_id is missing — migration "
        "d0e1f2g3h4i5 added the column but the model wasn't updated."
    )
    assert "stage_key" in cols, (
        "Application.stage_key is missing — migration "
        "d0e1f2g3h4i5 added the column but the model wasn't updated."
    )


# ── RBAC invariant: team-pipeline routes are admin-gated ──────────


def _route_deps_match(route, marker_substrings: tuple[str, ...]) -> bool:
    """Walk the FastAPI ``dependant`` graph for a route and return
    True iff the source of any callable in the closure matches one of
    the markers. Mirrors the helper in test_profile_docs_vault.py — we
    grep for the role-guard implementation rather than importing it
    directly so a rename of ``require_role`` doesn't quietly break
    every gated route's protection.
    """
    dependant = getattr(route, "dependant", None)
    if dependant is None:
        return False
    callables: list = []

    def _walk(dep):
        callables.append(dep.call)
        for sub in dep.dependencies:
            _walk(sub)

    for d in dependant.dependencies:
        _walk(d)

    for fn in callables:
        try:
            src = inspect.getsource(fn)
        except (OSError, TypeError):
            continue
        for marker in marker_substrings:
            if marker in src:
                return True
    return False


def test_applications_team_is_admin_gated():
    """``GET /applications/team`` must run through ``require_role(
    "admin")``. A regression here exposes every applicant's email +
    resume label to any logged-in viewer, including third-party
    contractors with viewer accounts.
    """
    from app.api.v1 import applications

    route = next(
        (
            r
            for r in applications.router.routes
            if getattr(r, "path", None) == "/applications/team"
            and "GET" in getattr(r, "methods", set())
        ),
        None,
    )
    assert route is not None, (
        "Route GET /applications/team not registered — F261 endpoint missing."
    )
    assert _route_deps_match(
        route, ("Insufficient privileges", "ROLE_HIERARCHY")
    ), (
        "GET /applications/team is not admin-gated. Wire `_TEAM_PIPELINE_GUARD"
        " = require_role('admin')` on the endpoint."
    )


def test_application_stage_patch_is_admin_gated():
    """The stage-edit endpoint moves applications through the
    configurable funnel. Allowing a viewer to PATCH would let a
    revoked contractor mark their own application as "Offer
    extended" without an admin's knowledge.
    """
    from app.api.v1 import applications

    route = next(
        (
            r
            for r in applications.router.routes
            if getattr(r, "path", None) == "/applications/{app_id}/stage"
            and "PATCH" in getattr(r, "methods", set())
        ),
        None,
    )
    assert route is not None, (
        "Route PATCH /applications/{app_id}/stage not registered."
    )
    assert _route_deps_match(
        route, ("Insufficient privileges", "ROLE_HIERARCHY")
    ), (
        "PATCH /applications/{id}/stage is not admin-gated. Restore the"
        " require_role('admin') dependency."
    )


def test_pipeline_drilldown_is_admin_gated():
    """``GET /pipeline/{client_id}/applications`` exposes applicant
    identity to whoever can call it; must stay admin-only.
    """
    from app.api.v1 import pipeline

    route = next(
        (
            r
            for r in pipeline.router.routes
            if getattr(r, "path", None) == "/pipeline/{client_id}/applications"
            and "GET" in getattr(r, "methods", set())
        ),
        None,
    )
    assert route is not None, (
        "Route GET /pipeline/{client_id}/applications not registered."
    )
    assert _route_deps_match(
        route, ("Insufficient privileges", "ROLE_HIERARCHY")
    ), "GET /pipeline/{client_id}/applications is not admin-gated."


# ── Schema: stage update rejects unknown fields ───────────────────


def test_application_stage_update_forbids_unknown_fields():
    """Body schema uses ``extra='forbid'`` so a client sending
    ``{"stage": "interview_1"}`` (missing the ``_key`` suffix) gets a
    422 instead of being silently no-op-ed. Same regression class as
    F194 (PATCH /applications dropped status writes when a typo
    matched no documented field).
    """
    from app.api.v1.applications import ApplicationStageUpdate
    from pydantic import ValidationError

    # Valid payload parses cleanly.
    ok = ApplicationStageUpdate(stage_key="interview_1", note="moved to round 1")
    assert ok.stage_key == "interview_1"
    assert ok.note == "moved to round 1"

    # Null clears the stage — explicitly supported.
    cleared = ApplicationStageUpdate(stage_key=None)
    assert cleared.stage_key is None

    # Unknown field rejected.
    with pytest.raises(ValidationError):
        ApplicationStageUpdate(stage="interview_1")  # missing _key suffix

    # Note exceeding 500 chars rejected.
    with pytest.raises(ValidationError):
        ApplicationStageUpdate(stage_key=None, note="x" * 501)
