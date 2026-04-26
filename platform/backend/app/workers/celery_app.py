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
        # Discovery scheduler fix: historically we ran `run_discovery`
        # here, which only populated the `discovered_companies` table —
        # never promoted discoveries into `company_ats_boards`, so no
        # new platforms ever got scanned without an admin manually
        # clicking "bulk import" on /discovery. Switching to the
        # auto-add variant makes discovery end-to-end: every run the
        # beat fires, up to `settings.discovery_promote_batch_size`
        # newly-discovered slugs go live as active boards and the
        # next scan cycle picks them up. The stale-board cull
        # (scan_task._STALE_BOARD_ZERO_SCAN_THRESHOLD) backstops any
        # dead slugs that slip in from the Greenhouse sitemap.
        "run_discovery": {
            "task": "app.workers.tasks.discovery_task.discover_and_add_boards",
            "schedule": crontab(minute=0, hour=0),  # Daily at midnight
        },
        # Phase-A fallback groundwork: fingerprint company websites to
        # populate `Company.careers_url` for future ATS-lockdown fallback.
        # Runs at 00:30 UTC daily — 30 min after the ATS-side discovery
        # at 00:00 to avoid two HTTP-heavy tasks hammering the VM at the
        # same time. `only_unfingerprinted=True` (the default) means this
        # is cheap once the corpus converges: the anti-join returns empty
        # when every Company.website has been fingerprinted at least once.
        # Initial-ramp math: 200/run × daily = full ~786-company corpus
        # in ~4 days. After that, only new Company rows get touched.
        "fingerprint_existing_companies": {
            "task": "app.workers.tasks.discovery_task.fingerprint_existing_companies",
            "schedule": crontab(minute=30, hour=0),
            "kwargs": {"limit": 200, "only_unfingerprinted": True},
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
        # F237: AI Intelligence twice-weekly run. Mon + Thu at 04:00
        # UTC, sequenced AFTER `rescore_jobs` (3:00),
        # `auto_target_companies` (3:15), and `rescore_active_resumes`
        # (3:30) so per-user insights see the freshest scoring +
        # target-company classifications. One Celery task produces
        # both the per-user and product insights in one run; cost
        # ~$2.60/run = ~$22/month at 50 active users.
        "weekly_ai_insights": {
            "task": "app.workers.tasks.ai_insights_task.run_weekly_insights",
            "schedule": crontab(minute=0, hour=4, day_of_week="mon,thu"),
        },
        # Funding-event auto-probe: fingerprints careers pages of
        # companies whose `funded_at` landed in the last 30 days.
        # New funding → new hiring within 60 days (leading
        # indicator); probing now puts us ahead of the public ATS
        # board appearing. 04:30 UTC on Mon + Thu — staggered 30
        # min after weekly_ai_insights so they don't pile up on
        # the same minute. See funding_followup_task.py.
        "funding_followup_probe": {
            "task": "app.workers.tasks.funding_followup_task.auto_probe_recent_funding",
            "schedule": crontab(minute=30, hour=4, day_of_week="mon,thu"),
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
        # Discovery scheduler fix: historically we ran `run_discovery`
        # here, which only populated the `discovered_companies` table —
        # never promoted discoveries into `company_ats_boards`, so no
        # new platforms ever got scanned without an admin manually
        # clicking "bulk import" on /discovery. Switching to the
        # auto-add variant makes discovery end-to-end: every run the
        # beat fires, up to `settings.discovery_promote_batch_size`
        # newly-discovered slugs go live as active boards and the
        # next scan cycle picks them up. The stale-board cull
        # (scan_task._STALE_BOARD_ZERO_SCAN_THRESHOLD) backstops any
        # dead slugs that slip in from the Greenhouse sitemap.
        "run_discovery": {
            "task": "app.workers.tasks.discovery_task.discover_and_add_boards",
            "schedule": crontab(minute=0, hour=0, day_of_week="sunday"),
        },
        # Phase-A fallback groundwork: fingerprint company websites to
        # populate `Company.careers_url`. In normal mode the full
        # platform scans run twice daily rather than every 30 min, so
        # it's safe to run fingerprinting at a weekly cadence here —
        # new companies trickle in slowly, and re-fingerprinting
        # existing ones doesn't help much without a Company.website
        # change. Sunday 01:00 UTC, an hour after the Sunday discovery
        # at 00:00, stays out of the scan window.
        "fingerprint_existing_companies": {
            "task": "app.workers.tasks.discovery_task.fingerprint_existing_companies",
            "schedule": crontab(minute=0, hour=1, day_of_week="sunday"),
            "kwargs": {"limit": 500, "only_unfingerprinted": True},
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
        # Mode-parity fix: ``fix_stuck_discovery_runs`` was only in the
        # aggressive schedule, so DiscoveryRun rows that got orphaned
        # (worker crash mid-run, beat fired into a Redis hiccup) sat in
        # 'pending'/'running' forever in normal-mode prod. Live monitoring
        # showed 2 stuck rows from 2026-04-16 still pending 10 days later,
        # blocking the discovery-runs UI list. Cadence matches aggressive
        # mode (every 6h on minute 50, staggered from enrichments).
        "fix_stuck_discovery_runs": {
            "task": "app.workers.tasks.maintenance_task.fix_stuck_discovery_runs",
            "schedule": crontab(minute=50, hour="*/6"),
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
        # F237: AI Intelligence — same schedule as aggressive mode.
        # Insight cadence is independent of scan cadence; we don't
        # want product insights computed less often in normal mode.
        "weekly_ai_insights": {
            "task": "app.workers.tasks.ai_insights_task.run_weekly_insights",
            "schedule": crontab(minute=0, hour=4, day_of_week="mon,thu"),
        },
        # Funding-event auto-probe: fingerprints careers pages of
        # companies whose `funded_at` landed in the last 30 days.
        # New funding → new hiring within 60 days (leading
        # indicator); probing now puts us ahead of the public ATS
        # board appearing. 04:30 UTC on Mon + Thu — staggered 30
        # min after weekly_ai_insights so they don't pile up on
        # the same minute. See funding_followup_task.py.
        "funding_followup_probe": {
            "task": "app.workers.tasks.funding_followup_task.auto_probe_recent_funding",
            "schedule": crontab(minute=30, hour=4, day_of_week="mon,thu"),
        },
    }
