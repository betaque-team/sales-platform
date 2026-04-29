"""F273 — uvicorn multi-worker wiring lock.

Manual burst-load test found that 50 parallel ``/jobs`` requests
showed ``p50 = 2.6s`` despite a single-call baseline of 28 ms. Root
cause was the Dockerfile shipping with a single uvicorn worker; all
50 requests queued behind one Python process.

Fix: override the ``command:`` in docker-compose.prod.yml with
``uvicorn ... --workers ${UVICORN_WORKERS:-2}``. This test
structurally verifies the multi-worker flag is present in the
prod compose file. A regression that drops it (e.g. someone
reverting to single-worker for "simplicity") would re-open the
burst-load bottleneck.

Note: we test the *compose file* rather than runtime behaviour
because the Dockerfile CMD is also single-worker (intentionally —
local ``docker run platform-backend`` for ad-hoc debugging
shouldn't fork). The command-override only kicks in via
docker-compose, which is how prod actually launches.
"""
from __future__ import annotations

import os
import pathlib

# Repo layout: this test lives at
#   platform/backend/tests/test_f273_uvicorn_multi_worker.py
# Compose lives at
#   platform/docker-compose.prod.yml
# Walk two parents from the test dir to land on the platform dir.
_PLATFORM_DIR = pathlib.Path(__file__).resolve().parents[2]
_PROD_COMPOSE = _PLATFORM_DIR / "docker-compose.prod.yml"


def test_prod_compose_overrides_uvicorn_to_multi_worker():
    """The backend service in docker-compose.prod.yml must override
    the single-worker default with ``--workers ${UVICORN_WORKERS:-2}``
    (or higher). A regression that drops this re-opens the burst-
    load bottleneck (50 concurrent /jobs at p50=2.6s vs 1.3s with
    2 workers).
    """
    src = _PROD_COMPOSE.read_text()
    # We only care that there's a backend command override that
    # passes ``--workers``. We don't pin to "2" specifically — ops
    # should be free to bump via UVICORN_WORKERS env var without
    # the test breaking. The default value of 2 IS pinned via
    # ``${UVICORN_WORKERS:-2}`` though.
    assert "--workers" in src, (
        "F273 regression: docker-compose.prod.yml backend service no "
        "longer passes --workers to uvicorn. The Dockerfile CMD "
        "ships with a single worker, so dropping the override "
        "re-opens the burst-load bottleneck (50 concurrent /jobs "
        "at p50=2.6s vs ~1.3s with 2 workers)."
    )
    # Pinned default — the env-var override is fine, but we want a
    # safe default for fresh installs / ops who haven't set the
    # env. Lock the literal "2" or higher digit-string.
    assert "UVICORN_WORKERS:-2" in src or "UVICORN_WORKERS:-3" in src or "UVICORN_WORKERS:-4" in src, (
        "F273 regression: default UVICORN_WORKERS dropped below 2. "
        "A fresh install would launch with 1 worker and hit the "
        "burst-load bottleneck. Restore the ``${UVICORN_WORKERS:-2}`` "
        "default (or higher)."
    )


def test_dockerfile_cmd_remains_single_worker_safe_for_local_run():
    """The Dockerfile CMD intentionally stays single-worker so that
    ad-hoc ``docker run platform-backend`` (without compose
    overrides) doesn't fork unexpectedly. The multi-worker behaviour
    is opt-in via compose. This test ensures we don't accidentally
    hardcode --workers in the Dockerfile, which would bake the
    config into every consumer.
    """
    dockerfile = (_PLATFORM_DIR / "backend" / "Dockerfile").read_text()
    # The Dockerfile CMD line should NOT have --workers.
    cmd_lines = [
        ln for ln in dockerfile.splitlines()
        if ln.strip().startswith("CMD") and "uvicorn" in ln
    ]
    for ln in cmd_lines:
        assert "--workers" not in ln, (
            "F273 design: Dockerfile CMD must stay single-worker "
            "so ``docker run`` for ad-hoc debugging doesn't fork. "
            f"Got: {ln!r}. Move the multi-worker config to the "
            "compose ``command:`` override instead."
        )
