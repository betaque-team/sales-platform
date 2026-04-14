"""Celery task for scoring a resume against all relevant jobs."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.workers.celery_app import celery_app
from app.workers.tasks._db import SyncSession
from app.workers.tasks._ats_scoring import compute_ats_score
from app.models.resume import Resume, ResumeScore
from app.models.job import Job, JobDescription
from app.models.role_config import RoleClusterConfig


def _get_relevant_clusters_sync(session) -> list[str]:
    result = session.execute(
        select(RoleClusterConfig.name).where(
            RoleClusterConfig.is_relevant == True,
            RoleClusterConfig.is_active == True,
        )
    )
    clusters = result.scalars().all()
    return list(clusters) if clusters else ["infra", "security"]


@celery_app.task(name="app.workers.tasks.resume_score_task.score_resume_task", bind=True, max_retries=1)
def score_resume_task(self, resume_id: str):
    """Score a resume against all relevant jobs in the background."""
    session = SyncSession()
    try:
        resume = session.execute(
            select(Resume).where(Resume.id == resume_id)
        ).scalar_one_or_none()

        if not resume:
            return {"error": "Resume not found", "jobs_scored": 0}

        if resume.status != "ready":
            return {"error": "Resume not ready", "jobs_scored": 0}

        relevant_clusters = _get_relevant_clusters_sync(session)

        # Get all relevant jobs with descriptions
        jobs = session.execute(
            select(Job)
            .where(Job.role_cluster.in_(relevant_clusters))
            .order_by(Job.relevance_score.desc())
        ).scalars().all()

        if not jobs:
            return {"error": "No relevant jobs found", "jobs_scored": 0}

        total = len(jobs)
        self.update_state(state="PROGRESS", meta={"current": 0, "total": total})

        # Delete old scores
        old_scores = session.execute(
            select(ResumeScore).where(ResumeScore.resume_id == resume.id)
        ).scalars().all()
        for old in old_scores:
            session.delete(old)
        session.flush()

        # Load descriptions in bulk
        job_ids = [j.id for j in jobs]
        descriptions = {}
        if job_ids:
            desc_rows = session.execute(
                select(JobDescription).where(JobDescription.job_id.in_(job_ids))
            ).scalars().all()
            for d in desc_rows:
                descriptions[d.job_id] = d.text_content or ""

        # Score each job
        scored = 0
        for i, job in enumerate(jobs):
            desc_text = descriptions.get(job.id, "")

            result = compute_ats_score(
                resume_text=resume.text_content,
                job_title=job.title,
                matched_role=job.matched_role or "",
                role_cluster=job.role_cluster or "",
                description_text=desc_text,
            )

            score = ResumeScore(
                id=uuid.uuid4(),
                resume_id=resume.id,
                job_id=job.id,
                overall_score=result["overall_score"],
                keyword_score=result["keyword_score"],
                role_match_score=result["role_match_score"],
                format_score=result["format_score"],
                matched_keywords=result["matched_keywords"],
                missing_keywords=result["missing_keywords"],
                suggestions=result["suggestions"],
            )
            session.add(score)
            scored += 1

            # Update progress every 50 jobs
            if scored % 50 == 0:
                self.update_state(state="PROGRESS", meta={"current": scored, "total": total})
                session.flush()

        session.commit()
        return {"jobs_scored": scored, "total": total}

    except Exception as exc:
        session.rollback()
        raise self.retry(exc=exc, countdown=10)
    finally:
        session.close()
