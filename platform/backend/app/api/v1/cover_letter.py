"""Cover letter generation API."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.job import Job, JobDescription
from app.models.company import Company
from app.models.resume import Resume
from app.models.user import User
from app.api.deps import get_current_user

router = APIRouter(prefix="/cover-letter", tags=["cover-letter"])


class CoverLetterRequest(BaseModel):
    job_id: str
    resume_id: str | None = None
    tone: str = "professional"  # professional | enthusiastic | technical | conversational


@router.post("/generate")
async def generate(body: CoverLetterRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Generate an AI-tailored cover letter for a specific job."""
    # Load job + description
    job = (await db.execute(select(Job).where(Job.id == body.job_id))).scalar_one_or_none()
    if not job:
        raise HTTPException(404, "Job not found")

    company = (await db.execute(select(Company).where(Company.id == job.company_id))).scalar_one_or_none()
    company_name = company.name if company else "the company"

    desc = (await db.execute(select(JobDescription).where(JobDescription.job_id == job.id))).scalar_one_or_none()
    job_description = desc.text_content if desc else ""

    # Load resume
    resume_id = body.resume_id or user.active_resume_id
    if not resume_id:
        raise HTTPException(400, "No active resume. Upload a resume first.")

    resume = (await db.execute(select(Resume).where(Resume.id == resume_id, Resume.user_id == user.id))).scalar_one_or_none()
    if not resume:
        raise HTTPException(404, "Resume not found")
    if not resume.text_content:
        raise HTTPException(400, "Resume text not extracted yet. Wait for processing to complete.")

    # Generate
    from app.workers.tasks._cover_letter import generate_cover_letter
    result = generate_cover_letter(
        resume_text=resume.text_content,
        job_title=job.title,
        company_name=company_name,
        job_description=job_description,
        tone=body.tone,
    )

    if result.get("error"):
        raise HTTPException(500, result.get("customization_notes", "Generation failed"))

    return {
        "cover_letter": result["cover_letter"],
        "key_points": result["key_points"],
        "customization_notes": result["customization_notes"],
        "tone": result["tone"],
        "job_title": job.title,
        "company_name": company_name,
    }
