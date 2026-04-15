"""Resume upload, ATS scoring, and AI customization endpoints."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.database import get_db
from app.models.resume import Resume, ResumeScore
from app.models.job import Job, JobDescription
from app.models.user import User
from app.models.role_config import RoleClusterConfig
from app.api.deps import get_current_user
from app.schemas.resume import CustomizeRequest
from app.workers.tasks._resume_parser import extract_text
from app.workers.tasks._ats_scoring import compute_ats_score
from app.utils.sql import escape_like


async def _get_relevant_clusters(db: AsyncSession) -> list[str]:
    """Get role clusters marked as relevant."""
    result = await db.execute(
        select(RoleClusterConfig.name).where(
            RoleClusterConfig.is_relevant == True,
            RoleClusterConfig.is_active == True,
        )
    )
    clusters = result.scalars().all()
    return list(clusters) if clusters else ["infra", "security"]

router = APIRouter(prefix="/resume", tags=["resume"])

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
MIN_FILE_SIZE = 256  # bytes — anything smaller can't be a real resume
ALLOWED_TYPES = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
}

# Minimum number of words we need to pull out of a file to call it a usable
# resume. Below this we assume extraction failed (scanned PDF, corrupt DOCX,
# plain-text-renamed-to-.pdf) and reject the upload outright rather than
# persisting a broken row with status="error".
MIN_WORD_COUNT = 50


@router.post("/upload")
async def upload_resume(
    file: UploadFile = File(...),
    label: str = "",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload a resume (PDF or DOCX) and extract text."""
    # Validate file type
    content_type = file.content_type or ""
    file_type = ALLOWED_TYPES.get(content_type)
    if not file_type:
        # Try extension fallback
        filename = file.filename or ""
        if filename.lower().endswith(".pdf"):
            file_type = "pdf"
        elif filename.lower().endswith(".docx"):
            file_type = "docx"
        else:
            raise HTTPException(status_code=400, detail="Only PDF and DOCX files are accepted")

    # Read file
    file_bytes = await file.read()
    if len(file_bytes) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if len(file_bytes) < MIN_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail="File is too small to be a valid resume",
        )
    if len(file_bytes) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File size exceeds 5MB limit")

    # Magic-byte check so a plain .txt renamed to .pdf (or a random binary
    # with a .pdf extension) gets rejected here instead of silently failing
    # text extraction downstream and leaving behind a status="error" row.
    header = file_bytes[:4]
    if file_type == "pdf" and not file_bytes[:5] == b"%PDF-":
        raise HTTPException(
            status_code=400,
            detail="File is not a valid PDF (missing %PDF header)",
        )
    if file_type == "docx" and header != b"PK\x03\x04":
        # DOCX is a ZIP package; real DOCX files start with the PK ZIP header.
        raise HTTPException(
            status_code=400,
            detail="File is not a valid DOCX (missing ZIP header)",
        )

    # Extract text
    text_content = extract_text(file_bytes, file_type)
    word_count = len(text_content.split()) if text_content else 0

    # Reject at the API boundary instead of persisting a broken row. Prior
    # behaviour (status="error" rows in the DB) caused DB clutter and
    # misleading UX — the user sees an upload succeed and then wonders why
    # scoring never runs.
    if word_count < MIN_WORD_COUNT:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Could not extract readable text from the file "
                f"(got {word_count} words, need at least {MIN_WORD_COUNT}). "
                f"Please upload a text-based (not scanned) PDF or DOCX."
            ),
        )

    resume = Resume(
        id=uuid.uuid4(),
        user_id=user.id,
        label=label or (file.filename or "resume").rsplit(".", 1)[0],
        filename=file.filename or "resume",
        file_type=file_type,
        text_content=text_content,
        word_count=word_count,
        status="ready",
    )
    db.add(resume)
    await db.flush()  # flush to DB so FK constraint is satisfied

    # Auto-set as active if this is the user's first resume
    if not user.active_resume_id:
        user.active_resume_id = resume.id
        db.add(user)

    await db.commit()
    await db.refresh(resume)

    # Regression finding 96: kick off scoring automatically on upload.
    # Before this hook, `status=ready` was the ONLY signal we gave back
    # and the user had to find and click the manual "Rescore" button on
    # the Resume Score page before any `ResumeScore` rows existed. For
    # the 11 days prior to this fix, that meant a brand-new upload
    # showed `jobs_scored=0` until someone noticed. Fire-and-forget: the
    # task has its own transaction + delete-and-replace semantics, so a
    # failed dispatch (redis down, worker offline) still leaves the
    # `Resume` row valid and the nightly beat schedule
    # (`rescore_all_active_resumes`) will catch up.
    try:
        from app.workers.tasks.resume_score_task import score_resume_task
        score_resume_task.delay(str(resume.id))
    except Exception:
        # Deliberately swallowed: upload succeeded, scoring is a
        # best-effort kicker. The nightly beat catches stragglers.
        pass

    return {
        "id": str(resume.id),
        "label": resume.label,
        "filename": resume.filename,
        "file_type": resume.file_type,
        "word_count": resume.word_count,
        "status": resume.status,
        "uploaded_at": resume.uploaded_at.isoformat(),
        "text_preview": text_content[:500] if text_content else "",
        "is_active": str(user.active_resume_id) == str(resume.id),
    }


