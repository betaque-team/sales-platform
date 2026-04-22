"""Seed definitions for the Claude Routine Apply required entries.

The routine refuses to run any application unless the user has filled
all of these. The 16 entries are the identity/comp/EEO facts the
routine must never invent — salary expectations, notice period, work
authorization, and the EEO demographic questions.

Each entry is seeded with:
    source      = "manual_required"
    is_locked   = True
    answer      = "" (empty; user fills via /answer-book/required-setup)
    resume_id   = None (shared across all resumes)

The /answer-book/seed-required endpoint is the ONLY authorized
creator of rows with ``is_locked=True``. It's idempotent: re-calling
is safe (already-present entries are skipped).

Why these exact 16? See v6 plan discussion. Briefly:
- 4 salary minima by geography (global / USA / UAE / remote) cover
  all classifiers; the routine picks the matching bucket.
- 2 notice-period formats (weeks integer / free text) because ATS
  forms ask it both ways.
- Work auth + sponsorship + relocation + work mode + location +
  earliest-start cover the standard comp/legal block.
- 4 EEO questions — EEOC self-identification. User fills each
  themselves (often with "Decline to self-identify") so the answer
  is provably user-chosen, not a system default.
"""

from __future__ import annotations


# Ordered tuples: (category, question_key, question). Category must
# match answer_book.VALID_CATEGORIES; question_key must be unique
# within (user_id, resume_id=None) — enforced by the uq_answer_user_
# resume_key constraint.
REQUIRED_ENTRIES: list[tuple[str, str, str]] = [
    # ── Comp / work terms ────────────────────────────────────────────
    ("preferences", "expected_min_salary_global",
     "Expected minimum salary (USD, for any role)"),
    ("preferences", "expected_min_salary_usa",
     "Expected minimum salary (USD, US-only roles)"),
    ("preferences", "expected_min_salary_uae",
     "Expected minimum salary (USD, UAE-only roles)"),
    ("preferences", "expected_min_salary_remote",
     "Expected minimum salary (USD, global remote roles)"),
    ("preferences", "notice_period_weeks",
     "Notice period in weeks (integer)"),
    ("preferences", "notice_period_text",
     "Notice period (free text, e.g. '4 weeks from offer acceptance')"),
    ("preferences", "earliest_start_date",
     "Earliest start date"),
    ("work_auth", "work_authorization_status",
     "Work authorization status (e.g. 'US citizen', 'H1B holder', "
     "'EU national', 'UAE resident')"),
    ("work_auth", "sponsorship_needed",
     "Do you require sponsorship? (yes/no)"),
    ("preferences", "willing_to_relocate",
     "Willing to relocate? (yes/no)"),
    ("preferences", "preferred_work_mode",
     "Preferred work mode (remote / hybrid / onsite)"),
    ("personal_info", "current_location",
     "Current location (city, country)"),
    # ── EEO ──────────────────────────────────────────────────────────
    # All four answered by the user themselves — no system default.
    # Common answer is "Decline to self-identify" but that's the
    # user's choice per field, not baked into the seed.
    ("personal_info", "eeo_race_ethnicity",
     "EEO: Race / ethnicity"),
    ("personal_info", "eeo_gender",
     "EEO: Gender"),
    ("personal_info", "eeo_veteran_status",
     "EEO: Veteran status"),
    ("personal_info", "eeo_disability_status",
     "EEO: Disability status"),
]


# Sanity check — keep in lockstep with v6 spec (16 entries).
assert len(REQUIRED_ENTRIES) == 16, (
    f"REQUIRED_ENTRIES must have 16 entries; got {len(REQUIRED_ENTRIES)}. "
    "If you intentionally changed the count, update the v6 spec + tests."
)

# question_keys reserved for manual_required — used by the lock-
# enforcement code in answer_book.py to reject any attempt to create
# or delete rows with these keys from the regular CRUD endpoints.
REQUIRED_QUESTION_KEYS: frozenset[str] = frozenset(
    qkey for (_cat, qkey, _q) in REQUIRED_ENTRIES
)
