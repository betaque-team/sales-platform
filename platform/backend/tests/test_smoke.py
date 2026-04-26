"""Cheap, no-IO smoke tests that run under pytest in CI.

Purpose: pytest's default behavior is to return exit code 5 ("no tests
collected") when the suite is empty, which fails the ``ci.yml`` backend
job. The live-integration harness in ``test_api.py`` is skipped via
``conftest.collect_ignore_glob``. Without this file, the test run would
collect zero items and the job would fail even when everything is
healthy.

The tests here are deliberately boring:

* **Import smokes** — boot the FastAPI app and the Celery worker module
  under the same env var scaffolding CI uses, so a missing import / typo
  / pydantic validation error is caught at pytest time rather than at
  deploy time.
* **SecretStr masking** — guards the Anthropic-key leak defense
  (``config.anthropic_api_key: SecretStr``). If someone reverts to
  plain ``str`` in a future cleanup, this test fails loudly.
* **Log scrubber** — the defense-in-depth filter in
  ``app.utils.log_scrub`` needs a regression test, because its failure
  mode is silent (the secret just shows up in logs). Patterns are
  kept in sync with ``scripts/check-forbidden-strings.sh``; this test
  exercises the two most important ones.

These are kept in one file to keep the test graph flat — adding a
proper unit-test tree is a separate ask.
"""
from __future__ import annotations

import logging
import os

import pytest


