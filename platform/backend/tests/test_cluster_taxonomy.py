"""F264 — cluster taxonomy invariants.

The user reshaped the role-cluster taxonomy so that:

  * ``infra`` cluster owns devsecops alongside DevOps / Cloud / SRE
    (build-pipeline security clusters with engineering, not SOC ops).
  * ``security`` cluster keeps pure SOC analyst / GRC / compliance /
    InfoSec / pentest roles.
  * Both clusters remain ``is_relevant=True`` (Option C — least
    disruptive reshape).

Pre-fix, ``devsecops`` was a keyword in BOTH ``INFRA_KEYWORDS`` and
``SECURITY_KEYWORDS`` in app/workers/tasks/_role_matching.py, plus
the seed_data.py cluster config listed it under ``security``. The
matcher's iteration order arbitrarily decided which cluster a
devsecops job ended up in — usually security, since that list was
checked second after infra failed-fast on no match. Result: a "Senior
DevSecOps Engineer" job got tagged ``security`` even though the team
treats it as engineering platform work.

These tests lock down the post-F264 invariant: devsecops appears in
infra and ONLY infra, across all three sources of truth.
"""
from __future__ import annotations

import os

# Minimum env so app.config imports cleanly (mirrors other test modules).
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://placeholder:placeholder@localhost:5432/placeholder",
)
os.environ.setdefault(
    "DATABASE_URL_SYNC",
    "postgresql://placeholder:placeholder@localhost:5432/placeholder",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET", "pytest-cluster-taxonomy")


def test_devsecops_keyword_is_in_infra_only():
    """``devsecops`` must appear in ``INFRA_KEYWORDS`` and NOT in
    ``SECURITY_KEYWORDS``. If a future maintainer re-adds it to both
    (or moves it back to security), this test fails CI before the
    classification gets re-broken on tens of thousands of rows.
    """
    from app.workers.tasks._role_matching import (
        INFRA_KEYWORDS, SECURITY_KEYWORDS,
    )
    assert "devsecops" in INFRA_KEYWORDS, (
        "F264 regression: 'devsecops' missing from INFRA_KEYWORDS. "
        "DevSecOps roles belong in the broadened infra cluster per "
        "the F264 reshape."
    )
    assert "devsecops" not in SECURITY_KEYWORDS, (
        "F264 regression: 'devsecops' is back in SECURITY_KEYWORDS. "
        "It MUST be in infra only — duplicate membership made the "
        "matcher's iteration order decide cluster routing, which "
        "was the original bug."
    )


def test_devsecops_engineer_role_is_in_infra_only():
    """Same invariant for the canonical role title. ``DevSecOps
    Engineer`` belongs in INFRA_ROLES; SECURITY_ROLES no longer
    advertises it.
    """
    from app.workers.tasks._role_matching import INFRA_ROLES, SECURITY_ROLES
    assert "DevSecOps Engineer" in INFRA_ROLES, (
        "F264 regression: 'DevSecOps Engineer' missing from INFRA_ROLES."
    )
    assert "DevSecOps Engineer" not in SECURITY_ROLES, (
        "F264 regression: 'DevSecOps Engineer' is back in SECURITY_ROLES."
    )


def test_seed_data_cluster_config_aligns():
    """The DB seed file must mirror the in-code keyword lists. If
    these drift, a fresh database install gets one taxonomy and the
    classifier uses another.

    We import the seed module's ``seed_role_cluster_configs`` clusters
    list indirectly by source-grepping (the function is async and
    needs a DB connection). The cheap source-level check is enough
    to catch the drift.
    """
    import inspect
    from app import seed_data
    src = inspect.getsource(seed_data)

    # Locate the ``"name": "infra"`` cluster block and verify
    # ``devsecops`` appears in its keywords/approved_roles.
    # Locate the ``"name": "security"`` cluster block and verify
    # ``devsecops`` does NOT appear.
    infra_block = src.split('"name": "infra"', 1)
    assert len(infra_block) == 2, "Could not find infra cluster block in seed_data.py"
    # Infra block runs until the next "name": tag.
    infra_section = infra_block[1].split('"name":', 1)[0]
    assert "devsecops" in infra_section, (
        "F264 regression: seed_data.py infra cluster keywords or "
        "approved_roles no longer mention devsecops."
    )

    security_block = src.split('"name": "security"', 1)
    assert len(security_block) == 2, (
        "Could not find security cluster block in seed_data.py"
    )
    # Security block runs until next "name": OR end of clusters list.
    security_section = security_block[1].split("\n        ]", 1)[0]
    # The check is "devsecops" specifically, NOT in a comment. So we
    # look at the part that comes AFTER the cluster's docstring/
    # comments — i.e. inside the actual keyword string. The string
    # forms are ``"keywords": "...,devsecops,..."`` or similar.
    keyword_lines = [
        line for line in security_section.split("\n")
        if '"keywords"' in line or '"approved_roles"' in line
    ]
    for line in keyword_lines:
        assert "devsecops" not in line.lower(), (
            f"F264 regression: seed_data.py security cluster still "
            f"references devsecops on line: {line.strip()[:120]}"
        )


def test_sec_signals_splitter_no_longer_routes_devsecops_to_security():
    """``seed_data.py``'s ``role_keywords`` splitter (which routes
    bulk-seeded role keywords into infra vs security) must NOT treat
    ``devsecops`` as a security signal. This is the helper that
    decides bulk-seeded keywords' default cluster — if it still
    grouped devsecops with security, every fresh seed would re-bury
    devsecops keywords in the wrong cluster.
    """
    import inspect
    from app import seed_data
    src = inspect.getsource(seed_data)

    # Find the ``sec_signals`` tuple. It's defined inline in the
    # role-rules splitter section. We extract the lines between
    # ``sec_signals = (`` and the closing ``)``.
    if "sec_signals = (" in src:
        start = src.index("sec_signals = (")
        end = src.index(")", start)
        signals_block = src[start:end + 1]
        assert "devsecops" not in signals_block.lower(), (
            "F264 regression: sec_signals tuple in seed_data.py still "
            "treats 'devsecops' as a security signal. The splitter "
            "would re-route devsecops keywords back to the security "
            "cluster on every fresh seed."
        )
    else:
        # The splitter might have been refactored — fall back to a
        # broader source check: the legacy substring list pattern
        # ``["security", "soc", "devsecops", ...]`` shouldn't appear.
        assert '"devsecops"' not in src.split("# F264")[0], (
            "F264 regression: legacy splitter still references devsecops."
        )
