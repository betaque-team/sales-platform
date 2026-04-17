"""Capture helpers for training-data examples (F238).

One thin wrapper per task type so the call sites read intent, not
schema. Pattern at every call site:

    from app.utils.training_capture import capture_resume_match
    await capture_resume_match(db, user, resume_text, job, decision)

The helpers handle:
  - PII scrubbing on free-text fields (resume, JD, cover letter)
  - User-id hashing
  - Truncation of long text fields (model context windows have
    practical limits; storing 100K of resume text per row would
    bloat the export with no training value beyond ~6K)
  - Idempotent commit so the call site can ``await`` and move on

Failure mode: every helper wraps its session.add + commit in a
try/except that LOGS-AND-SWALLOWS. Training-data capture is
side-effect work — a failure here must NOT break the user-facing
write that triggered it. If the audit table lags or fails, the user's
review still goes through.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.training_example import (
    TASK_COVER_LETTER_QUALITY,
    TASK_CUSTOMIZE_QUALITY,
    TASK_INTERVIEW_PREP_QUALITY,
    TASK_RESUME_MATCH,
    TASK_ROLE_CLASSIFY,
    TASK_SEARCH_INTENT,
    TrainingExample,
)
from app.utils.training_scrub import hash_user_id, scrub_pii

logger = logging.getLogger(__name__)

# Practical text caps. Larger than 6K bloats exports without training
# value (model context windows truncate anyway), smaller drops signal.
# Tuned to match the same caps the AI generation prompts use.
_RESUME_MAX_CHARS = 6000
_JD_MAX_CHARS = 6000
_COVER_LETTER_MAX_CHARS = 4000
_PREP_MAX_CHARS = 6000


async def _commit_safely(db: AsyncSession, row: TrainingExample, label: str) -> None:
    """Add + commit with the side-effect-safe try/except pattern.

    Pulled into a helper so the swallowing logic is one place. Every
    caller delegates here so a future "OK now I want to track failure
    rates" change is a single diff.
    """
    try:
        db.add(row)
        await db.commit()
    except Exception as e:
        # Side-effect-only: never break the user-facing write that
        # triggered this. Log + rollback so the parent transaction
        # can still commit its own work.
        logger.warning(
            "training_capture: failed to persist %s example: %s",
            label, e,
        )
        try:
            await db.rollback()
        except Exception:
            pass


# ── resume_match ────────────────────────────────────────────────────────────

async def capture_resume_match(
    db: AsyncSession,
    user_id: UUID,
    resume_text: str | None,
    job_title: str,
    job_description: str | None,
    decision: str,
    *,
    job_id: UUID | None = None,
    role_cluster: str | None = None,
) -> None:
    """One review event = one resume-match training row.

    Inputs: scrubbed resume + scrubbed JD + job title.
    Label: decision (accepted / rejected / skipped).

    The reviewer's user_id_hash is captured so per-user splits
    work — but the actual user_id is never stored.
    """
    inputs: dict[str, Any] = {
        "resume_text": scrub_pii(resume_text)[:_RESUME_MAX_CHARS],
        "job_title": job_title,
        "job_description": scrub_pii(job_description)[:_JD_MAX_CHARS],
    }
    metadata: dict[str, Any] = {
        "role_cluster": role_cluster,
    }
    if job_id is not None:
        metadata["job_id"] = str(job_id)
    row = TrainingExample(
        task_type=TASK_RESUME_MATCH,
        label_class=decision,
        inputs=inputs,
        labels={"decision": decision},
        metadata_json=metadata,
        user_id_hash=hash_user_id(user_id),
    )
    await _commit_safely(db, row, "resume_match")


# ── role_classify ───────────────────────────────────────────────────────────

async def capture_role_classify(
    db: AsyncSession,
    *,
    job_id: UUID,
    job_title: str,
    job_description: str | None,
    role_cluster: str | None,
    matched_role: str | None,
    platform: str | None,
) -> None:
    """One classified job = one role-classify training row.

    Hooked from `scan_task._upsert_job` AFTER the role-matching pass.
    Inputs: title + description (no PII expected — JD is public, but
    we scrub just in case the upstream included a contact email).
    Label: role_cluster (infra, security, qa, "" for unclassified).

    No user_id_hash — this is a job-side label, not user behavior.
    """
    inputs: dict[str, Any] = {
        "job_title": job_title,
        "job_description": scrub_pii(job_description)[:_JD_MAX_CHARS],
    }
    labels: dict[str, Any] = {
        "role_cluster": role_cluster or "",
        "matched_role": matched_role or "",
    }
    metadata: dict[str, Any] = {
        "job_id": str(job_id),
        "platform": platform,
    }
    row = TrainingExample(
        task_type=TASK_ROLE_CLASSIFY,
        # Use cluster as the label_class so class-balance queries work.
        # Empty string for unclassified rows so they're countable as
        # a distinct bucket.
        label_class=role_cluster or "unclassified",
        inputs=inputs,
        labels=labels,
        metadata_json=metadata,
        user_id_hash=None,
    )
    await _commit_safely(db, row, "role_classify")


# ── cover_letter_quality ────────────────────────────────────────────────────

async def capture_cover_letter_quality(
    db: AsyncSession,
    user_id: UUID,
    resume_text: str | None,
    job_title: str,
    job_description: str | None,
    cover_letter_text: str,
    *,
    job_id: UUID | None = None,
    tone: str | None = None,
    model_version: str | None = None,
    initial_label: str = "generated",
) -> None:
    """One AI cover-letter call = one row, label="generated".

    The label can later be updated (by a UI signal: did the user keep
    the letter, regenerate, or apply with it?) but storing the row at
    generation time captures the (input, output) pair so we don't
    lose the AI text after the user closes the tab.

    Frontend will eventually emit a follow-up event ("kept" / "regenerated"
    / "applied") that bumps the label_class — see Round 70 plan.
    """
    inputs: dict[str, Any] = {
        "resume_text": scrub_pii(resume_text)[:_RESUME_MAX_CHARS],
        "job_title": job_title,
        "job_description": scrub_pii(job_description)[:_JD_MAX_CHARS],
        "tone": tone or "professional",
    }
    labels: dict[str, Any] = {
        "cover_letter_text": scrub_pii(cover_letter_text)[:_COVER_LETTER_MAX_CHARS],
        "outcome": initial_label,
    }
    metadata: dict[str, Any] = {
        "model_version": model_version,
    }
    if job_id is not None:
        metadata["job_id"] = str(job_id)
    row = TrainingExample(
        task_type=TASK_COVER_LETTER_QUALITY,
        label_class=initial_label,
        inputs=inputs,
        labels=labels,
        metadata_json=metadata,
        user_id_hash=hash_user_id(user_id),
    )
    await _commit_safely(db, row, "cover_letter_quality")


# ── interview_prep_quality ──────────────────────────────────────────────────

async def capture_interview_prep_quality(
    db: AsyncSession,
    user_id: UUID,
    resume_text: str | None,
    job_title: str,
    job_description: str | None,
    prep_payload: dict,
    *,
    job_id: UUID | None = None,
    model_version: str | None = None,
    initial_label: str = "generated",
) -> None:
    """One AI interview-prep call = one row.

    Same shape as cover-letter capture but the label payload carries
    the structured prep dict (questions / talking_points / etc.)
    rather than a single text field. Length cap on the JSON-string
    serialized form so the export stays bounded.
    """
    import json
    serialized = json.dumps(prep_payload, default=str)
    inputs: dict[str, Any] = {
        "resume_text": scrub_pii(resume_text)[:_RESUME_MAX_CHARS],
        "job_title": job_title,
        "job_description": scrub_pii(job_description)[:_JD_MAX_CHARS],
    }
    labels: dict[str, Any] = {
        "prep_payload": serialized[:_PREP_MAX_CHARS],
        "outcome": initial_label,
    }
    metadata: dict[str, Any] = {"model_version": model_version}
    if job_id is not None:
        metadata["job_id"] = str(job_id)
    row = TrainingExample(
        task_type=TASK_INTERVIEW_PREP_QUALITY,
        label_class=initial_label,
        inputs=inputs,
        labels=labels,
        metadata_json=metadata,
        user_id_hash=hash_user_id(user_id),
    )
    await _commit_safely(db, row, "interview_prep_quality")


# ── customize_quality ──────────────────────────────────────────────────────

async def capture_customize_quality(
    db: AsyncSession,
    user_id: UUID,
    resume_text: str | None,
    job_title: str,
    job_description: str | None,
    customized_text: str,
    target_score: int,
    *,
    job_id: UUID | None = None,
    model_version: str | None = None,
    initial_label: str = "generated",
) -> None:
    """One AI resume-customize call = one row.

    Inputs include `target_score` so a future model can learn the
    relationship between requested score band and rewrite intensity.
    """
    inputs: dict[str, Any] = {
        "resume_text": scrub_pii(resume_text)[:_RESUME_MAX_CHARS],
        "job_title": job_title,
        "job_description": scrub_pii(job_description)[:_JD_MAX_CHARS],
        "target_score": target_score,
    }
    labels: dict[str, Any] = {
        "customized_text": scrub_pii(customized_text)[:_RESUME_MAX_CHARS],
        "outcome": initial_label,
    }
    metadata: dict[str, Any] = {"model_version": model_version}
    if job_id is not None:
        metadata["job_id"] = str(job_id)
    row = TrainingExample(
        task_type=TASK_CUSTOMIZE_QUALITY,
        label_class=initial_label,
        inputs=inputs,
        labels=labels,
        metadata_json=metadata,
        user_id_hash=hash_user_id(user_id),
    )
    await _commit_safely(db, row, "customize_quality")