# CI sets DATABASE_URL etc. in env. For local runs via `pytest` without
# those, supply placeholders so `get_settings()` doesn't blow up at
# import. Real DB / Redis aren't needed — we only exercise import-time
# behavior.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://placeholder:placeholder@localhost:5432/placeholder",
)
os.environ.setdefault(
    "DATABASE_URL_SYNC",
    "postgresql://placeholder:placeholder@localhost:5432/placeholder",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET", "pytest-smoke-secret")


def test_fastapi_app_imports() -> None:
    """``app.main.app`` boots without raising.

    Mirrors the ``Backend import smoke test`` step in
    ``.github/workflows/deploy.yml`` — if every router, model, and
    pydantic schema imports cleanly, this passes. Catches broken
    import chains, stale model metadata, alembic-vs-model drift that
    trips at ``Base.metadata`` registration, and missing env defaults.
    """
    from app.main import app

    assert app.title, "FastAPI app has no title — schema broke"


def test_openapi_docs_redoc_all_under_api_prefix() -> None:
    """F242(c) regression — every doc-related URL must sit under the
    ``/api`` prefix that nginx proxies to the backend.

    Pre-fix, ``docs_url`` and ``redoc_url`` were prefixed but
    ``openapi_url`` defaulted to ``/openapi.json``. Prod nginx routes
    ``/api/*`` to the backend; ``/openapi.json`` (no prefix) fell
    through to the React SPA, so Swagger UI loaded the HTML shell and
    then failed to fetch the JSON spec. Aligning all three under one
    prefix means Swagger / ReDoc / third-party OpenAPI consumers all
    work without an nginx-config change.
    """
    from app.main import app

    assert app.docs_url == "/api/docs", (
        f"docs_url drifted to {app.docs_url!r} — Swagger UI mount path "
        "must stay under /api so nginx proxies it to the backend."
    )
    assert app.redoc_url == "/api/redoc", (
        f"redoc_url drifted to {app.redoc_url!r} — ReDoc mount path "
        "must stay under /api for the same reason."
    )
    assert app.openapi_url == "/api/openapi.json", (
        f"openapi_url is {app.openapi_url!r}; Swagger UI's HTML shell "
        "loads but the spec fetch falls through to the React SPA in prod "
        "(F242(c) regression). Keep this aligned with docs_url's prefix."
    )


def test_celery_worker_imports() -> None:
    """Celery bootstrap doesn't raise.

    Separate from the FastAPI import because Celery has its own set
    of task-discovery paths. A broken ``celery_app.py`` wouldn't be
    caught by the FastAPI smoke alone.
    """
    from app.workers.celery_app import celery_app  # noqa: F401


def test_anthropic_api_key_is_secret_str() -> None:
    """Regression guard on the leak-defense layer.

    Pydantic's ``SecretStr`` is what keeps ``str(settings)`` /
    ``model_dump()`` from dumping the raw key in a future debug
    endpoint or logged exception. If someone converts the field back
    to plain ``str``, the mask disappears silently — this test fails
    loudly instead.

    Verifies three invariants:

    * ``repr`` doesn't leak — must render as ``SecretStr('**********')``.
    * ``str`` is the masked form, not the raw value.
    * ``.get_secret_value()`` still returns the raw value so call sites
      that pass the key to the Anthropic SDK keep working.
    """
    from pydantic import SecretStr
    from app.config import Settings

    # Instantiate with an explicit non-empty value so repr/str have
    # something to mask. Using `_env_file=None` to skip .env file
    # loading — we're asserting on the class contract, not what
    # env defines.
    s = Settings(anthropic_api_key="sk-ant-api03-REGRESSIONSENTINEL000000")
    assert isinstance(s.anthropic_api_key, SecretStr), (
        "anthropic_api_key must be SecretStr for leak defense"
    )
    assert "REGRESSION" not in repr(s), (
        f"SecretStr leaked in repr: {repr(s)!r}"
    )
    assert "REGRESSION" not in str(s.anthropic_api_key), (
        f"SecretStr leaked in str: {str(s.anthropic_api_key)!r}"
    )
    assert s.anthropic_api_key.get_secret_value() == (
        "sk-ant-api03-REGRESSIONSENTINEL000000"
    ), "get_secret_value() must return the raw value"


@pytest.mark.parametrize(
    "raw, should_redact",
    [
        ("sk-ant-api03-TESTVALUE000000000000000", True),
        ("sk-ant-admin01-ANOTHERLONGVALUE000001", True),
        ("ghp_abcdefghijklmnopqrstuvwxyz0123456789", True),
        ("AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ0123456", True),
        # Short / shaped-wrong values do NOT match — the regex floors
        # are intentional to avoid false positives on UUIDs etc.
        ("sk-ant-short", False),
        ("plain log with no secrets", False),
    ],
)
def test_log_scrubber_redacts_known_patterns(raw: str, should_redact: bool) -> None:
    """Verify the secret-scrub filter redacts known credential shapes.

    Uses a per-test ``StringIO`` + ``StreamHandler`` (rather than
    pytest's ``caplog``) because caplog attaches to the root logger's
    handler chain, and our filter lives on a named leaf logger with
    ``propagate=False`` — caplog would never see the record. Reading
    a custom handler's buffer matches what a real prod handler does.
    """
    import io

    from app.utils.log_scrub import SecretScrubFilter

    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(logging.Formatter("%(message)s"))

    logger = logging.getLogger(f"test_scrub_{should_redact}_{len(raw)}")
    logger.handlers = [handler]
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    logger.addFilter(SecretScrubFilter())

    # Emit via %-interpolation so the filter exercises its
    # ``record.args`` branch (the most common call path in the app).
    logger.warning("token=%s", raw)
    output = buf.getvalue()

    if should_redact:
        assert raw not in output, (
            f"Secret leaked unscrubbed in log output: {output!r}"
        )
        assert "***REDACTED-SECRET***" in output, (
            f"Redaction marker missing: {output!r}"
        )
    else:
        assert raw in output, (
            f"Non-secret value was unexpectedly scrubbed: {output!r}"
        )


def test_log_scrubber_redacts_exception_traceback() -> None:
    """The exception-traceback channel is the most plausible leak path
    (third-party SDK exceptions with auth bytes in the message), and
    the trickiest to test because ``logger.exception()`` formats the
    traceback at handler time, not at filter time. This test asserts
    the filter materializes + scrubs the exception text correctly —
    regression guard for the fix applied during initial implementation.
    """
    import io

    from app.utils.log_scrub import SecretScrubFilter

    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(logging.Formatter("%(message)s"))

    logger = logging.getLogger("test_scrub_exception")
    logger.handlers = [handler]
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    logger.addFilter(SecretScrubFilter())

    try:
        raise RuntimeError("boom with sk-ant-api03-EXCPATHLEAKGUARD000000000")
    except RuntimeError:
        logger.exception("during op")

    output = buf.getvalue()
    assert "sk-ant-" not in output, (
        f"Key leaked via exception traceback path: {output!r}"
    )
    assert "***REDACTED-SECRET***" in output, (
        f"Redaction marker missing from traceback output: {output!r}"
    )
