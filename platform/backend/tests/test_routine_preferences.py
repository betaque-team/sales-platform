"""F257 — structural tests for routine preferences + manual queue.

These exercise the new endpoints' DI graph + Pydantic validation
without a live DB. End-to-end coverage (full PATCH cycle, top-to-apply
re-ordering with queued + excluded targets) lives in the
script-mode ``tests/test_api.py`` harness — added when the apply
workflow gets its first full integration smoke.
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
os.environ.setdefault("JWT_SECRET", "pytest-routine-prefs")


def test_routine_router_exposes_new_endpoints():
    """The five new F257 endpoints must register on the routine router.

    Each one is a separate user-facing surface; renaming or losing
    one is a breaking change for the SPA. Locking them by path here
    catches the regression at CI time.
    """
    from app.api.v1.routine import router

    paths_methods: set[tuple[str, str]] = set()
    for r in router.routes:
        for m in getattr(r, "methods", set()) or set():
            if m == "HEAD":
                continue
            paths_methods.add((r.path, m))

    expected = {
        ("/routine/preferences", "GET"),
        ("/routine/preferences", "PUT"),
        ("/routine/queue", "GET"),
        ("/routine/queue/{job_id}", "POST"),
        ("/routine/queue/{job_id}", "DELETE"),
    }
    missing = expected - paths_methods
    assert not missing, (
        f"F257 endpoints missing from routine router: {sorted(missing)}. "
        f"Got: {sorted(paths_methods)}"
    )


def test_routine_preferences_pydantic_defaults_to_empty():
    """A fresh user with empty ``users.routine_preferences`` JSONB
    must round-trip through ``RoutinePreferences()`` cleanly with all
    defaults preserved (no extra-field 422s, no required-field
    failures). Locks the contract that ``{}`` = legacy behaviour."""
    from app.schemas.routine import RoutinePreferences

    p = RoutinePreferences()
    assert p.only_global_remote is False
    assert p.allowed_geographies == []
    assert p.min_relevance_score == 0
    assert p.min_resume_score == 0
    assert p.allowed_role_clusters == []
    assert p.extra_excluded_platforms == []

    # model_validate({}) is the actual JSONB-load path the handler uses.
    p2 = RoutinePreferences.model_validate({})
    assert p2 == p


def test_routine_preferences_rejects_unknown_field():
    """``extra='forbid'`` so a frontend typo on a key 422s instead of
    silently dropping. Mirrors the F157 / F231 pattern across other
    request models."""
    import pytest
    from pydantic import ValidationError

    from app.schemas.routine import RoutinePreferences

    with pytest.raises(ValidationError, match="extra"):
        RoutinePreferences(only_global_remote=True, typoed_field=1)  # type: ignore[call-arg]


def test_routine_preferences_score_bounds():
    """Score floors are clamped to 0-100 — a UI bug that submits 150
    must 422 at parse time rather than silently fail."""
    import pytest
    from pydantic import ValidationError

    from app.schemas.routine import RoutinePreferences

    with pytest.raises(ValidationError, match="100"):
        RoutinePreferences(min_relevance_score=150)
    with pytest.raises(ValidationError, match="100"):
        RoutinePreferences(min_resume_score=120)
    # 0 and 100 are inclusive — pin the boundary.
    RoutinePreferences(min_relevance_score=0, min_resume_score=100)


def test_routine_target_intent_allowlist():
    """The intent enum is a strict allow-list; sending a typo'd
    intent must 422 before reaching the DB so a row can't carry
    a bogus value the picker doesn't know how to handle."""
    import pytest
    from pydantic import ValidationError

    from app.schemas.routine import RoutineTargetCreate

    # Allowed values.
    RoutineTargetCreate(intent="queued")
    RoutineTargetCreate(intent="excluded")
    # Anything else 422s.
    with pytest.raises(ValidationError, match="intent"):
        RoutineTargetCreate(intent="boost")  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="intent"):
        RoutineTargetCreate(intent="QUEUED")  # type: ignore[arg-type]


def test_routine_target_note_capped():
    """``note`` field caps at 500 chars so a runaway input from the
    UI can't overflow the Text column when persisted (defensive,
    matches the F253 oversize-string pattern)."""
    import pytest
    from pydantic import ValidationError

    from app.schemas.routine import RoutineTargetCreate

    RoutineTargetCreate(intent="queued", note="x" * 500)  # OK
    with pytest.raises(ValidationError, match="500"):
        RoutineTargetCreate(intent="queued", note="x" * 501)


def test_top_to_apply_job_carries_is_queued_flag():
    """The ``is_queued`` field must default to False (so a cached
    response from before F257 doesn't break the UI's badge logic)
    and accept True for operator-pinned rows."""
    from uuid import uuid4

    from app.schemas.routine import TopToApplyJob

    j_default = TopToApplyJob(
        job_id=uuid4(),
        title="Senior SRE",
        company_id=None,
        company_name="Acme",
        platform="greenhouse",
        relevance_score=88.0,
        geography_bucket="global_remote",
        role_cluster="infra",
    )
    assert j_default.is_queued is False

    j_pinned = TopToApplyJob(
        job_id=uuid4(),
        title="Senior SRE",
        company_id=None,
        company_name="Acme",
        platform="greenhouse",
        relevance_score=88.0,
        geography_bucket="global_remote",
        role_cluster="infra",
        is_queued=True,
    )
    assert j_pinned.is_queued is True


def test_routine_target_model_intent_constants():
    """The model's intent allow-list constant must mirror the
    Pydantic Literal exactly. A drift between the two would let
    the API accept an intent the model can't store sanely (or
    vice versa)."""
    import typing

    from app.models.routine_target import ROUTINE_TARGET_INTENTS
    from app.schemas.routine import RoutineTargetIntent

    schema_values = set(typing.get_args(RoutineTargetIntent))
    model_values = set(ROUTINE_TARGET_INTENTS)
    assert schema_values == model_values, (
        f"intent constants drift — schema={sorted(schema_values)} "
        f"model={sorted(model_values)}"
    )


def test_user_model_has_routine_preferences_jsonb_column():
    """Lock the column shape: JSONB, NOT NULL, default ``{}``.

    A regression where someone makes the column nullable would let
    Python ``None`` reach the picker's ``_load_user_preferences``
    helper. The helper handles that defensively, but NOT NULL keeps
    the contract clean and the migration's ``server_default`` work."""
    from sqlalchemy.dialects.postgresql import JSONB

    from app.models.user import User

    col = User.__table__.c.routine_preferences
    assert isinstance(col.type, JSONB), (
        f"routine_preferences column type is {type(col.type).__name__}, "
        "expected JSONB."
    )
    assert col.nullable is False, (
        "routine_preferences must be NOT NULL — server default '{}' covers "
        "fresh users; nullable would let None reach the picker silently."
    )


def test_routine_target_table_has_unique_user_job():
    """One row per (user, job) — re-pinning a job updates in place
    rather than stacking duplicates. Locked by the migration's
    UNIQUE constraint; this test guards the index name + columns
    against future model edits that drop it."""
    from app.models.routine_target import RoutineTarget

    constraint_names = {c.name for c in RoutineTarget.__table__.constraints}
    assert "uq_routine_targets_user_job" in constraint_names, (
        f"missing UNIQUE(user_id, job_id) on routine_targets — got "
        f"{sorted(constraint_names)}"
    )
