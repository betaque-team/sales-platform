"""Question caching and answer book auto-population service."""

import uuid
import re
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.job_question import JobQuestion
from app.models.answer_book import AnswerBookEntry

logger = logging.getLogger(__name__)


def _normalise_key(text: str) -> str:
    """Normalize text to a field key."""
    key = text.lower().strip()
    key = re.sub(r"[^\w\s]", "", key)
    key = re.sub(r"\s+", "_", key)
    return key[:255]


async def get_or_fetch_questions(db: AsyncSession, job, board_slug: str) -> list[dict]:
    """Get cached questions or fetch from ATS API, then cache."""
    # Check cache first
    result = await db.execute(
        select(JobQuestion).where(JobQuestion.job_id == job.id)
    )
    cached = result.scalars().all()

    if cached:
        return [
            {
                "field_key": q.field_key,
                "label": q.label,
                "field_type": q.field_type,
                "required": q.required,
                "options": q.options or [],
                "description": q.description or "",
            }
            for q in cached
        ]

    # Fetch from ATS API
    from app.fetchers.questions import fetch_application_questions
    questions = fetch_application_questions(job.platform, job.external_id, board_slug)

    # Cache in DB
    for q in questions:
        jq = JobQuestion(
            id=uuid.uuid4(),
            job_id=job.id,
            field_key=q.get("field_key", ""),
            label=q.get("label", ""),
            field_type=q.get("field_type", "text"),
            required=q.get("required", False),
            options=q.get("options", []),
            description=q.get("description", ""),
            platform=job.platform,
        )
        db.add(jq)

    try:
        await db.flush()
    except Exception:
        await db.rollback()
        logger.warning("Failed to cache questions for job %s", job.id)

    return questions


def get_or_fetch_questions_sync(session: Session, job, board_slug: str) -> list[dict]:
    """Sync version for Celery tasks."""
    cached = session.execute(
        select(JobQuestion).where(JobQuestion.job_id == job.id)
    ).scalars().all()

    if cached:
        return [
            {
                "field_key": q.field_key,
                "label": q.label,
                "field_type": q.field_type,
                "required": q.required,
                "options": q.options or [],
                "description": q.description or "",
            }
            for q in cached
        ]

    from app.fetchers.questions import fetch_application_questions
    questions = fetch_application_questions(job.platform, job.external_id, board_slug)

    for q in questions:
        jq = JobQuestion(
            id=uuid.uuid4(),
            job_id=job.id,
            field_key=q.get("field_key", ""),
            label=q.get("label", ""),
            field_type=q.get("field_type", "text"),
            required=q.get("required", False),
            options=q.get("options", []),
            description=q.get("description", ""),
            platform=job.platform,
        )
        session.add(jq)

    try:
        session.flush()
    except Exception:
        session.rollback()
        logger.warning("Failed to cache questions for job %s", job.id)

    return questions


async def auto_populate_answer_book(db: AsyncSession, user_id, questions: list[dict]) -> int:
    """Create placeholder answer book entries for new questions.

    Skips file-type fields. Returns count of new entries created.
    """
    from app.workers.tasks._answer_prep import _FIELD_ALIASES

    # Load existing entries for this user (base only)
    result = await db.execute(
        select(AnswerBookEntry).where(
            AnswerBookEntry.user_id == user_id,
            AnswerBookEntry.resume_id.is_(None),
        )
    )
    existing = result.scalars().all()
    existing_keys = {e.question_key for e in existing}

    # Build reverse alias map: alias -> canonical key
    all_known_keys = set(existing_keys)
    for canonical, aliases in _FIELD_ALIASES.items():
        for alias in aliases:
            if alias in existing_keys or _normalise_key(alias) in existing_keys:
                all_known_keys.add(canonical)
                all_known_keys.update(_normalise_key(a) for a in aliases)
                break

    added = 0
    for q in questions:
        if q.get("field_type") == "file":
            continue

        field_key = _normalise_key(q.get("field_key", "") or q.get("label", ""))
        if not field_key:
            continue

        if field_key in all_known_keys:
            continue

        # Check aliases
        is_known = False
        for canonical, aliases in _FIELD_ALIASES.items():
            norm_aliases = [_normalise_key(a) for a in aliases]
            if field_key in norm_aliases or canonical == field_key:
                if canonical in all_known_keys or any(a in all_known_keys for a in norm_aliases):
                    is_known = True
                    break

        if is_known:
            continue

        # Guess category
        category = _guess_category(field_key)

        label = q.get("label", field_key.replace("_", " ").title())

        entry = AnswerBookEntry(
            id=uuid.uuid4(),
            user_id=user_id,
            resume_id=None,
            category=category,
            question=label,
            question_key=field_key,
            answer="",
            source="ats_discovered",
        )
        db.add(entry)
        all_known_keys.add(field_key)
        added += 1

    if added:
        try:
            await db.flush()
        except Exception:
            await db.rollback()
            logger.warning("Failed to auto-populate answer book entries")
            added = 0

    return added


def _guess_category(field_key: str) -> str:
    """Guess answer book category from field key."""
    personal = ["first_name", "last_name", "email", "phone", "name", "linkedin", "website", "github", "address", "city", "zip", "country"]
    work_auth = ["work_auth", "sponsor", "authorized", "visa", "legally", "citizenship", "eligible"]
    experience = ["experience", "cover_letter", "tell_us", "why_do_you", "achievement", "describe", "about_yourself"]
    skills = ["skills", "technologies", "languages", "proficient", "certif"]
    preferences = ["salary", "compensation", "start_date", "relocat", "schedule", "travel", "notice_period"]

    for kw in personal:
        if kw in field_key:
            return "personal_info"
    for kw in work_auth:
        if kw in field_key:
            return "work_auth"
    for kw in experience:
        if kw in field_key:
            return "experience"
    for kw in skills:
        if kw in field_key:
            return "skills"
    for kw in preferences:
        if kw in field_key:
            return "preferences"
    return "custom"