@router.post("/switch/{resume_id}")
async def switch_active_resume(
    resume_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Switch the user's active resume/persona."""
    result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user.id)
    )
    resume = result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    user.active_resume_id = resume.id
    db.add(user)
    await db.commit()

    return {
        "active_resume_id": str(resume.id),
        "label": resume.label,
        "message": f"Switched to '{resume.label or resume.filename}'",
    }


@router.post("/clear-active")
async def clear_active_resume(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Clear the user's active resume (exit persona mode)."""
    user.active_resume_id = None
    db.add(user)
    await db.commit()
    return {"active_resume_id": None, "message": "Active resume cleared"}


@router.get("/active")
async def get_active_resume(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the user's active resume details with score summary."""
    if not user.active_resume_id:
        return {"active_resume": None}

    result = await db.execute(
        select(Resume).where(Resume.id == user.active_resume_id, Resume.user_id == user.id)
    )
    resume = result.scalar_one_or_none()
    if not resume:
        return {"active_resume": None}

    # Score summary for this resume
    score_stats = (await db.execute(
        select(
            func.count(ResumeScore.id),
            func.avg(ResumeScore.overall_score),
            func.max(ResumeScore.overall_score),
        ).where(ResumeScore.resume_id == resume.id)
    )).one()

    above_70 = (await db.execute(
        select(func.count(ResumeScore.id))
        .where(ResumeScore.resume_id == resume.id, ResumeScore.overall_score >= 70)
    )).scalar() or 0

    return {
        "active_resume": {
            "id": str(resume.id),
            "label": resume.label,
            "filename": resume.filename,
            "file_type": resume.file_type,
            "word_count": resume.word_count,
            "status": resume.status,
            "uploaded_at": resume.uploaded_at.isoformat(),
            "score_summary": {
                "jobs_scored": score_stats[0] or 0,
                "average_score": round(float(score_stats[1]), 1) if score_stats[1] else 0.0,
                "best_score": round(float(score_stats[2]), 1) if score_stats[2] else 0.0,
                "above_70": above_70,
            },
        }
    }


@router.patch("/{resume_id}/label")
async def update_resume_label(
    resume_id: str,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a resume's display label."""
    result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user.id)
    )
    resume = result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    label = body.get("label", "").strip()
    if not label:
        raise HTTPException(status_code=400, detail="Label cannot be empty")

    resume.label = label[:100]
    db.add(resume)
    await db.commit()

    return {"id": str(resume.id), "label": resume.label}


@router.get("")
async def list_resumes(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    all_users: bool = False,
):
    """List resumes. Admin/super_admin can pass ?all_users=true to see all."""
    query = select(Resume).where(Resume.status != "archived")
    if all_users and user.role in ("admin", "super_admin"):
        # Admin sees all resumes across users
        query = query.options(joinedload(Resume.owner))
    else:
        query = query.where(Resume.user_id == user.id)
    query = query.order_by(Resume.uploaded_at.desc())

    result = await db.execute(query)
    resumes = result.unique().scalars().all()
    return {
        "items": [
            {
                "id": str(r.id),
                "label": r.label,
                "filename": r.filename,
                "file_type": r.file_type,
                "word_count": r.word_count,
                "status": r.status,
                "uploaded_at": r.uploaded_at.isoformat(),
                "is_active": str(user.active_resume_id) == str(r.id) if user.active_resume_id else False,
                **({"owner_name": r.owner.name, "owner_email": r.owner.email}
                   if all_users and user.role in ("admin", "super_admin") and hasattr(r, "owner") and r.owner else {}),
            }
            for r in resumes
        ],
        "active_resume_id": str(user.active_resume_id) if user.active_resume_id else None,
    }


@router.delete("/{resume_id}")
async def archive_resume(
    resume_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Archive a resume (soft-delete — data is preserved)."""
    result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user.id)
    )
    resume = result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    resume.status = "archived"
    # Clear active if this was the active resume
    if user.active_resume_id and str(user.active_resume_id) == str(resume.id):
        user.active_resume_id = None
    await db.commit()
    return {"status": "archived", "message": "Resume archived (data preserved)"}


@router.post("/{resume_id}/score")
async def score_resume(
    resume_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Dispatch background task to score resume against ALL relevant jobs."""
    from app.workers.tasks.resume_score_task import score_resume_task

    result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user.id)
    )
    resume = result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    if resume.status != "ready":
        raise HTTPException(status_code=400, detail="Resume text extraction failed. Please upload a text-based PDF or DOCX.")

    # Dispatch to Celery
    task = score_resume_task.delay(str(resume.id))

    return {
        "task_id": task.id,
        "resume_id": str(resume.id),
        "status": "scoring",
        "message": "Scoring against all relevant jobs. This may take a moment.",
    }


