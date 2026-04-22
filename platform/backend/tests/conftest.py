"""Pytest collection config for the backend test suite.

``test_api.py`` in this directory is a live-server integration harness
(see its module docstring: "Requires the platform to be running on
localhost:8000"). It's designed to be invoked as a script:

    python tests/test_api.py --url https://salesplatform.reventlabs.com

The ``test_*`` functions take a positional ``client`` argument (an
``httpx.Client`` constructed in the ``__main__`` block) rather than a
pytest fixture. Left to its default behaviour, pytest collects the 11
functions and errors every one of them with ``fixture 'client' not
found`` — which is what's failing CI.

The proper long-term fix is a matching fixture that boots a
``fastapi.testclient.TestClient`` against the app, ideally gated on
DB + Redis services being reachable. Until that lands, ``collect_
ignore_glob`` tells pytest to skip this file during discovery so CI
doesn't fail on a test harness that was never pytest-shaped.

The file itself stays unchanged so the script-mode entry point
keeps working for manual smoke runs against prod / staging.
"""

# Paths are resolved relative to this conftest.py's directory, so
# `"test_api.py"` matches `tests/test_api.py`. Glob form so a future
# `tests/test_*_live.py` can join the ignore list with one line.
collect_ignore_glob = [
    "test_api.py",
    # Same pattern: `test_profile_vault_live.py` is a script-mode
    # integration harness, takes args via argparse, not via pytest
    # fixtures. Gets invoked manually against a live backend:
    #   python tests/test_profile_vault_live.py --url http://localhost:8000/api/v1
    "test_profile_vault_live.py",
]
