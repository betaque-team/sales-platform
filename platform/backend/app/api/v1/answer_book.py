"""Answer book management endpoints.

Regression finding 80: `POST /answer-book` and `PATCH /answer-book/{id}`
previously declared `body: dict`. Replaced with explicit Pydantic
`AnswerCreate` / `AnswerUpdate` schemas which cap `question` at 2 KB
and `answer` at 8 KB (matching the `_LONG_TEXT_MAX` used elsewhere),
enforce the category allowlist at parse time, and remove `source`
from the input surface entirely — the server always sets it based on
the endpoint, eliminating the provenance-spoofing footgun.
"""

import re
import uuid
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import func

from app.database import get_db
from app.models.answer_book import AnswerBookEntry
from app.models.resume import Resume
from app.models.user import User
from app.api.deps import get_current_user
from app.schemas.answer_book import AnswerCreate, AnswerUpdate

router = APIRouter(prefix="/answer-book", tags=["answer-book"])

VALID_CATEGORIES = ["personal_info", "work_auth", "experience", "skills", "preferences", "custom"]


def normalize_question_key(question: str) -> str:
    """Normalize a question into a key for matching."""
    key = question.lower().strip()
    key = re.sub(r"[^\w\s]", "", key)
    key = re.sub(r"\s+", "_", key)
    return key[:255]


@router.get("")
async def get_answer_book(
    category: str | None = None,
    resume_id: UUID | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get merged answer book entries (base + resume overrides).

    Regression finding 172: `resume_id` was previously silently dropped
    by FastAPI (the handler never declared it), so the frontend's
    `?resume_id=X` calls returned the same response as the no-param
    call — always merging base + user.active_resume_id. When a user
    wanted to review overrides for a non-active resume (e.g. while
    switching resumes, or in the resume-comparison flow), they had no
    way to get them.

    Contract now:
      - `resume_id` omitted  → base + user.active_resume_id overrides
        (unchanged, backward-compatible default)
      - `resume_id` provided → base + that resume's overrides, after
        verifying the caller owns the resume (404 otherwise — match
        the existing pattern on `create_answer`)
    """
    # Resolve the effective override resume. None ⇒ "no overrides".
    override_resume_id = None
    if resume_id is not None:
        resume = (await db.execute(
            select(Resume.id).where(Resume.id == resume_id, Resume.user_id == user.id)
        )).scalar_one_or_none()
        if not resume:
            raise HTTPException(status_code=404, detail="Resume not found")
        override_resume_id = resume_id
    elif user.active_resume_id:
        override_resume_id = user.active_resume_id

    query = select(AnswerBookEntry).where(
        AnswerBookEntry.user_id == user.id,
        or_(
            AnswerBookEntry.resume_id.is_(None),
            AnswerBookEntry.resume_id == override_resume_id,
        ) if override_resume_id else AnswerBookEntry.resume_id.is_(None),
    )
    if category:
        query = query.where(AnswerBookEntry.category == category)
    query = query.order_by(AnswerBookEntry.category, AnswerBookEntry.question)

    result = await db.execute(query)
    entries = result.scalars().all()

    # Merge: resume-specific overrides win on matching question_key
    merged: dict[str, AnswerBookEntry] = {}
    for entry in entries:
        key = entry.question_key
        if key not in merged or entry.resume_id is not None:
            merged[key] = entry

    return {
        "items": [
            {
                "id": str(e.id),
                "user_id": str(e.user_id),
                "resume_id": str(e.resume_id) if e.resume_id else None,
                "category": e.category,
                "question": e.question,
                "question_key": e.question_key,
                "answer": e.answer,
                "source": e.source,
                "is_override": e.resume_id is not None,
                "usage_count": e.usage_count,
                "created_at": e.created_at.isoformat(),
                "updated_at": e.updated_at.isoformat(),
            }
            for e in merged.values()
        ],
        "categories": VALID_CATEGORIES,
        "active_resume_id": str(user.active_resume_id) if user.active_resume_id else None,
    }


@router.post("")
async def create_answer(
    body: AnswerCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create an answer book entry."""
    # AnswerCreate has already validated: category is in the allowlist,
    # question is 1-2000 chars, answer is 0-8000 chars. Any violation
    # returned 422 before we got here.
    question = body.question.strip()
    answer = body.answer.strip()
    category = body.category
    resume_id = body.resume_id  # None for base entry

    # Verify resume ownership if resume_id provided
    if resume_id:
        resume = (await db.execute(
            select(Resume).where(Resume.id == resume_id, Resume.user_id == user.id)
        )).scalar_one_or_none()
        if not resume:
            raise HTTPException(status_code=404, detail="Resume not found")

    question_key = normalize_question_key(question)

    # Check for duplicate
    dup_query = select(AnswerBookEntry).where(
        AnswerBookEntry.user_id == user.id,
        AnswerBookEntry.question_key == question_key,
    )
    if resume_id:
        dup_query = dup_query.where(AnswerBookEntry.resume_id == resume_id)
    else:
        dup_query = dup_query.where(AnswerBookEntry.resume_id.is_(None))

    existing = (await db.execute(dup_query)).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="An entry with this question already exists")

    entry = AnswerBookEntry(
        id=uuid.uuid4(),
        user_id=user.id,
        resume_id=resume_id,
        category=category,
        question=question,
        question_key=question_key,
        answer=answer,
        # `source` is server-controlled — removed from the input schema
        # to close the provenance-spoofing footgun. Import-from-resume
        # sets `"resume_extracted"`, DELETE soft-archive sets
        # `"archived"`; user-created entries are always `"manual"`.
        source="manual",
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)

    return {
        "id": str(entry.id),
        "question": entry.question,
        "question_key": entry.question_key,
        "answer": entry.answer,
        "category": entry.category,
        "resume_id": str(entry.resume_id) if entry.resume_id else None,
    }


