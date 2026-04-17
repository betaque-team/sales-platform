"""Application tracking endpoints."""

import uuid
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.database import get_db
from app.models.application import Application
from app.models.job import Job
from app.models.company import Company, CompanyATSBoard
from app.models.resume import Resume, ResumeScore
from app.models.answer_book import AnswerBookEntry
from app.models.platform_credential import PlatformCredential
from app.models.user import User
from app.api.deps import get_current_user
from app.utils.sql import escape_like

router = APIRouter(prefix="/applications", tags=["applications"])

# Valid status transitions -- terminal states have no outgoing transitions
VALID_TRANSITIONS = {
    "prepared": ["applied", "withdrawn"],
    "submitted": ["applied", "withdrawn"],
    "applied": ["interview", "rejected", "withdrawn"],
    "interview": ["offer", "rejected", "withdrawn"],
    "offer": ["rejected", "withdrawn"],
    "rejected": [],
    "withdrawn": [],
}

# Regression finding 194: PATCH /applications/{id} was declared with
# `body: dict`, so any stray key (typo like `stauts`, camelCase
# `preparedAnswers`, or a hand-crafted `{"__evil__": "<script>..."}`)
# was silently ignored with a 200 response. Users thought they had
# advanced the application's stage when nothing changed. We now parse
# against a strict schema: `status` is a Literal over the documented
# states, and `extra="forbid"` causes Pydantic v2 to 422 on any
# unknown field. The VALID_TRANSITIONS state-machine check still runs
# against the parsed `status` value since it depends on the row's
# current state (not expressible in a static schema).
ApplicationStatus = Literal[
    "prepared", "submitted", "applied", "interview",
    "offer", "rejected", "withdrawn",
]


# Regression finding 129: `prepared_answers` was `list[dict] | None =
# None` with no per-item shape and no array cap, so a client could
# POST 10,000 dicts × 100-char answer strings (1.37 MB parsed) and
# have it persisted on `Application.prepared_answers` (typed JSON,
# unbounded). On a user with 100 apps, that's ~137 MB per user in
# storage, plus every analytics endpoint that joins `Application`
# loads the blob into memory. Same failure-mode class as F130 (unbounded
# comment), F131 (unbounded description), F80 (answer book). Per-item
# ApplicationAnswer schema caps the two free-text fields; `max_length=
# 200` on the outer array is ~10× a real ATS form (typical 5-30 fields).
class ApplicationAnswer(BaseModel):
    """One field of a prepared-application answer payload.

    Mirrors the shape the `/applications/prepare` handler builds at
    line 285 — only the free-text fields get length-capped here; the
    rest are enums / bools / question_keys that are already length-
    bounded by the ATS form they came from.
    """

    model_config = ConfigDict(extra="allow")

    # `question_key` is derived from the ATS form schema and typically
    # reads like `first_name`, `years_experience`, `cover_letter`.
    # 200 chars is 5x the longest question_key the repo generates
    # today, with room for provider-prefixed keys like
    # `greenhouse_custom_field_1234`.
    question_key: str | None = Field(default=None, max_length=200)
    # `answer` is the actual user-entered value. Most answers are
    # short (name, email, yes/no); cover-letter fields can go long but
    # 5000 chars is a hard upper bound (typical cover letter is
    # ~300 words ≈ 2000 chars). Above this we're clearly being
    # DoS-payload'd, not getting real data.
    answer: str | None = Field(default=None, max_length=5000)


class ApplicationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ApplicationStatus | None = None
    # F129: 5000-char cap matches the answer_book + cover_letter
    # precedent. Pre-fix was 10000 (F194) which rejected the 10MB
    # probe but still allowed ~40KB of prose per row. Tightening here
    # now that we know the real-world upper bound. Rows with >5000
    # chars written before this fix are grandfathered (PATCH only
    # rejects oversize writes; reads still return whatever's there).
    notes: str | None = Field(default=None, max_length=5000)
    # F129: cap the outer list at 200 + enforce ApplicationAnswer on
    # each item. `extra="allow"` on the inner schema keeps backward
    # compatibility with any provider-specific fields the
    # /applications/prepare handler adds (confidence, match_source,
    # field_type, etc.) — those aren't free-text user input so they
    # don't need capping.
    prepared_answers: list[ApplicationAnswer] | None = Field(default=None, max_length=200)


