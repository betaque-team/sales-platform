"""Celery task registry -- import all tasks so autodiscovery picks them up."""

from app.workers.tasks.scan_task import scan_all_platforms, scan_single_company
from app.workers.tasks.career_page_task import check_career_pages
from app.workers.tasks.discovery_task import run_discovery
from app.workers.tasks.maintenance_task import (
    expire_stale_jobs, rescore_jobs,
    reclassify_and_rescore, auto_target_companies, fix_stuck_enrichments,
)
from app.workers.tasks.enrichment_task import enrich_company, enrich_target_companies_batch, verify_stale_emails
from app.workers.tasks.resume_score_task import score_resume_task
from app.workers.tasks.feedback_task import process_review_feedback_task, decay_scoring_signals
from app.workers.tasks.question_collection_task import collect_questions

__all__ = [
    "scan_all_platforms",
    "scan_single_company",
    "check_career_pages",
    "run_discovery",
    "expire_stale_jobs",
    "rescore_jobs",
    "enrich_company",
    "score_resume_task",
    "process_review_feedback_task",
    "decay_scoring_signals",
    "collect_questions",
    "enrich_target_companies_batch",
    "verify_stale_emails",
    "reclassify_and_rescore",
    "auto_target_companies",
    "fix_stuck_enrichments",
]
