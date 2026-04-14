"""Application tracking endpoints."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
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


@router.get("/readiness/{job_id}")
async def get_apply_readiness(
    job_id: str,
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

    # Resume score
    score_info = None
    if resume_ready:
        score = (await db.execute(
            select(ResumeScore.overall_score).where(
                ResumeScore.resume_id == user.active_resume_id,
                ResumeScore.job_id == job.id,
            )
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

    # Get resume score for this job
    score = (await db.execute(
        select(ResumeScore.overall_score).where(
            ResumeScore.resume_id == resume.id,
            ResumeScore.job_id == job.id,
        )
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
    app_id: str,
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
    job_id: str,
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
    status: str | None = None,
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
    if search:
        term = f"%{search}%"
        query = query.where(or_(Job.title.ilike(term), Company.name.ilike(term)))

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
    job_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Preview application questions for a job with pre-filled answers from answer book."""
    from app.services.question_service import get_or_fetch_questions, auto_populate_answer_book
    from app.workers.tasks._answer_prep import match_questions_to_answers

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

    # Merge (resume overrides base)
    merged = {}
    for entry in ab_entries:
        key = entry.question_key
        if key not in merged or entry.resume_id is not None:
            merged[key] = entry

    # Match questions to answers
    matched = match_questions_to_answers(ats_questions, list(merged.values()))

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
    app_id: str,
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
    }


@router.patch("/{app_id}")
async def update_application(
    app_id: str,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update application status/notes."""
    app = (await db.execute(
        select(Application).where(Application.id == app_id, Application.user_id == user.id)
    )).scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    if "status" in body:
        new_status = body["status"]
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

    if "notes" in body:
        app.notes = body["notes"]

    if "prepared_answers" in body and app.status == "prepared":
        app.prepared_answers = body["prepared_answers"]

    db.add(app)
    await db.commit()

    return {"id": str(app.id), "status": app.status, "notes": app.notes, "prepared_answers": app.prepared_answers}


@router.delete("/{app_id}")
async def withdraw_application(
    app_id: str,
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
