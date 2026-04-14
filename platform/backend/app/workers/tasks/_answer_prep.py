"""Match ATS form questions to user answer-book entries."""

from __future__ import annotations

import re
from typing import Any

# Common aliases: map normalised field keys to likely answer-book question keys.
_FIELD_ALIASES: dict[str, list[str]] = {
    "first_name": ["first_name", "given_name", "whats_your_first_name", "name"],
    "last_name": ["last_name", "surname", "family_name", "whats_your_last_name"],
    "name": ["full_name", "name", "first_name", "your_name", "whats_your_name"],
    "email": ["email", "email_address", "whats_your_email", "whats_your_email_address"],
    "phone": ["phone", "phone_number", "mobile", "whats_your_phone_number", "telephone"],
    "linkedin_url": ["linkedin", "linkedin_url", "linkedin_profile", "linkedincom"],
    "website": ["website", "portfolio", "personal_website", "website_portfolio", "github", "github_url"],
    "cover_letter": ["cover_letter", "why_do_you_want_to_work", "tell_us_about_yourself"],
    "salary": ["salary", "salary_expectations", "expected_salary", "desired_salary", "compensation"],
    "work_authorization": ["work_authorization", "are_you_authorized", "authorized_to_work", "work_auth", "do_you_require_sponsorship"],
    "location": ["location", "current_location", "where_are_you_located", "city"],
    "how_did_you_hear": ["how_did_you_hear", "how_did_you_hear_about_us", "referral_source"],
    "years_experience": ["years_of_experience", "years_experience", "how_many_years"],
    "start_date": ["start_date", "earliest_start_date", "when_can_you_start", "availability"],
    "gender": ["gender", "gender_identity"],
    "race": ["race", "ethnicity", "race_ethnicity"],
    "veteran_status": ["veteran", "veteran_status", "are_you_a_veteran"],
    "disability_status": ["disability", "disability_status"],
}

# Category hints: if field_key contains these terms, prefer answer-book entries from these categories.
_CATEGORY_HINTS: dict[str, str] = {
    "first_name": "personal_info",
    "last_name": "personal_info",
    "name": "personal_info",
    "email": "personal_info",
    "phone": "personal_info",
    "linkedin": "personal_info",
    "website": "personal_info",
    "github": "personal_info",
    "salary": "preferences",
    "work_auth": "work_auth",
    "sponsor": "work_auth",
    "authorized": "work_auth",
    "visa": "work_auth",
    "experience": "experience",
    "cover_letter": "experience",
    "tell_us": "experience",
    "skills": "skills",
    "location": "preferences",
    "start_date": "preferences",
    "gender": "custom",
    "race": "custom",
    "veteran": "custom",
    "disability": "custom",
}


def _normalise_key(text: str) -> str:
    key = text.lower().strip()
    key = re.sub(r"[^\w\s]", "", key)
    key = re.sub(r"\s+", "_", key)
    return key[:255]


def match_questions_to_answers(
    questions: list[dict[str, Any]],
    answer_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Match ATS form questions against user answer-book entries.

    Parameters
    ----------
    questions
        Normalised question dicts from ``fetch_application_questions``.
    answer_entries
        Merged answer-book entries (base + resume overrides).
        Each has ``question_key``, ``answer``, ``category``, ``source``.

    Returns
    -------
    list of matched dicts, one per form question::

        {
            "field_key": str,
            "label": str,
            "field_type": str,
            "required": bool,
            "options": list,
            "description": str,
            "answer": str,
            "match_source": "base" | "override" | "unmatched",
            "question_key": str,
            "confidence": "high" | "medium" | "low",
        }
    """
    # Build lookup indexes from answer-book entries
    by_key: dict[str, dict] = {}
    by_category: dict[str, list[dict]] = {}
    for entry in answer_entries:
        qk = entry.get("question_key", "")
        if qk:
            by_key[qk] = entry
        cat = entry.get("category", "")
        by_category.setdefault(cat, []).append(entry)

    results: list[dict[str, Any]] = []

    for q in questions:
        field_key = q.get("field_key", "")
        label = q.get("label", "")

        match = _find_best_match(field_key, label, by_key, by_category)

        results.append({
            "field_key": field_key,
            "label": label,
            "field_type": q.get("field_type", "text"),
            "required": q.get("required", False),
            "options": q.get("options", []),
            "description": q.get("description", ""),
            "answer": match["answer"],
            "match_source": match["source"],
            "question_key": match["question_key"],
            "confidence": match["confidence"],
        })

    return results


def _find_best_match(
    field_key: str,
    label: str,
    by_key: dict[str, dict],
    by_category: dict[str, list[dict]],
) -> dict[str, str]:
    """Find the best answer-book match for a given form field."""
    empty = {"answer": "", "source": "unmatched", "question_key": "", "confidence": "low"}

    # 1. Exact key match
    if field_key in by_key:
        entry = by_key[field_key]
        return {
            "answer": entry.get("answer", ""),
            "source": entry.get("source", "base"),
            "question_key": entry.get("question_key", field_key),
            "confidence": "high",
        }

    # 2. Alias match: check if field_key maps to known aliases
    aliases = _FIELD_ALIASES.get(field_key, [])
    for alias in aliases:
        if alias in by_key:
            entry = by_key[alias]
            return {
                "answer": entry.get("answer", ""),
                "source": entry.get("source", "base"),
                "question_key": entry.get("question_key", alias),
                "confidence": "high",
            }

    # 3. Label-based match: normalise the label and try matching
    label_key = _normalise_key(label)
    if label_key and label_key in by_key:
        entry = by_key[label_key]
        return {
            "answer": entry.get("answer", ""),
            "source": entry.get("source", "base"),
            "question_key": entry.get("question_key", label_key),
            "confidence": "high",
        }

    # 4. Partial / substring match on answer-book keys
    for qk, entry in by_key.items():
        if not qk:
            continue
        # Check if the field_key is a substring of the question_key or vice versa
        if field_key and (field_key in qk or qk in field_key):
            return {
                "answer": entry.get("answer", ""),
                "source": entry.get("source", "base"),
                "question_key": qk,
                "confidence": "medium",
            }
        if label_key and (label_key in qk or qk in label_key):
            return {
                "answer": entry.get("answer", ""),
                "source": entry.get("source", "base"),
                "question_key": qk,
                "confidence": "medium",
            }

    # 5. Category-based fallback: use category hints to find a plausible match
    hint_cat = _guess_category(field_key, label)
    if hint_cat and hint_cat in by_category:
        # Pick the first entry in the hinted category with a non-empty answer
        for entry in by_category[hint_cat]:
            if entry.get("answer"):
                return {
                    "answer": entry.get("answer", ""),
                    "source": entry.get("source", "base"),
                    "question_key": entry.get("question_key", ""),
                    "confidence": "low",
                }

    return empty


def _guess_category(field_key: str, label: str) -> str:
    """Guess the answer-book category from a field key or label."""
    combined = f"{field_key} {label}".lower()
    for term, cat in _CATEGORY_HINTS.items():
        if term in combined:
            return cat
    return ""
