"""F268 — extra="forbid" on admin-mutation schemas.

Manual sweep finding: ``PATCH /role-clusters/{id}`` accepted
``{"foo_bar": "x"}`` and returned 200, silently dropping the unknown
field. Same pattern existed across 12+ admin / mutation schemas:
typos in admin payloads were no-op-ed without surfacing as 422.

This is the same regression class as F194 (PATCH /applications
silent-drop of unknown fields, fixed via ``extra="forbid"`` on
``ApplicationUpdate``). F268 sweeps the policy across the
high-leverage admin surfaces:

  * RoleClusterCreate / RoleClusterUpdate (api/v1/role_config.py)
  * AnswerUpdate (schemas/answer_book.py)
  * PipelineUpdate (schemas/pipeline.py)
  * PipelineCreateRequest / StageCreate / StageUpdate (api/v1/pipeline.py)
  * JobStatusUpdate (schemas/job.py — bulk-action target)
  * UserUpdate / UserCreate / ChangePassword / ResetPassword (schemas/user.py)

These tests lock the policy. A regression that drops ``extra=
"forbid"`` from any of these schemas reopens the silent-drop bug
for that surface.
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
os.environ.setdefault("JWT_SECRET", "pytest-f268")


import pytest
from pydantic import ValidationError


def _assert_forbids_extra(model_cls, valid_payload: dict, marker: str):
    """Helper: a model with ``extra="forbid"`` should reject an
    unknown key. ``valid_payload`` is a known-good payload that
    parses cleanly; we then add ``__f268_unknown_field__`` and
    expect a ValidationError.
    """
    # Sanity: valid payload parses.
    model_cls(**valid_payload)
    # Now add an unknown field — should raise.
    bad = dict(valid_payload)
    bad["__f268_unknown_field__"] = "should be rejected"
    with pytest.raises(ValidationError) as exc_info:
        model_cls(**bad)
    err = str(exc_info.value)
    assert "extra" in err.lower() or "forbidden" in err.lower() or "not permitted" in err.lower(), (
        f"{marker}: ValidationError raised but message doesn't mention "
        f"forbidden/extra: {err[:200]}"
    )


def test_role_cluster_create_forbids_extra():
    from app.api.v1.role_config import RoleClusterCreate
    _assert_forbids_extra(
        RoleClusterCreate,
        {"name": "x", "display_name": "X cluster"},
        "RoleClusterCreate",
    )


def test_role_cluster_update_forbids_extra():
    from app.api.v1.role_config import RoleClusterUpdate
    _assert_forbids_extra(
        RoleClusterUpdate,
        {"display_name": "renamed"},
        "RoleClusterUpdate",
    )


def test_answer_update_forbids_extra():
    from app.schemas.answer_book import AnswerUpdate
    _assert_forbids_extra(
        AnswerUpdate,
        {"answer": "yes"},
        "AnswerUpdate",
    )


def test_pipeline_update_forbids_extra():
    from app.schemas.pipeline import PipelineUpdate
    _assert_forbids_extra(
        PipelineUpdate,
        {"stage": "researching"},
        "PipelineUpdate",
    )


def test_pipeline_create_request_forbids_extra():
    from app.api.v1.pipeline import PipelineCreateRequest
    import uuid
    _assert_forbids_extra(
        PipelineCreateRequest,
        {"company_id": str(uuid.uuid4())},
        "PipelineCreateRequest",
    )


def test_stage_create_forbids_extra():
    from app.api.v1.pipeline import StageCreate
    _assert_forbids_extra(
        StageCreate,
        {"key": "k1", "label": "L1"},
        "StageCreate",
    )


def test_stage_update_forbids_extra():
    from app.api.v1.pipeline import StageUpdate
    _assert_forbids_extra(
        StageUpdate,
        {"label": "renamed"},
        "StageUpdate",
    )


def test_job_status_update_forbids_extra():
    from app.schemas.job import JobStatusUpdate
    _assert_forbids_extra(
        JobStatusUpdate,
        {"status": "accepted"},
        "JobStatusUpdate",
    )


def test_user_update_forbids_extra():
    from app.schemas.user import UserUpdate
    _assert_forbids_extra(
        UserUpdate,
        {"role": "admin"},
        "UserUpdate",
    )


def test_user_create_forbids_extra():
    from app.schemas.user import UserCreate
    _assert_forbids_extra(
        UserCreate,
        {"email": "x@y.com", "name": "X", "password": "abcdefghij"},
        "UserCreate",
    )


def test_change_password_forbids_extra():
    from app.schemas.user import ChangePassword
    _assert_forbids_extra(
        ChangePassword,
        {"current_password": "old", "new_password": "newer123"},
        "ChangePassword",
    )