@router.get("/readiness/{job_id}")
async def get_apply_readiness(
    job_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Check if user is ready to apply for a job. Returns readiness status for each prerequisite."""
    # Load job
    job = (await db.execute(
        select(Job).where(Job.id == job_id)
    )).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Resume check
    resume_ready = False
    resume_info = None
    if user.active_resume_id:
        resume = (await db.execute(
            select(Resume).where(Resume.id == user.active_resume_id, Resume.user_id == user.id)
        )).scalar_one_or_none()
        if resume and resume.status == "ready":
            resume_ready = True
            resume_info = {"id": str(resume.id), "label": resume.label or resume.filename}

    # Credential check
    cred_ready = False
    cred_info = None
    if resume_ready:
        cred = (await db.execute(
            select(PlatformCredential).where(
                PlatformCredential.resume_id == user.active_resume_id,
                PlatformCredential.platform == job.platform,
            )
        )).scalar_one_or_none()
        if cred and cred.encrypted_password:
            cred_ready = True
            cred_info = {"platform": cred.platform, "email": cred.email}

    # Answer book count
    ab_count_q = select(func.count(AnswerBookEntry.id)).where(
        AnswerBookEntry.user_id == user.id,
        or_(
            AnswerBookEntry.resume_id.is_(None),
            AnswerBookEntry.resume_id == user.active_resume_id,
        ),
    )
    ab_count = (await db.execute(ab_count_q)).scalar() or 0

    # Resume score.
    # resume_scores has no UNIQUE (resume_id, job_id); duplicate rows
    # happen in production (concurrent scoring tasks) and would make
    # `scalar_one_or_none()` raise `MultipleResultsFound` → 500. Pick
    # the most recent row until the dedupe + UNIQUE migration lands.
    score_info = None
    if resume_ready:
        score = (await db.execute(
            select(ResumeScore.overall_score)
            .where(
                ResumeScore.resume_id == user.active_resume_id,
                ResumeScore.job_id == job.id,
            )
            .order_by(ResumeScore.scored_at.desc())
            .limit(1)
        )).scalar_one_or_none()
        if score is not None:
            score_info = {"score": round(score, 1)}

    # Existing application check
    existing = (await db.execute(
        select(Application.id, Application.status).where(
            Application.user_id == user.id,
            Application.job_id == job.id,
        )
    )).first()

    return {
        "resume": {"ready": resume_ready, **(resume_info or {})},
        "credentials": {"ready": cred_ready, "platform": job.platform, **(cred_info or {})},
        "answer_book": {"ready": ab_count > 0, "count": ab_count},
        "resume_score": {"available": score_info is not None, **(score_info or {})},
        "existing_application": {"exists": existing is not None, "id": str(existing[0]) if existing else None, "status": existing[1] if existing else None},
        "can_apply": resume_ready and cred_ready,
    }


@router.post("/prepare")
async def prepare_application(
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Prepare an application for a job using the active resume.

    Fetches the actual ATS form questions from the platform, matches
    them against the user's answer book, and returns a structured list
    of fields with pre-filled answers.
    """
    job_id = body.get("job_id")
    if not job_id:
        raise HTTPException(status_code=400, detail="job_id is required")

    if not user.active_resume_id:
        raise HTTPException(status_code=400, detail="No active resume selected. Please switch to a resume first.")

    # Load resume
    resume = (await db.execute(
        select(Resume).where(Resume.id == user.active_resume_id, Resume.user_id == user.id)
    )).scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Active resume not found")

    # Load job with company
    job = (await db.execute(
        select(Job).options(joinedload(Job.company)).where(Job.id == job_id)
    )).unique().scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Enforce credential requirement
    credential = (await db.execute(
        select(PlatformCredential).where(
            PlatformCredential.resume_id == resume.id,
            PlatformCredential.platform == job.platform,
        )
    )).scalar_one_or_none()
    if not credential or not credential.encrypted_password:
        raise HTTPException(
            status_code=400,
            detail=f"Platform credentials required for {job.platform}. Add credentials before applying.",
        )

    # Check if application already exists
    existing = (await db.execute(
        select(Application).where(
            Application.user_id == user.id,
            Application.job_id == job.id,
        )
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Application already exists for this job")

    # Look up board slug for question fetching
    board = (await db.execute(
        select(CompanyATSBoard).where(
            CompanyATSBoard.company_id == job.company_id,
            CompanyATSBoard.platform == job.platform,
            CompanyATSBoard.is_active.is_(True),
        )
    )).scalar_one_or_none()
    board_slug = board.slug if board else ""

    # Fetch ATS form questions (cached via question service)
    from app.services.question_service import get_or_fetch_questions, auto_populate_answer_book
    ats_questions = await get_or_fetch_questions(db, job, board_slug)
    new_entries = await auto_populate_answer_book(db, user.id, ats_questions)

    # Load and merge answer book entries
    entries = (await db.execute(
        select(AnswerBookEntry).where(
            AnswerBookEntry.user_id == user.id,
            or_(
                AnswerBookEntry.resume_id.is_(None),
                AnswerBookEntry.resume_id == resume.id,
            ),
        ).order_by(AnswerBookEntry.category)
    )).scalars().all()

    merged: dict[str, dict] = {}
    for entry in entries:
        key = entry.question_key
        if key not in merged or entry.resume_id is not None:
            merged[key] = {
                "question_key": entry.question_key,
                "question": entry.question,
                "answer": entry.answer,
                "category": entry.category,
                "source": "override" if entry.resume_id else "base",
            }

    # Match ATS questions to answer book
    from app.workers.tasks._answer_prep import match_questions_to_answers
    prepared_answers = match_questions_to_answers(ats_questions, list(merged.values()))

    # Get resume score for this job.
    # See the matching comment above: pick the most recently computed
    # score to avoid MultipleResultsFound when the table has duplicate
    # rows for the (resume_id, job_id) pair.
    score = (await db.execute(
        select(ResumeScore.overall_score)
        .where(
            ResumeScore.resume_id == resume.id,
            ResumeScore.job_id == job.id,
        )
        .order_by(ResumeScore.scored_at.desc())
        .limit(1)
    )).scalar_one_or_none()

    # Create application record
    application = Application(
        id=uuid.uuid4(),
        user_id=user.id,
        job_id=job.id,
        resume_id=resume.id,
        status="prepared",
        apply_method="manual_copy",
        prepared_answers=prepared_answers,
    )
    db.add(application)
    await db.commit()
    await db.refresh(application)

    return {
        "id": str(application.id),
        "job": {
            "id": str(job.id),
            "title": job.title,
            "company_name": job.company.name if job.company else "",
            "platform": job.platform,
            "url": job.url,
        },
        "resume": {
            "id": str(resume.id),
            "label": resume.label or resume.filename,
        },
        "resume_score": round(score, 1) if score else None,
        "apply_method": "manual_copy",
        "has_credentials": True,
        "prepared_answers": prepared_answers,
        "status": "prepared",
    }


@router.post("/{app_id}/sync-answers")
async def sync_answers_to_book(
    app_id: UUID,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Sync edited answers back to the answer book.

    Accepts a list of {question_key, answer} and updates matching
    AnswerBookEntry records, preferring resume-specific entries.
    """
    app = (await db.execute(
        select(Application).where(Application.id == app_id, Application.user_id == user.id)
    )).scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    answers = body.get("answers", [])
    if not answers:
        return {"synced": 0}

    synced = 0
    for item in answers:
        qk = item.get("question_key", "").strip()
        answer_text = item.get("answer", "")
        if not qk:
            continue

        # Try resume-specific entry first, then base
        entry = (await db.execute(
            select(AnswerBookEntry).where(
                AnswerBookEntry.user_id == user.id,
                AnswerBookEntry.resume_id == app.resume_id,
                AnswerBookEntry.question_key == qk,
            )
        )).scalar_one_or_none()

        if not entry:
            entry = (await db.execute(
                select(AnswerBookEntry).where(
                    AnswerBookEntry.user_id == user.id,
                    AnswerBookEntry.resume_id.is_(None),
                    AnswerBookEntry.question_key == qk,
                )
            )).scalar_one_or_none()

        if entry:
            entry.answer = answer_text
            entry.usage_count = (entry.usage_count or 0) + 1
            db.add(entry)
            synced += 1

    await db.commit()
    return {"synced": synced}


@router.get("/by-job/{job_id}")
async def get_application_by_job(
    job_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get existing application for a specific job (if any)."""
    result = await db.execute(
        select(Application)
        .options(joinedload(Application.job), joinedload(Application.resume))
        .where(Application.user_id == user.id, Application.job_id == job_id)
    )
    app = result.unique().scalar_one_or_none()
    if not app:
        return None

    return {
        "id": str(app.id),
        "job_id": str(app.job_id),
        "resume_id": str(app.resume_id),
        "resume_label": (app.resume.label or app.resume.filename) if app.resume else "",
        "status": app.status,
        "apply_method": app.apply_method,
        "prepared_answers": app.prepared_answers or [],
        "notes": app.notes or "",
        "applied_at": app.applied_at.isoformat() if app.applied_at else None,
        "created_at": app.created_at.isoformat(),
    }


@router.get("/stats")
async def get_application_stats(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get application counts by status."""
    result = await db.execute(
        select(Application.status, func.count(Application.id))
        .where(Application.user_id == user.id)
        .group_by(Application.status)
    )
    counts = {row[0]: row[1] for row in result}

    total = sum(counts.values())
    return {
        "total": total,
        "prepared": counts.get("prepared", 0),
        "submitted": counts.get("submitted", 0),
        "applied": counts.get("applied", 0),
        "interview": counts.get("interview", 0),
        "offer": counts.get("offer", 0),
        "rejected": counts.get("rejected", 0),
        "withdrawn": counts.get("withdrawn", 0),
    }


@router.get("")
async def list_applications(
    # Regression finding 220(B): `status` was typed `str | None` while the
    # `ApplicationStatus` Literal (used by `ApplicationUpdate` on line 57)
    # was sitting right there in the same module. A typo like `?status=
    # Rejected` (capital R), `?status=APPLIED` (all caps), or `?status=
    # <script>` silently returned HTTP 200 with total=0 — users saw "no
    # applications" for a valid-looking filter value. Reusing the Literal
    # here gives us a parse-time 422 that enumerates the allowed states.
    # Same bug class as F187 (/export/jobs), F218 (/jobs), and F191
    # (/platforms).
    status: ApplicationStatus | None = None,
    # Regression finding 228: `submission_source` was ADDED as a response
    # field by the Feature C migration (r8m9n0o1p2q3) and consumed by the
    # frontend as a "Source" badge + gating for the "What we sent" modal
    # (ApplicationsPage.tsx:201,262), but the matching INPUT filter was
    # missed. Live verification at deploy showed `?submission_source=
    # review_queue` silently returned total=9 (unfiltered). Same
    # F220(A)/(C) silent-accept class — declared params validate
    # cleanly, undeclared params are discarded by FastAPI without
    # warning. Literal-typing here gives a parse-time 422 on typos and
    # the matching WHERE below makes the filter actually bite.
    submission_source: Literal["review_queue", "manual_prepare"] | None = None,
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List applications with filters."""
    query = (
        select(Application, Job, Company.name.label("co_name"), Resume.label.label("resume_label"), Resume.filename.label("resume_filename"))
        .join(Job, Application.job_id == Job.id)
        .join(Company, Job.company_id == Company.id)
        .join(Resume, Application.resume_id == Resume.id)
        .where(Application.user_id == user.id)
    )

    if status:
        query = query.where(Application.status == status)
    if submission_source:
        query = query.where(Application.submission_source == submission_source)
    if search and search.strip():
        # Findings 84+85: escape LIKE metachars + drop whitespace-only input.
        term = f"%{escape_like(search.strip())}%"
        query = query.where(or_(
            Job.title.ilike(term, escape="\\"),
            Company.name.ilike(term, escape="\\"),
        ))

    # Count
    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    query = query.order_by(Application.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    rows = (await db.execute(query)).all()

    items = []
    for app, job, co_name, resume_label, resume_filename in rows:
        items.append({
            "id": str(app.id),
            "job_id": str(app.job_id),
            "job_title": job.title,
            "company_name": co_name or "",
            "platform": job.platform,
            "job_url": job.url,
            "resume_id": str(app.resume_id),
            "resume_label": resume_label or resume_filename or "",
            "status": app.status,
            "apply_method": app.apply_method,
            "applied_at": app.applied_at.isoformat() if app.applied_at else None,
            "submitted_at": app.submitted_at.isoformat() if app.submitted_at else None,
            "created_at": app.created_at.isoformat(),
            "notes": app.notes,
            # Feature C — expose provenance + top-level score on the list
            # view. Not including `applied_resume_text` here on purpose;
            # the text blob can be ~20KB and a 25-row list shouldn't ship
            # half a megabyte. Callers who want the full snapshot fetch
            # the single-application endpoint.
            "submission_source": app.submission_source,
            "applied_resume_score_overall": (
                (app.applied_resume_score_snapshot or {}).get("overall")
                if app.applied_resume_score_snapshot else None
            ),
        })

    total_pages = (total + page_size - 1) // page_size if total > 0 else 1

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


@router.get("/questions/{job_id}")
async def preview_job_questions(
    job_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Preview application questions for a job with pre-filled answers from answer book.

    Regression finding 182: this endpoint was returning an opaque
    HTTP 500 (plain text body, no JSON detail) for the Wiz SRE job
    across 4 consecutive calls while 3 other Greenhouse jobs
    returned 200. The symptom was reproducible but the root cause
    was hidden because (a) any raised exception here bubbled up to
    FastAPI's default 500 handler with no stack trace in logs, and
    (b) the inner `db.flush()` in `get_or_fetch_questions` caught and
    swallowed its own failure, leaving the session in an unpredictable
    state for the outer `db.commit()`.

    Defensive changes:
      1. Wrap the session-mutating section in try/except — on any
         error, rollback and return an HTTP 502 with a specific
         reason message so the on-call engineer can see what failed
         without having to hunt through traceback logs.
      2. Log exceptions with `exc_info=True` so the traceback makes
         it to the logging pipeline.
      3. The dedup/coercion in `get_or_fetch_questions` covers the
         most likely root causes (duplicate `field_key` INSERTs,
         NULL fields in cached rows).
    """
    import logging
    from app.services.question_service import get_or_fetch_questions, auto_populate_answer_book
    from app.workers.tasks._answer_prep import match_questions_to_answers

    logger = logging.getLogger(__name__)

    # Load job
    job = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Find board slug
    board = (await db.execute(
        select(CompanyATSBoard).where(
            CompanyATSBoard.company_id == job.company_id,
            CompanyATSBoard.platform == job.platform,
            CompanyATSBoard.is_active.is_(True),
        )
    )).scalar_one_or_none()
    board_slug = board.slug if board else ""

    try:
        # Get or fetch questions (cached)
        ats_questions = await get_or_fetch_questions(db, job, board_slug)

        # Auto-populate answer book
        new_entries = await auto_populate_answer_book(db, user.id, ats_questions)
        await db.commit()

        # Load answer book entries
        ab_query = select(AnswerBookEntry).where(
            AnswerBookEntry.user_id == user.id,
            or_(
                AnswerBookEntry.resume_id.is_(None),
                AnswerBookEntry.resume_id == user.active_resume_id,
            ) if user.active_resume_id else AnswerBookEntry.resume_id.is_(None),
        )
        ab_result = await db.execute(ab_query)
        ab_entries = ab_result.scalars().all()

        # Merge (resume overrides base). Convert ORM objects to plain dicts so the
        # downstream matcher (which calls .get()) works correctly.
        merged: dict[str, dict] = {}
        for entry in ab_entries:
            key = entry.question_key
            if key not in merged or entry.resume_id is not None:
                merged[key] = {
                    "question_key": entry.question_key,
                    "answer": entry.answer or "",
                    "category": entry.category or "",
                    "source": entry.source or "base",
                }

        # Match questions to answers
        matched = match_questions_to_answers(ats_questions, list(merged.values()))
    except HTTPException:
        raise
    except Exception:
        # F182: don't let arbitrary exceptions surface as opaque 500s
        # with no body. Rollback any partial writes, log the trace,
        # and return a 502 (Bad Gateway / upstream fetch failed) with
        # a specific message so the client UI can show "couldn't
        # preview questions — try again" instead of a generic crash.
        await db.rollback()
        logger.exception(
            "Failed to preview questions for job_id=%s platform=%s board=%s",
            job_id, job.platform, board_slug,
        )
        raise HTTPException(
            status_code=502,
            detail=(
                "Could not load application questions from the ATS provider. "
                "This usually means the job posting was removed or the "
                "ATS API is temporarily unavailable."
            ),
        )

    # Compute coverage
    total = len(matched)
    answered = sum(1 for m in matched if m.get("answer"))
    high_conf = sum(1 for m in matched if m.get("confidence") == "high" and m.get("answer"))

    return {
        "questions": matched,
        "coverage": {
            "total": total,
            "answered": answered,
            "high_confidence": high_conf,
            "new_entries": new_entries,
        },
    }


@router.get("/{app_id}")
async def get_application(
    app_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single application detail."""
    result = await db.execute(
        select(Application)
        .options(joinedload(Application.job), joinedload(Application.resume))
        .where(Application.id == app_id, Application.user_id == user.id)
    )
    app = result.unique().scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    # Get company name
    co_name = ""
    if app.job and app.job.company_id:
        co = (await db.execute(select(Company.name).where(Company.id == app.job.company_id))).scalar_one_or_none()
        co_name = co or ""

    return {
        "id": str(app.id),
        "job": {
            "id": str(app.job.id),
            "title": app.job.title,
            "company_name": co_name,
            "platform": app.job.platform,
            "url": app.job.url,
        },
        "resume": {
            "id": str(app.resume.id),
            "label": app.resume.label or app.resume.filename,
        },
        "status": app.status,
        "apply_method": app.apply_method,
        "prepared_answers": app.prepared_answers,
        "submitted_at": app.submitted_at.isoformat() if app.submitted_at else None,
        "applied_at": app.applied_at.isoformat() if app.applied_at else None,
        "platform_response": app.platform_response,
        "notes": app.notes,
        "created_at": app.created_at.isoformat(),
        # Feature C — apply-time snapshot. `applied_resume_text` can be
        # large (~20KB), so callers that just need the score / source
        # should read the list endpoint instead. Nullable for legacy
        # rows that predate the snapshot columns.
        "submission_source": app.submission_source,
        "applied_resume_text": app.applied_resume_text,
        "applied_resume_score_snapshot": app.applied_resume_score_snapshot,
        "ai_customization_log_id": (
            str(app.ai_customization_log_id) if app.ai_customization_log_id else None
        ),
    }


@router.patch("/{app_id}")
async def update_application(
    app_id: UUID,
    body: ApplicationUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update application status/notes."""
    app = (await db.execute(
        select(Application).where(Application.id == app_id, Application.user_id == user.id)
    )).scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    # F194: `model_dump(exclude_unset=True)` gives us exactly the fields
    # the client sent, so the partial-update semantics of the old
    # `"status" in body` checks are preserved — setting a field to
    # null on purpose is distinguishable from omitting it.
    patch = body.model_dump(exclude_unset=True)

    if "status" in patch:
        new_status = patch["status"]
        allowed = VALID_TRANSITIONS.get(app.status, [])
        if new_status not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot transition from '{app.status}' to '{new_status}'. Allowed: {allowed}",
            )
        app.status = new_status
        if new_status == "applied" and not app.applied_at:
            app.applied_at = datetime.now(timezone.utc)
        elif new_status == "submitted" and not app.submitted_at:
            app.submitted_at = datetime.now(timezone.utc)

    if "notes" in patch:
        app.notes = patch["notes"]

    if "prepared_answers" in patch and app.status == "prepared":
        app.prepared_answers = patch["prepared_answers"]

    db.add(app)
    await db.commit()

    return {"id": str(app.id), "status": app.status, "notes": app.notes, "prepared_answers": app.prepared_answers}


@router.delete("/{app_id}")
async def withdraw_application(
    app_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Withdraw an application (soft-delete — data is preserved)."""
    app = (await db.execute(
        select(Application).where(Application.id == app_id, Application.user_id == user.id)
    )).scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    app.status = "withdrawn"
    await db.commit()
    return {"status": "withdrawn", "message": "Application withdrawn (data preserved)"}
