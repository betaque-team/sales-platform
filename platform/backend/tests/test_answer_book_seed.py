"""Unit tests for the Answer Book required-entries seed (v6).

These are the 16 canonical rows the Claude Routine refuses to run
without — salary minima, notice period, work auth, EEO. This test
file locks in the invariants that make the feature safe:

  * Exactly 16 entries (v6 spec frozen).
  * question_keys are unique — the DB unique constraint would catch
    a duplicate anyway, but a unit test catches it at review time.
  * Every category is one that answer_book.py accepts (no typos that
    would silently fail on seed).
  * The REQUIRED_QUESTION_KEYS frozenset matches the entry list — the
    lock-enforcement code uses it as the authoritative "which rows are
    frozen" set, so drift between the two would let a user delete a
    required row via the regular CRUD endpoints.
  * Every required entry covers one of the spec's four buckets
    (comp, work auth, personal, EEO) — a quick sanity that a rename
    or deletion didn't shift the coverage.

No DB, no HTTP — just imports the module and asserts on its constants.
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
os.environ.setdefault("JWT_SECRET", "pytest-seed")

from app.services.answer_book_seed import (  # noqa: E402
    REQUIRED_ENTRIES,
    REQUIRED_QUESTION_KEYS,
)


# Categories the answer_book router accepts. Hardcoded here rather
# than imported because a typo on the router side should not silently
# pass the seed test.
VALID_ANSWER_BOOK_CATEGORIES = {
    "preferences",
    "work_auth",
    "personal_info",
}


def test_required_entries_has_exactly_sixteen_rows():
    """v6 spec: 16 entries. The module asserts this at import time too,
    but having it as a test makes the contract visible in failure
    reports."""
    assert len(REQUIRED_ENTRIES) == 16


def test_required_entries_have_unique_question_keys():
    """DB enforces uniqueness per (user_id, resume_id) — a duplicate
    here would fail the second insert during seed. Catch it earlier."""
    keys = [qkey for (_cat, qkey, _q) in REQUIRED_ENTRIES]
    assert len(keys) == len(set(keys)), (
        f"duplicate question_key in REQUIRED_ENTRIES: "
        f"{[k for k in keys if keys.count(k) > 1]}"
    )


def test_required_entries_use_valid_categories():
    """Every seeded row must go into a category answer_book.py
    recognises; otherwise the regular list/filter endpoints would
    never surface the row."""
    for (category, qkey, _q) in REQUIRED_ENTRIES:
        assert category in VALID_ANSWER_BOOK_CATEGORIES, (
            f"{qkey} uses unknown category '{category}'"
        )


def test_question_text_is_non_empty():
    """Empty question text would render a blank label on the setup
    page — the user has nothing to answer."""
    for (_cat, qkey, question) in REQUIRED_ENTRIES:
        assert question and question.strip(), (
            f"{qkey} has empty question text"
        )


def test_required_keys_frozenset_matches_entry_list():
    """REQUIRED_QUESTION_KEYS is used by the lock-enforcement path to
    reject delete/create on these rows via the regular CRUD endpoints.
    If it drifts from REQUIRED_ENTRIES, a user could create an
    unlocked row with a required key (or delete a required row via
    DELETE /answer-book/{id}), bypassing the routine's safety net."""
    derived = {qkey for (_cat, qkey, _q) in REQUIRED_ENTRIES}
    assert REQUIRED_QUESTION_KEYS == derived


def test_salary_geography_buckets_all_present():
    """The routine picks a salary row based on geography_bucket — if
    one bucket's row goes missing, the routine can't fill salary for
    that geography."""
    salary_keys = {
        qkey for (_cat, qkey, _q) in REQUIRED_ENTRIES
        if qkey.startswith("expected_min_salary_")
    }
    assert salary_keys == {
        "expected_min_salary_global",
        "expected_min_salary_usa",
        "expected_min_salary_uae",
        "expected_min_salary_remote",
    }


def test_all_four_eeo_questions_present():
    """EEO: race, gender, veteran, disability — each answered by the
    user themselves (no system default). Any missing here means the
    routine would leave EEO blank, which many ATS forms reject."""
    eeo_keys = {
        qkey for (_cat, qkey, _q) in REQUIRED_ENTRIES
        if qkey.startswith("eeo_")
    }
    assert eeo_keys == {
        "eeo_race_ethnicity",
        "eeo_gender",
        "eeo_veteran_status",
        "eeo_disability_status",
    }


def test_work_auth_coverage():
    """Work authorization + sponsorship are distinct rows — ATS forms
    ask them separately and conflating them gives wrong answers to
    at least one of the two variants."""
    work_auth_keys = {
        qkey for (_cat, qkey, _q) in REQUIRED_ENTRIES
        if _cat_of(qkey) == "work_auth"
    }
    assert "work_authorization_status" in work_auth_keys
    assert "sponsorship_needed" in work_auth_keys


def test_notice_period_has_both_integer_and_text():
    """ATS forms ask notice period both ways; seeding both formats
    avoids the routine having to guess which one a given form wants."""
    keys = {qkey for (_cat, qkey, _q) in REQUIRED_ENTRIES}
    assert "notice_period_weeks" in keys
    assert "notice_period_text" in keys


# Helper — local, not part of the module. Just makes the test above
# readable without duplicating the tuple unpacking.
def _cat_of(target_qkey: str) -> str:
    for (category, qkey, _q) in REQUIRED_ENTRIES:
        if qkey == target_qkey:
            return category
    raise KeyError(target_qkey)