@router.get("/{resume_id}/score-status/{task_id}")
async def get_score_task_status(
    resume_id: str,
    task_id: str,
    user: User = Depends(get_current_user),
):
    """Poll the status of a resume scoring task."""
    from celery.result import AsyncResult
    result = AsyncResult(task_id)

    if result.state == "PENDING":
        return {"status": "pending", "current": 0, "total": 0}
    elif result.state == "PROGRESS":
        info = result.info or {}
        return {"status": "progress", "current": info.get("current", 0), "total": info.get("total", 0)}
    elif result.state == "SUCCESS":
        info = result.result or {}
        return {
            "status": "completed",
            "jobs_scored": info.get("jobs_scored", 0),
            "total": info.get("total", 0),
            "error": info.get("error"),
        }
    elif result.state == "FAILURE":
        return {"status": "failed", "error": str(result.info)}
    else:
        return {"status": result.state.lower()}


@router.get("/{resume_id}/scores")
async def get_resume_scores(
    resume_id: str,
    page: int = 1,
    page_size: int = 25,
    role_cluster: str | None = None,
    min_score: float | None = None,
    max_score: float | None = None,
    search: str | None = None,
    sort_by: str = "overall_score",
    sort_dir: str = "desc",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get previously computed scores for a resume with pagination and filters."""
    result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user.id)
    )
    resume = result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    from app.models.company import Company

    # Build query with joins for filtering (join Company for search/sort)
    base_query = (
        select(ResumeScore, Job, Company.name.label("co_name"))
        .join(Job, ResumeScore.job_id == Job.id)
        .join(Company, Job.company_id == Company.id)
        .where(ResumeScore.resume_id == resume.id)
    )

    # Apply filters
    if role_cluster:
        base_query = base_query.where(Job.role_cluster == role_cluster)
    if min_score is not None:
        base_query = base_query.where(ResumeScore.overall_score >= min_score)
    if max_score is not None:
        base_query = base_query.where(ResumeScore.overall_score <= max_score)
    if search and search.strip():
        # Findings 84+85: escape LIKE metachars + drop whitespace-only input
        # so `"100%"`, `"dev_ops"`, and `"   "` no longer return wildcard
        # matches in the resume-score search.
        search_term = f"%{escape_like(search.strip())}%"
        base_query = base_query.where(
            (Job.title.ilike(search_term, escape="\\"))
            | (Company.name.ilike(search_term, escape="\\"))
        )

    # Get total count (unfiltered for summary stats)
    all_scores_result = await db.execute(
        select(func.count(ResumeScore.id), func.avg(ResumeScore.overall_score))
        .where(ResumeScore.resume_id == resume.id)
    )
    all_row = all_scores_result.one()
    total_all = all_row[0] or 0
    avg_score_all = float(all_row[1]) if all_row[1] else 0.0

    # Get filtered count
    count_query = select(func.count()).select_from(base_query.subquery())
    total_filtered = (await db.execute(count_query)).scalar() or 0

    # Sort
    sort_col = {
        "overall_score": ResumeScore.overall_score,
        "keyword_score": ResumeScore.keyword_score,
        "role_match_score": ResumeScore.role_match_score,
        "format_score": ResumeScore.format_score,
        "job_title": Job.title,
        "company_name": Company.name,
    }.get(sort_by, ResumeScore.overall_score)

    if sort_dir == "asc":
        base_query = base_query.order_by(sort_col.asc())
    else:
        base_query = base_query.order_by(sort_col.desc())

    # Paginate
    offset = (page - 1) * page_size
    paginated_query = base_query.offset(offset).limit(page_size)

    rows = (await db.execute(paginated_query)).all()

    scores = []
    for score_record, job, co_name in rows:
        scores.append({
            "id": str(score_record.id),
            "job_id": str(score_record.job_id),
            "job_title": job.title,
            "company_name": co_name or "",
            "role_cluster": job.role_cluster or "",
            "overall_score": score_record.overall_score,
            "keyword_score": score_record.keyword_score,
            "role_match_score": score_record.role_match_score,
            "format_score": score_record.format_score,
            "matched_keywords": score_record.matched_keywords,
            "missing_keywords": score_record.missing_keywords,
            "suggestions": score_record.suggestions,
            "scored_at": score_record.scored_at.isoformat(),
        })

    # Get score distribution for summary (from all scores, not filtered)
    above_70 = (await db.execute(
        select(func.count(ResumeScore.id))
        .where(ResumeScore.resume_id == resume.id, ResumeScore.overall_score >= 70)
    )).scalar() or 0

    best_score = (await db.execute(
        select(func.max(ResumeScore.overall_score))
        .where(ResumeScore.resume_id == resume.id)
    )).scalar() or 0

    # Top missing keywords (from all scores)
    all_missing_result = await db.execute(
        select(ResumeScore.missing_keywords)
        .where(ResumeScore.resume_id == resume.id)
    )
    all_missing: dict[str, int] = {}
    for (mkw,) in all_missing_result:
        if mkw:
            for kw in mkw:
                all_missing[kw] = all_missing.get(kw, 0) + 1
    top_missing = [kw for kw, _ in sorted(all_missing.items(), key=lambda x: -x[1])[:10]]

    total_pages = (total_filtered + page_size - 1) // page_size if total_filtered > 0 else 1

    return {
        "resume_id": str(resume.id),
        "scores": scores,
        "average_score": round(avg_score_all, 1),
        "best_score": round(best_score, 1),
        "above_70": above_70,
        "top_missing_keywords": top_missing,
        "jobs_scored": total_all,
        "total_filtered": total_filtered,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


@router.get("/ai-usage")
async def get_ai_usage(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get current user's AI customization usage for today."""
    from app.models.resume import AICustomizationLog
    from app.config import get_settings

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    used_today = (await db.execute(
        select(func.count(AICustomizationLog.id))
        .where(
            AICustomizationLog.user_id == user.id,
            AICustomizationLog.created_at >= today_start,
        )
    )).scalar() or 0

    settings = get_settings()
    return {
        "used_today": used_today,
        "daily_limit": settings.ai_daily_limit_per_user,
        "remaining": max(0, settings.ai_daily_limit_per_user - used_today),
        "has_api_key": bool(settings.anthropic_api_key),
    }


@router.post("/{resume_id}/customize")
async def customize_resume_for_job(
    resume_id: str,
    body: CustomizeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """AI-powered resume customization for a specific job.

    Body: { job_id: UUID, target_score: int (60-95, default 85) }

    Regression finding 90: previously `body: dict` with a manual
    `if not (60 <= target_score <= 95)` guard. A string value such as
    `target_score="high"` raised a `TypeError` inside the comparison
    that surfaced as a 500. `CustomizeRequest` now enforces the bounds
    at parse time (Pydantic returns 422 on bad input) so the request
    never reaches the handler with a non-int target_score.
    """
    from app.workers.tasks._ai_resume import customize_resume
    from app.models.resume import AICustomizationLog
    from app.config import get_settings

    # `job_id` comes out of Pydantic as `UUID`; downstream code
    # (SQLAlchemy `.where(Job.id == job_id)`) accepts UUID directly,
    # but the `.delay(str(job_id), …)` call into Celery serializes a
    # string, so we normalize once here.
    job_id = body.job_id
    target_score = body.target_score

    # Check daily limit
    settings = get_settings()
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    used_today = (await db.execute(
        select(func.count(AICustomizationLog.id))
        .where(
            AICustomizationLog.user_id == user.id,
            AICustomizationLog.created_at >= today_start,
        )
    )).scalar() or 0

    if used_today >= settings.ai_daily_limit_per_user:
        raise HTTPException(
            status_code=429,
            detail=f"Daily AI customization limit reached ({settings.ai_daily_limit_per_user}/day). Resets at midnight UTC."
        )

    # Load resume
    result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user.id)
    )
    resume = result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    # Load job
    job = (await db.execute(
        select(Job).options(joinedload(Job.description)).where(Job.id == job_id)
    )).unique().scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Restrict to relevant jobs only
    relevant_clusters = await _get_relevant_clusters(db)
    if job.role_cluster not in relevant_clusters:
        raise HTTPException(
            status_code=400,
            detail="AI resume customization is only available for relevant jobs (infra, security, etc.)"
        )

    # Get existing score if available
    existing_score = (await db.execute(
        select(ResumeScore).where(
            ResumeScore.resume_id == resume.id,
            ResumeScore.job_id == job.id,
        )
    )).scalar_one_or_none()

    matched_keywords = existing_score.matched_keywords if existing_score else []
    missing_keywords = existing_score.missing_keywords if existing_score else []

    # If no existing score, compute one
    if not existing_score:
        desc_text = job.description.text_content if job.description else ""
        ats_result = compute_ats_score(
            resume_text=resume.text_content,
            job_title=job.title,
            matched_role=job.matched_role,
            role_cluster=job.role_cluster,
            description_text=desc_text,
        )
        matched_keywords = ats_result["matched_keywords"]
        missing_keywords = ats_result["missing_keywords"]

    desc_text = job.description.text_content if job.description else ""

    # Call AI customization
    ai_result = customize_resume(
        resume_text=resume.text_content,
        job_title=job.title,
        job_description=desc_text,
        matched_keywords=matched_keywords,
        missing_keywords=missing_keywords,
        target_score=target_score,
    )

    # Log usage
    log_entry = AICustomizationLog(
        user_id=user.id,
        resume_id=resume.id,
        job_id=job.id,
        input_tokens=ai_result.get("input_tokens", 0),
        output_tokens=ai_result.get("output_tokens", 0),
        success=not ai_result.get("error", False),
    )
    db.add(log_entry)
    await db.commit()

    return {
        "resume_id": str(resume.id),
        "job_id": str(job.id),
        "job_title": job.title,
        "target_score": target_score,
        "customized_text": ai_result["customized_text"],
        "changes_made": ai_result["changes_made"],
        "improvement_notes": ai_result["improvement_notes"],
        "error": ai_result.get("error", False),
        "usage": {
            "used_today": used_today + 1,
            "daily_limit": settings.ai_daily_limit_per_user,
            "remaining": max(0, settings.ai_daily_limit_per_user - used_today - 1),
        },
    }
