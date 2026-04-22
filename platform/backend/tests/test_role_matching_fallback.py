"""Regression tests for the ``match_role_with_config`` fallback.

F235: the DB-driven ``RoleClusterConfig`` rows are a strict subset of
the hardcoded keyword lists refined across regression rounds 91, 92,
93, 227, …. Pre-fix, ``reclassify_and_rescore`` used the config-driven
matcher exclusively, leaving 315 stale infra + 440 stale security rows
that the hardcoded matcher would have caught.

These tests pin the hybrid behaviour:
  * Config wins when it has an opinion.
  * Hardcoded superset catches what the DB config narrows off — but
    only for clusters the admin still has active in the DB.
  * Disabled / removed clusters stay disabled (admin intent wins).
"""
from __future__ import annotations

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
os.environ.setdefault("JWT_SECRET", "pytest-role-matching")


def _minimal_config_missing_aws() -> dict:
    """A DB config where the ``infra`` cluster is present but
    deliberately narrower than the hardcoded list — it omits the
    ``aws`` / ``azure`` / ``gcp`` tokens the F93 sweep added to the
    hardcoded ``INFRA_KEYWORDS``.
    """
    return {
        "infra": {
            "keywords": {"devops", "kubernetes", "terraform"},
            "approved_roles": ["DevOps Engineer"],
        },
        "security": {
            "keywords": {"security", "soc"},
            "approved_roles": ["Security Engineer"],
        },
    }


def test_config_hit_wins_over_hardcoded():
    """When the config-driven matcher lands on a cluster, trust it —
    admins configured the cluster and any custom cluster (e.g.
    ``data_science``) only exists on the config side.
    """
    from app.workers.tasks._role_matching import match_role_with_config

    cfg = {
        "data_science": {
            "keywords": {"machine learning", "data scientist"},
            "approved_roles": ["Data Scientist"],
        },
    }
    result = match_role_with_config("Senior Data Scientist", cfg)
    assert result["role_cluster"] == "data_science"


def test_hardcoded_fallback_catches_aws_when_config_narrow():
    """Reproduces the F235 symptom — title classifies under the
    hardcoded ``aws`` keyword but the DB config omits it. Pre-fix
    this returned empty; post-fix it falls back to ``match_role`` and
    lands on ``infra``.
    """
    from app.workers.tasks._role_matching import match_role_with_config

    # "AWS Specialist" isn't in `approved_roles` OR the narrow config
    # keyword set. Pre-fix result: role_cluster="". Post-fix: "infra".
    result = match_role_with_config("AWS Specialist", _minimal_config_missing_aws())
    assert result["role_cluster"] == "infra", (
        "Expected hardcoded fallback to classify 'AWS Specialist' as infra "
        "when the DB config is narrower than the hardcoded keyword list. "
        "F235 regression."
    )


def test_fallback_respects_disabled_cluster():
    """If the admin removed / disabled a cluster (it's not in the DB
    config dict), the hardcoded fallback must NOT resurrect it. The
    admin's disable decision outranks the hardcoded superset.
    """
    from app.workers.tasks._role_matching import match_role_with_config

    # No `security` cluster in the config at all. A "SOC Analyst"
    # title would classify as security via the hardcoded matcher, but
    # the admin has explicitly removed the security cluster, so we
    # must honour that and return empty.
    cfg_no_security = {
        "infra": {
            "keywords": {"devops", "kubernetes"},
            "approved_roles": ["DevOps Engineer"],
        },
    }
    result = match_role_with_config("SOC Analyst", cfg_no_security)
    assert result["role_cluster"] == "", (
        "Expected empty cluster when admin has disabled the 'security' "
        "cluster — the hardcoded fallback must not override admin intent."
    )


def test_no_config_falls_through_to_hardcoded():
    """When called without a config (None / empty), the function is the
    hardcoded matcher — preserves the legacy single-matcher call path.
    """
    from app.workers.tasks._role_matching import match_role_with_config

    result = match_role_with_config("Kubernetes Engineer", None)
    assert result["role_cluster"] == "infra"

    result = match_role_with_config("Kubernetes Engineer", {})
    assert result["role_cluster"] == "infra"


def test_empty_config_infra_still_fires_hardcoded_fallback():
    """F235 edge case: the DB has an ``infra`` cluster row but with an
    empty keyword/approved-roles set (e.g. admin cleared it but hasn't
    deleted it). The config matcher returns empty, so we fall back to
    the hardcoded matcher — and since ``infra`` is still in the config
    dict, the fallback fires.
    """
    from app.workers.tasks._role_matching import match_role_with_config

    cfg = {
        "infra": {"keywords": set(), "approved_roles": []},
    }
    result = match_role_with_config("Terraform Engineer", cfg)
    assert result["role_cluster"] == "infra"
