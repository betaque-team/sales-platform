"""Match contacts to jobs based on role analysis.

Computes relevance scores for each (job, contact) pair and persists
records in the job_contact_relevance table.
"""

import logging

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.job import Job
from app.models.company_contact import CompanyContact, JobContactRelevance

logger = logging.getLogger(__name__)

# Active statuses for jobs we care about
_ACTIVE_STATUSES = {"new", "under_review", "accepted"}

# Relevance score maps per role cluster
_INFRA_SCORES: dict[str, tuple[float, str]] = {
    "cto": (0.9, "CTO - infrastructure hiring authority"),
    "vp engineering": (0.85, "VP Engineering - infrastructure leadership"),
    "vp of engineering": (0.85, "VP Engineering - infrastructure leadership"),
    "engineering director": (0.8, "Engineering Director - infrastructure oversight"),
    "director of engineering": (0.8, "Engineering Director - infrastructure oversight"),
    "platform lead": (0.75, "Platform Lead - infrastructure team lead"),
    "head of engineering": (0.75, "Head of Engineering - infrastructure authority"),
    "head of infrastructure": (0.8, "Head of Infrastructure - direct authority"),
    "head of platform": (0.75, "Head of Platform - infrastructure authority"),
    "hiring manager": (0.7, "Hiring Manager - direct hiring authority"),
    "recruiter": (0.6, "Recruiter - hiring pipeline contact"),
    "talent acquisition": (0.6, "Talent Acquisition - hiring pipeline contact"),
    "ceo": (0.5, "CEO - executive hiring authority"),
}

_SECURITY_SCORES: dict[str, tuple[float, str]] = {
    "ciso": (0.9, "CISO - security hiring authority"),
    "cto": (0.85, "CTO - security technology authority"),
    "security director": (0.8, "Security Director - security oversight"),
    "director of security": (0.8, "Security Director - security oversight"),
    "head of security": (0.8, "Head of Security - direct authority"),
    "vp engineering": (0.75, "VP Engineering - security team oversight"),
    "vp of engineering": (0.75, "VP Engineering - security team oversight"),
    "hiring manager": (0.7, "Hiring Manager - direct hiring authority"),
    "recruiter": (0.6, "Recruiter - hiring pipeline contact"),
    "talent acquisition": (0.6, "Talent Acquisition - hiring pipeline contact"),
}

# Fallback scores based on role_category and seniority
_CATEGORY_SCORES = {
    ("c_suite", "c_suite"): (0.6, "C-suite executive"),
    ("engineering_lead", "vp"): (0.7, "Engineering VP"),
    ("engineering_lead", "director"): (0.65, "Engineering Director"),
    ("engineering_lead", "manager"): (0.55, "Engineering Manager"),
    ("hiring", "director"): (0.65, "HR/Talent Director"),
    ("hiring", "manager"): (0.6, "Talent Manager"),
    ("hiring", "other"): (0.55, "Recruiter"),
}


def _score_pair(job: Job, contact: CompanyContact) -> tuple[float, str]:
    """Compute relevance score and reason for a (job, contact) pair.

    Returns (score, reason) or (0.0, "") if not relevant.
    """
    title_lower = (contact.title or "").lower()
    cluster = (job.role_cluster or "").lower()

    # Try title-based matching first
    score_map = _INFRA_SCORES if cluster == "infra" else _SECURITY_SCORES if cluster == "security" else {}

    for keyword, (score, reason) in score_map.items():
        if keyword in title_lower:
            return score, reason

    # Fallback to category + seniority
    key = (contact.role_category, contact.seniority)
    if key in _CATEGORY_SCORES:
        score, reason = _CATEGORY_SCORES[key]
        return score, f"{reason} - {cluster} role"

    return 0.0, ""


def compute_contact_relevance(session: Session, company_id) -> int:
    """Compute and store relevance of each contact to active jobs.

    Deletes old relevance records for the company first, then inserts new ones.

    Args:
        session: Sync SQLAlchemy session.
        company_id: UUID of the company.

    Returns:
        Count of relevance records created.
    """
    try:
        # Load contacts for the company
        contacts_result = session.execute(
            select(CompanyContact).where(CompanyContact.company_id == company_id)
        )
        contacts = list(contacts_result.scalars().all())

        if not contacts:
            logger.debug("No contacts for company %s, skipping relevance computation", company_id)
            return 0

        # Load active jobs for the company
        jobs_result = session.execute(
            select(Job).where(
                Job.company_id == company_id,
                Job.status.in_(list(_ACTIVE_STATUSES)),
            )
        )
        jobs = list(jobs_result.scalars().all())

        if not jobs:
            logger.debug("No active jobs for company %s, skipping relevance computation", company_id)
            return 0

        # Delete old relevance records for contacts of this company
        contact_ids = [c.id for c in contacts]
        session.execute(
            delete(JobContactRelevance).where(
                JobContactRelevance.contact_id.in_(contact_ids)
            )
        )

        # Compute and insert new relevance records
        count = 0
        for job in jobs:
            for contact in contacts:
                score, reason = _score_pair(job, contact)
                if score > 0.4:
                    record = JobContactRelevance(
                        job_id=job.id,
                        contact_id=contact.id,
                        relevance_score=score,
                        relevance_reason=reason,
                    )
                    session.add(record)
                    count += 1

        session.flush()
        logger.info(
            "Created %d relevance records for company %s (%d contacts x %d jobs)",
            count, company_id, len(contacts), len(jobs),
        )
        return count

    except Exception as exc:
        logger.warning("Contact relevance computation failed for company %s: %s", company_id, exc, exc_info=True)
        return 0
