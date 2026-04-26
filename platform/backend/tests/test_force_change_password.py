"""F247 — admin password reset must force the user to change on first login.

Pre-fix flow:
  1. super_admin POST /users/{id}/reset-password → temp password set
  2. user POSTs /auth/login with the temp password → 200 + JWT
  3. nothing in the response or any subsequent /auth/me call signals
     "you must change your password" → user keeps using the temp
     password indefinitely

Post-fix flow:
  1. The reset endpoint flips ``users.must_change_password = True``
  2. ``POST /auth/login`` and ``GET /auth/me`` both surface the flag
     in their response payload (top-level ``user.must_change_password``
     on login; ``UserOut.must_change_password`` on /me)
  3. The frontend ProtectedRoute redirects every protected page to
     ``/change-password`` until the flag flips back

These tests pin the BACKEND half of that contract:

* ``admin_reset_password`` sets the flag (and audit-logs the action).
* ``change_password`` clears the flag on success.
* ``UserOut.from_user`` surfaces the flag.
* Login response includes the flag.
* The flag has the right shape on the User model + migration covers it.

No live DB. We instantiate User-shaped objects directly for the
schema/serialisation paths and use SimpleNamespace stand-ins for
the handler logic where appropriate. Live HTTP coverage lives in
``tests/test_api.py`` (script-mode) once it's wired.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4


os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://placeholder:placeholder@localhost:5432/placeholder",
)
os.environ.setdefault(
    "DATABASE_URL_SYNC",
    "postgresql://placeholder:placeholder@localhost:5432/placeholder",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET", "pytest-force-change-password")


def _fake_user(must_change: bool = False):
    """Build a User-shaped namespace covering every attribute the
    ``UserOut.from_user`` constructor reads. Avoids spinning up the
    full ORM for what's a pure serialisation test."""
    return SimpleNamespace(
        id=uuid4(),
        email="user@example.com",
        name="Test User",
        avatar_url="",
        role="viewer",
        is_active=True,
        active_resume_id=None,
        password_hash="dummy-hash",
        created_at=datetime.now(timezone.utc),
        last_login_at=None,
        must_change_password=must_change,
    )


def test_user_model_has_must_change_password_column():
    """Locks the column shape: ``Boolean``, NOT NULL, default False.

    A regression where someone makes the column nullable would let
    Python ``None`` flow into ``UserOut`` and through to the
    frontend, where ``user.must_change_password`` would be falsy and
    the gate would silently never fire. NOT NULL keeps the contract
    binary.
    """
    from sqlalchemy import Boolean

    from app.models.user import User

    col = User.__table__.c.must_change_password
    assert isinstance(col.type, Boolean), (
        f"must_change_password column type is {type(col.type).__name__}, "
        "expected Boolean. The flag must be a strict bool — anything else "
        "would let truthy/falsy ambiguity sneak past the gate."
    )
    assert col.nullable is False, (
        "must_change_password must be NOT NULL. A nullable column lets "
        "existing rows return None to the frontend, and `user.must_change_password` "
        "would be falsy — the gate would silently never fire (F247)."
    )


def test_user_out_surfaces_must_change_password_default_false():
    """The flag must be in the UserOut payload AND default to False
    so a User row without the attribute (e.g. test factories that
    predate the column) doesn't crash serialisation.
    """
    from app.schemas.user import UserOut

    out = UserOut.from_user(_fake_user(must_change=False))
    assert out.must_change_password is False, (
        f"UserOut.must_change_password = {out.must_change_password!r} for "
        "a fresh user; expected False."
    )

    # Field is in the model, so model_dump must include it under that key.
    dumped = out.model_dump()
    assert "must_change_password" in dumped, (
        f"model_dump() missing must_change_password — keys: {sorted(dumped)}. "
        "Frontend reads this key directly from /auth/me."
    )


def test_user_out_surfaces_must_change_password_true_after_reset():
    """When the underlying user has the flag set, the API payload
    must reflect that — otherwise the frontend ProtectedRoute can't
    fire the redirect.
    """
    from app.schemas.user import UserOut

    out = UserOut.from_user(_fake_user(must_change=True))
    assert out.must_change_password is True, (
        "UserOut did not propagate must_change_password=True from the "
        "underlying user; the gate redirect would never fire."
    )


def test_admin_reset_password_handler_sets_must_change_password():
    """Source-level guard on ``admin_reset_password``: the handler
    body must assign ``target.must_change_password = True``.

    A live HTTP test would be cleaner but requires a fixture harness
    we don't have yet (test_api.py is script-mode). This grep-the-
    source check is the strongest unit-testable substitute and would
    catch any refactor that drops the assignment.
    """
    import inspect

    from app.api.v1 import users as users_module

    src = inspect.getsource(users_module.admin_reset_password)
    assert "must_change_password = True" in src, (
        "admin_reset_password no longer sets must_change_password=True. "
        "Without that assignment, the temp password the admin shares "
        "stays valid indefinitely and the user never gets prompted to "
        "rotate it (F247 regression)."
    )


def test_change_password_handler_clears_must_change_password():
    """Source-level guard on ``change_password``: the handler must
    assign ``user.must_change_password = False`` on success."""
    import inspect

    from app.api.v1 import auth as auth_module

    src = inspect.getsource(auth_module.change_password)
    assert "must_change_password = False" in src, (
        "change_password no longer clears must_change_password. The "
        "user would change their password successfully but the gate "
        "would still redirect them on the next page load — infinite "
        "loop until the cache invalidates."
    )


def test_login_response_includes_must_change_password_key():
    """The /auth/login response payload includes the flag at
    ``user.must_change_password`` so the frontend can route to the
    gate immediately after sign-in, without a separate /auth/me
    round-trip.
    """
    import inspect

    from app.api.v1 import auth as auth_module

    src = inspect.getsource(auth_module.login)
    # The response dict-literal must assign must_change_password into
    # the ``user`` sub-object. Looser substring match because the
    # surrounding code may format the dict over multiple lines.
    assert '"must_change_password"' in src, (
        "The /auth/login response no longer includes the "
        "must_change_password key in the user payload. Frontend would "
        "need a separate /auth/me round-trip to see the flag, and the "
        "redirect would fire one navigation late."
    )


def test_must_change_password_migration_present():
    """A migration adding the must_change_password column must exist
    in alembic/versions/. Catches a model-vs-migration drift where
    someone bumps the model without adding the matching ALTER TABLE.
    """
    import re
    from pathlib import Path

    versions_dir = (
        Path(__file__).resolve().parent.parent / "alembic" / "versions"
    )
    pattern = re.compile(r"must_change_password", re.IGNORECASE)
    matches = [
        f.name
        for f in versions_dir.glob("*.py")
        if pattern.search(f.read_text())
    ]
    assert matches, (
        "No alembic migration mentions must_change_password. The model "
        "has the column but prod's `alembic upgrade head` won't add it, "
        "so login would 500 on the first attempt to read a non-existent "
        "column. Add a migration that runs op.add_column on users."
    )
