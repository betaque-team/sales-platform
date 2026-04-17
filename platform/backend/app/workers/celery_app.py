"""Celery application configuration."""

import os
from celery import Celery
from celery.schedules import crontab

# Install the secret-scrubbing logging filter before any Celery task
# imports its module-level loggers. Celery's worker process has its own
# logger tree (`celery.task`, `celery.worker`) separate from the
# FastAPI app — if we only install in main.py, worker stdout/stderr
# would still leak. Must happen BEFORE `autodiscover_tasks` below so
# that loggers created during task import inherit the filter. Mirrors
# the wiring in app/main.py; see app/utils/log_scrub.py for what's
# scrubbed.
from app.utils.log_scrub import install_root_scrubber
install_root_scrubber()

# Aggressive mode: scan frequently during initial data collection
# Set SCAN_MODE=normal in env to switch to twice-daily
SCAN_MODE = os.environ.get("SCAN_MODE", "aggressive")

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

celery_app = Celery(
    "job_platform",
    broker=REDIS_URL,
    backend=REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    result_expires=3600,
    # Regression finding 204: persist the task's positional args on the
    # result row so `AsyncResult(task_id).args` returns the original
    # inputs. `resume.py`'s `score-status` endpoint cross-validates that
    # the polled task_id was dispatched by the same resume_id in the URL
    # path — without `result_extended`, celery strips args during
    # serialization and the cross-check degrades to "ownership only".
    # Cost: one extra JSON field per result row in Redis (~30 bytes for a
    # UUID arg). Retention is capped by `result_expires=3600`.
    result_extended=True,
)

# Autodiscover tasks from the tasks subpackage
celery_app.autodiscover_tasks(["app.workers.tasks"])

# Beat schedule for recurring tasks
if SCAN_MODE == "aggressive":
    # Aggressive: scan every 30 min, career pages every hour, discovery daily
    celery_app.conf.beat_schedule = {
        "scan_all_platforms": {
            "task": "app.workers.tasks.scan_task.scan_all_platforms",
            "schedule": crontab(minute="*/30"),  # Every 30 minutes
        },
        "check_career_pages": {
            "task": "app.workers.tasks.career_page_task.check_career_pages",
            "schedule": crontab(minute=0, hour="*/1"),  # Every hour
        },
        "run_discovery": {
            "task": "app.workers.tasks.discovery_task.run_discovery",
            "schedule": crontab(minute=0, hour=0),  # Daily at midnight
        },
        "expire_stale_jobs": {
            "task": "app.workers.tasks.maintenance_task.expire_stale_jobs",
            "schedule": crontab(minute=0, hour=2),
        },
        "rescore_jobs": {
            "task": "app.workers.tasks.maintenance_task.rescore_jobs",
            "schedule": crontab(minute=0, hour=3),
        },
        # Finding 96: resume ATS scores were 11 days stale because nothing
        # scheduled a rescore. Fans out one `score_resume_task` per active
        # resume at 3:30 UTC, deliberately sequenced AFTER `rescore_jobs`
        # (3:00) so resume scores reflect the freshest relevance scores.
        "rescore_active_resumes": {
            "task": "app.workers.tasks.resume_score_task.rescore_all_active_resumes",
            "schedule": crontab(minute=30, hour=3),
        },
        "decay_scoring_signals": {
            "task": "app.workers.tasks.feedback_task.decay_scoring_signals",
            "schedule": crontab(minute=30, hour=2),
        },
        "collect_questions": {
            "task": "app.workers.tasks.question_collection_task.collect_questions",
            "schedule": crontab(minute=0, hour=4),
        },
        "enrich_target_companies": {
            "task": "app.workers.tasks.enrichment_task.enrich_target_companies_batch",
            "schedule": crontab(minute=0, hour=1),
        },
        "verify_stale_emails": {
            "task": "app.workers.tasks.enrichment_task.verify_stale_emails",
            "schedule": crontab(minute=30, hour=1),
        },
        "auto_target_companies": {
            "task": "app.workers.tasks.maintenance_task.auto_target_companies",
            "schedule": crontab(minute=15, hour=3),  # After rescore
        },
        "fix_stuck_enrichments": {
            "task": "app.workers.tasks.maintenance_task.fix_stuck_enrichments",
            "schedule": crontab(minute=45, hour="*/6"),  # Every 6 hours
        },
        # F186: sweep DiscoveryRun rows stuck pending/running >1h (API
        # dispatched but Celery was down, worker crashed mid-run, etc.)
        "fix_stuck_discovery_runs": {
            "task": "app.workers.tasks.maintenance_task.fix_stuck_discovery_runs",
            "schedule": crontab(minute=50, hour="*/6"),  # Every 6 hours, staggered from enrichment sweep
        },
        "deduplicate_contacts": {
            "task": "app.workers.tasks.enrichment_task.deduplicate_contacts",
            "schedule": crontab(minute=0, hour=2, day_of_week="sunday"),  # Weekly Sunday 2am
        },
        "nightly_backup": {
            "task": "app.workers.tasks.backup_task.run_backup",
            "schedule": crontab(minute=0, hour=3, day_of_week="*"),  # Nightly 3am UTC
            "kwargs": {"label": "nightly"},
        },
    }