@router.patch("/{entry_id}")
async def update_answer(
    entry_id: str,
    body: AnswerUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update an answer book entry."""
    entry = (await db.execute(
        select(AnswerBookEntry).where(
            AnswerBookEntry.id == entry_id,
            AnswerBookEntry.user_id == user.id,
        )
    )).scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    # AnswerUpdate already validated each supplied field; fields left
    # unset (None) mean "don't touch". We use `model_fields_set` to
    # distinguish an explicit `null` (which we still treat as no-op for
    # these non-nullable DB columns) from omission.
    fields = body.model_fields_set
    if "answer" in fields and body.answer is not None:
        entry.answer = body.answer
    if "question" in fields and body.question is not None:
        entry.question = body.question
        entry.question_key = normalize_question_key(body.question)
    if "category" in fields and body.category is not None:
        entry.category = body.category

    db.add(entry)
    await db.commit()

    return {"id": str(entry.id), "answer": entry.answer, "question": entry.question}


@router.delete("/{entry_id}")
async def archive_answer(
    entry_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Archive an answer book entry (soft-delete — data is preserved)."""
    entry = (await db.execute(
        select(AnswerBookEntry).where(
            AnswerBookEntry.id == entry_id,
            AnswerBookEntry.user_id == user.id,
        )
    )).scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    entry.source = "archived"
    await db.commit()
    return {"status": "archived", "message": "Entry archived (data preserved)"}


@router.post("/import-from-resume/{resume_id}")
async def import_from_resume(
    resume_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Extract personal info from resume text into answer book base entries."""
    resume = (await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user.id)
    )).scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    text = resume.text_content or ""
    extracted = []

    # Extract email
    email_match = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text)
    if email_match:
        extracted.append(("What is your email address?", email_match.group(), "personal_info"))

    # Extract phone
    phone_match = re.search(r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}", text)
    if phone_match:
        extracted.append(("What is your phone number?", phone_match.group(), "personal_info"))

    # Extract LinkedIn
    linkedin_match = re.search(r"linkedin\.com/in/[\w-]+", text, re.IGNORECASE)
    if linkedin_match:
        extracted.append(("What is your LinkedIn URL?", f"https://{linkedin_match.group()}", "personal_info"))

    # Extract GitHub
    github_match = re.search(r"github\.com/[\w-]+", text, re.IGNORECASE)
    if github_match:
        extracted.append(("What is your GitHub URL?", f"https://{github_match.group()}", "personal_info"))

    added = 0
    for question, answer, category in extracted:
        question_key = normalize_question_key(question)
        existing = (await db.execute(
            select(AnswerBookEntry).where(
                AnswerBookEntry.user_id == user.id,
                AnswerBookEntry.question_key == question_key,
                AnswerBookEntry.resume_id.is_(None),
            )
        )).scalar_one_or_none()

        if not existing:
            db.add(AnswerBookEntry(
                id=uuid.uuid4(),
                user_id=user.id,
                resume_id=None,
                category=category,
                question=question,
                question_key=question_key,
                answer=answer,
                source="resume_extracted",
            ))
            added += 1

    await db.commit()

    return {
        "extracted": len(extracted),
        "added": added,
        "fields": [{"question": q, "answer": a} for q, a, _ in extracted],
    }


@router.get("/coverage")
async def get_coverage(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get answer book coverage stats by category and top used entries."""
    # Fetch all entries (base + active resume)
    query = select(AnswerBookEntry).where(
        AnswerBookEntry.user_id == user.id,
        or_(
            AnswerBookEntry.resume_id.is_(None),
            AnswerBookEntry.resume_id == user.active_resume_id,
        ) if user.active_resume_id else AnswerBookEntry.resume_id.is_(None),
    )
    result = await db.execute(query)
    entries = result.scalars().all()

    # Merge (resume-specific wins)
    merged: dict[str, AnswerBookEntry] = {}
    for entry in entries:
        key = entry.question_key
        if key not in merged or entry.resume_id is not None:
            merged[key] = entry

    # Category coverage
    categories: dict[str, dict] = {}
    for cat in VALID_CATEGORIES:
        categories[cat] = {"count": 0, "with_answer": 0}

    for e in merged.values():
        cat = e.category or "custom"
        if cat in categories:
            categories[cat]["count"] += 1
            if e.answer and e.answer.strip():
                categories[cat]["with_answer"] += 1

    # Top used entries
    top_used = sorted(
        [e for e in merged.values() if e.usage_count > 0],
        key=lambda e: e.usage_count,
        reverse=True,
    )[:10]

    return {
        "total_entries": len(merged),
        "categories": categories,
        "top_used": [
            {
                "question_key": e.question_key,
                "question": e.question,
                "usage_count": e.usage_count,
                "category": e.category,
            }
            for e in top_used
        ],
    }
