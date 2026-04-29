"""F269 — negative-signal parity across infra/security/qa clusters.

Manual sweep finding: 50 sales-titled jobs were misclassified as
``security`` and 3 as ``qa`` because:

  * ``_INFRA_NEGATIVE_TITLE_SIGNALS`` had a long sales/marketing
    exclusion list (F92, F227) that caught "Sales Engineer", "Cloud
    Sales Engineer", "Customer Success Manager", etc.
  * ``_SECURITY_NEGATIVE_TITLE_SIGNALS`` had compliance/legal/HR
    guards but NO sales/marketing parity, so titles like "SALES TEAM
    LEADER (DevSecOps)" matched the security cluster's keywords and
    landed there.
  * The ``qa`` cluster had ZERO negative-signal list at all —
    every sales/marketing role bearing a QA keyword (e.g. "Sales
    Quality Specialist") slipped into the relevant feed.

F269 brings the three lists into parity: revenue/marketing/people-ops
tokens are now in all three negative-signal sets, and ``qa`` has a
new ``_is_excluded_from_qa`` guard wired into both the config-driven
matcher and the hardcoded fallback path.

These tests lock the parity. Each cluster gets a sales-shaped probe
that should classify as ``""`` (unclassified) post-fix.
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
os.environ.setdefault("JWT_SECRET", "pytest-f269")


def test_security_cluster_excludes_sales_titles():
    """The exact failure mode reported: sales titles bearing a
    security keyword (e.g. ``DevSecOps``) must NOT land in security.
    """
    from app.workers.tasks._role_matching import match_role

    # The literal title that triggered the F269 investigation.
    sales_titles = [
        "Sales Engineer Cybersecurity",
        "Customer Success Manager — Security",
        "Sales Team Leader (DevSecOps Solutions)",
        "Account Executive — Cloud Security",
        "Pre-Sales Solutions Consultant Cybersecurity",
    ]
    for t in sales_titles:
        result = match_role(t)
        assert result["role_cluster"] == "", (
            f"F269 regression: {t!r} → role_cluster={result['role_cluster']!r}, "
            "expected '' (unclassified). Sales/marketing tokens must "
            "exclude titles from the security cluster the same way "
            "they already exclude from infra."
        )


def test_qa_cluster_excludes_sales_titles():
    """Pre-F269, the QA cluster had NO negative list. Sales titles
    bearing a QA keyword (Quality Specialist, Test Manager, etc.)
    landed in qa — surfaced 3 wrong rows in the relevant feed.
    """
    from app.workers.tasks._role_matching import match_role

    sales_titles = [
        "Sales Quality Specialist",
        "Customer Success Test Manager",
        "Marketing Quality Engineer",
        "Account Executive — Test Automation",
    ]
    for t in sales_titles:
        result = match_role(t)
        assert result["role_cluster"] == "", (
            f"F269 regression: {t!r} → role_cluster={result['role_cluster']!r}, "
            "expected '' (unclassified). The QA cluster must guard "
            "against sales/marketing titles the same way infra and "
            "security do."
        )


def test_infra_cluster_still_excludes_sales_titles():
    """Regression guard for the existing F92/F227 infra exclusion —
    tightening the security/qa lists must not have broken anything
    on the infra side.
    """
    from app.workers.tasks._role_matching import match_role

    sales_titles = [
        "Cloud Sales Engineer",
        "Account Manager — Cloud Solutions",
        "Customer Success Manager Kubernetes",
    ]
    for t in sales_titles:
        result = match_role(t)
        assert result["role_cluster"] == "", (
            f"F269 regression risk: {t!r} → cluster={result['role_cluster']!r}, "
            "expected ''. Infra negative-signal list must still work."
        )


def test_legitimate_security_titles_still_classify():
    """Counter-test: F269 must not over-fire. Real security titles
    (no sales/marketing tokens) must still classify as security.
    """
    from app.workers.tasks._role_matching import match_role

    legitimate = [
        ("Security Engineer", "security"),
        ("SOC Analyst", "security"),
        ("Penetration Tester", "security"),
        ("Cloud Security Engineer", "security"),
    ]
    for t, expected in legitimate:
        result = match_role(t)
        assert result["role_cluster"] == expected, (
            f"F269 over-broad: {t!r} → cluster={result['role_cluster']!r}, "
            f"expected {expected!r}. The negative list must not steal "
            "legitimate security titles."
        )


def test_legitimate_qa_titles_still_classify():
    """Same counter-test for QA — real QA titles must still match qa.
    """
    from app.workers.tasks._role_matching import match_role

    # Note: ``Test Automation Engineer`` is intentionally NOT here —
    # the matcher iterates INFRA_ROLES (which contains "Automation
    # Engineer") before QA_ROLES, so that title classifies as infra.
    # Pre-existing classifier behaviour, not an F269 regression.
    legitimate = [
        ("QA Engineer", "qa"),
        ("Senior SDET", "qa"),
        ("QA Analyst", "qa"),
    ]
    for t, expected in legitimate:
        result = match_role(t)
        assert result["role_cluster"] == expected, (
            f"F269 over-broad: {t!r} → cluster={result['role_cluster']!r}, "
            f"expected {expected!r}."
        )


def test_qa_negative_signals_list_present():
    """Structural — the new constant must exist, and the wire-up via
    ``_is_excluded_from_qa`` must be importable. A regression that
    drops the constant would silently re-open the gap.
    """
    from app.workers.tasks._role_matching import (
        _QA_NEGATIVE_TITLE_SIGNALS,
        _is_excluded_from_qa,
    )
    assert "sales" in _QA_NEGATIVE_TITLE_SIGNALS, (
        "F269 regression: 'sales' missing from _QA_NEGATIVE_TITLE_SIGNALS. "
        "The whole reason this list exists is to catch sales/marketing "
        "false positives in QA."
    )
    # Note: _is_excluded_from_qa expects pre-normalized (lowercased)
    # input — see _title_has_signal's plain `in` check. The public
    # ``match_role`` does the normalization first then calls the
    # exclusion helper. Tests below use the lowercased form directly.
    assert _is_excluded_from_qa("sales quality specialist") is True
    assert _is_excluded_from_qa("qa engineer") is False


def test_security_negative_signals_now_include_sales():
    """Structural — verify the F269 additions are in
    ``_SECURITY_NEGATIVE_TITLE_SIGNALS`` so future re-orderings can't
    silently drop them.
    """
    from app.workers.tasks._role_matching import _SECURITY_NEGATIVE_TITLE_SIGNALS

    must_have = {
        "sales", "account executive", "account manager", "marketing",
        "customer success", "business development", "presales",
    }
    missing = must_have - _SECURITY_NEGATIVE_TITLE_SIGNALS
    assert not missing, (
        f"F269 regression: _SECURITY_NEGATIVE_TITLE_SIGNALS missing "
        f"sales/marketing tokens: {missing}. The whole point of F269 "
        "is parity with the infra negative list."
    )