else:
    # Normal: scan twice daily, career pages every 4h, discovery weekly
    celery_app.conf.beat_schedule = {
        "scan_all_platforms": {
            "task": "app.workers.tasks.scan_task.scan_all_platforms",
            "schedule": crontab(minute=0, hour="8,20"),  # 8am and 8pm UTC
        },
        "check_career_pages": {
            "task": "app.workers.tasks.career_page_task.check_career_pages",
            "schedule": crontab(minute=0, hour="*/4"),
        },
        "run_discovery": {
            "task": "app.workers.tasks.discovery_task.run_discovery",
            "schedule": crontab(minute=0, hour=0, day_of_week="sunday"),
        },
        "expire_stale_jobs": {
            "task": "app.workers.tasks.maintenance_task.expire_stale_jobs",
            "schedule": crontab(minute=0, hour=2),
        },
        "rescore_jobs": {
            "task": "app.workers.tasks.maintenance_task.rescore_jobs",
            "schedule": crontab(minute=0, hour=3),
        },
        # Finding 96: resume ATS scores were 11 days stale. Sequenced after
        # `rescore_jobs` (3:00) so resume scores reflect fresh relevance.
        "rescore_active_resumes": {
            "task": "app.workers.tasks.resume_score_task.rescore_all_active_resumes",
            "schedule": crontab(minute=30, hour=3),
        },
        "decay_scoring_signals": {
            "task": "app.workers.tasks.feedback_task.decay_scoring_signals",
            "schedule": crontab(minute=30, hour=2),
        },
        "collect_questions": {
            "task": "app.workers.tasks.question_collection_task.collect_questions",
            "schedule": crontab(minute=0, hour=4),
        },
        "enrich_target_companies": {
            "task": "app.workers.tasks.enrichment_task.enrich_target_companies_batch",
            "schedule": crontab(minute=0, hour=1),
        },
        "verify_stale_emails": {
            "task": "app.workers.tasks.enrichment_task.verify_stale_emails",
            "schedule": crontab(minute=30, hour=1),
        },
        "auto_target_companies": {
            "task": "app.workers.tasks.maintenance_task.auto_target_companies",
            "schedule": crontab(minute=15, hour=3),
        },
        "fix_stuck_enrichments": {
            "task": "app.workers.tasks.maintenance_task.fix_stuck_enrichments",
            "schedule": crontab(minute=45, hour="*/6"),
        },
        "deduplicate_contacts": {
            "task": "app.workers.tasks.enrichment_task.deduplicate_contacts",
            "schedule": crontab(minute=0, hour=2, day_of_week="sunday"),
        },
        "nightly_backup": {
            "task": "app.workers.tasks.backup_task.run_backup",
            "schedule": crontab(minute=0, hour=3),  # Nightly 3am UTC
            "kwargs": {"label": "nightly"},
        },
    }
