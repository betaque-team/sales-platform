"""Maintenance tasks -- job expiration, re-scoring, and data quality."""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update, func

from app.workers.celery_app import celery_app
from app.workers.tasks._db import SyncSession
from app.workers.tasks._scoring import compute_relevance_score
from app.workers.tasks._role_matching import (
    match_role_with_config, classify_geography, load_cluster_config_sync,
)
from app.models.company import Company
from app.models.job import Job, JobDescription
from app.models.scoring_signal import ScoringSignal
from app.models.discovery import DiscoveryRun
from app.workers.tasks._feedback import get_feedback_adjustment
from app.utils.job_description import extract_description

logger = logging.getLogger(__name__)

# Jobs not seen in this many days are marked expired
STALE_THRESHOLD_DAYS = 14


@celery_app.task(name="app.workers.tasks.maintenance_task.expire_stale_jobs")
def expire_stale_jobs():
    """Mark jobs not seen in the last 14 days as expired."""
    logger.info("Starting expire_stale_jobs")
    session = SyncSession()

    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=STALE_THRESHOLD_DAYS)

        result = session.execute(
            update(Job)
            .where(
                Job.status.in_(["new", "under_review"]),
                Job.last_seen_at < cutoff,
            )
            .values(
                status="expired",
                expired_at=datetime.now(timezone.utc),
            )
        )
        expired_count = result.rowcount
        session.commit()

        logger.info("expire_stale_jobs complete: %d jobs expired", expired_count)
        return {"expired": expired_count}

    except Exception as e:
        logger.exception("expire_stale_jobs failed: %s", e)
        session.rollback()
        raise
    finally:
        session.close()


@celery_app.task(name="app.workers.tasks.maintenance_task.rescore_jobs")
def rescore_jobs():
    """Recalculate relevance_score for all active (non-expired, non-archived) jobs."""
    logger.info("Starting rescore_jobs")
    session = SyncSession()

    try:
        active_statuses = ["new", "under_review", "accepted"]
        jobs = session.execute(
            select(Job).where(Job.status.in_(active_statuses))
        ).scalars().all()

        # Pre-fetch all companies in a single query for efficiency
        company_ids = {j.company_id for j in jobs}
        companies = {}
        if company_ids:
            rows = session.execute(
                select(Company).where(Company.id.in_(company_ids))
            ).scalars().all()
            companies = {c.id: c for c in rows}

        # Preload scoring signals for feedback adjustments
        signal_rows = session.execute(select(ScoringSignal)).scalars().all()
        signals_cache = {s.signal_key: s.weight for s in signal_rows}

        # Build approved roles set from cluster config
        from app.workers.tasks._role_matching import load_cluster_config_sync
        cluster_config = load_cluster_config_sync(session)
        approved_roles_set = set()
        for cfg in cluster_config.values():
            for role in cfg["approved_roles"]:
                approved_roles_set.add(role.lower())

        rescored = 0
        for job in jobs:
            company = companies.get(job.company_id)
            is_target = company.is_target if company else False
            feedback_adj = get_feedback_adjustment(job, signals_cache)

            new_score = compute_relevance_score(
                title=job.title,
                matched_role=job.matched_role,
                role_cluster=job.role_cluster,
                is_target=is_target,
                geography_bucket=job.geography_bucket,
                remote_scope=job.remote_scope,
                platform=job.platform,
                posted_at=job.posted_at,
                approved_roles_set=approved_roles_set if approved_roles_set else None,
                feedback_adjustment=feedback_adj,
            )

            if job.relevance_score != new_score:
                job.relevance_score = new_score
                rescored += 1

        session.commit()

        logger.info(
            "rescore_jobs complete: %d active jobs checked, %d rescored",
            len(jobs), rescored,
        )
        return {"checked": len(jobs), "rescored": rescored}

    except Exception as e:
        logger.exception("rescore_jobs failed: %s", e)
        session.rollback()
        raise
    finally:
        session.close()


@celery_app.task(name="app.workers.tasks.maintenance_task.reclassify_and_rescore")
def reclassify_and_rescore():
    """Re-run role matching, geography classification, and scoring for all active jobs.

    Unlike rescore_jobs which only recalculates scores, this re-runs the full
    classification pipeline with updated keywords/roles/geography signals.
    """
    logger.info("Starting reclassify_and_rescore")
    session = SyncSession()

    try:
        cluster_config = load_cluster_config_sync(session)

        active_statuses = ["new", "under_review", "accepted"]
        jobs = session.execute(
            select(Job).where(Job.status.in_(active_statuses))
        ).scalars().all()

        company_ids = {j.company_id for j in jobs}
        companies = {}
        if company_ids:
            rows = session.execute(
                select(Company).where(Company.id.in_(company_ids))
            ).scalars().all()
            companies = {c.id: c for c in rows}

        # Build approved roles set
        approved_roles_set = set()
        for cfg in cluster_config.values():
            for role in cfg["approved_roles"]:
                approved_roles_set.add(role.lower())

        signal_rows = session.execute(select(ScoringSignal)).scalars().all()
        signals_cache = {s.signal_key: s.weight for s in signal_rows}

        reclassified = 0
        rescored = 0

        for job in jobs:
            # Re-run role matching
            role_match = match_role_with_config(job.title, cluster_config)
            new_cluster = role_match["role_cluster"]
            new_matched_role = role_match["matched_role"]
            new_title_norm = role_match["title_normalized"]

            # Re-run geography classification
            new_geo = classify_geography(job.location_raw or "", job.remote_scope or "")

            cluster_changed = new_cluster != (job.role_cluster or "")
            geo_changed = new_geo != (job.geography_bucket or "")

            if cluster_changed or geo_changed:
                job.role_cluster = new_cluster
                job.matched_role = new_matched_role
                job.title_normalized = new_title_norm
                job.geography_bucket = new_geo
                reclassified += 1

            # Rescore
            company = companies.get(job.company_id)
            is_target = company.is_target if company else False
            feedback_adj = get_feedback_adjustment(job, signals_cache)

            new_score = compute_relevance_score(
                title=job.title,
                matched_role=new_matched_role,
                role_cluster=new_cluster,
                is_target=is_target,
                geography_bucket=new_geo,
                remote_scope=job.remote_scope,
                platform=job.platform,
                posted_at=job.posted_at,
                approved_roles_set=approved_roles_set if approved_roles_set else None,
                feedback_adjustment=feedback_adj,
            )

            if job.relevance_score != new_score:
                job.relevance_score = new_score
                rescored += 1

        session.commit()

        logger.info(
            "reclassify_and_rescore complete: %d jobs, %d reclassified, %d rescored",
            len(jobs), reclassified, rescored,
        )
        return {"checked": len(jobs), "reclassified": reclassified, "rescored": rescored}

    except Exception as e:
        logger.exception("reclassify_and_rescore failed: %s", e)
        session.rollback()
        raise
    finally:
        session.close()


@celery_app.task(name="app.workers.tasks.maintenance_task.backfill_job_descriptions")
def backfill_job_descriptions(batch_size: int = 500, max_jobs: int | None = None):
    """Populate JobDescription rows for historical jobs that never had one.

    Regression finding 101: the scan pipeline only started writing
    ``JobDescription`` rows in a recent round, so historical Job rows
    have ``raw_json`` populated but no companion description row. The
    resume scorer's online raw_json fallback (F97) covers this at
    scoring time, but every read path that joins JobDescription
    (``/jobs/{id}/description``, the JD-text-only ATS test harness)
    sees empty rows. This task walks the gap once: for every Job
    whose ``raw_json`` is non-null and whose ``id`` doesn't appear in
    ``job_descriptions``, parse the raw_json via the same
    ``extract_description`` helper the scan pipeline uses and merge
    a JobDescription row.

    Idempotent — re-runs are safe because the WHERE clause filters
    out anything that already has a row. Batched to keep a single
    transaction's write set bounded (``batch_size`` jobs per
    commit). ``max_jobs`` lets ops cap a one-shot run for a smoke
    test before unleashing the full sweep.

    Returns ``{"backfilled": int, "skipped_no_text": int, "scanned": int}``
    so admins can see what landed and what couldn't be backfilled
    (raw_json present but extractor returned empty — usually means
    the platform mapping in ``extract_description`` doesn't cover
    that row's shape, which is a separate finding).
    """
    logger.info("Starting backfill_job_descriptions (batch_size=%d max_jobs=%s)",
                batch_size, max_jobs)
    session = SyncSession()
    try:
        # IDs that already have a description — exclude them from the
        # scan. One IN-list lookup per batch is cheap; doing it inside
        # the per-job loop would N+1 across the whole table.
        existing_subq = select(JobDescription.job_id).subquery()

        scanned = 0
        backfilled = 0
        skipped_no_text = 0

        while True:
            if max_jobs is not None and scanned >= max_jobs:
                break
            # Limit to the batch size, ordered by oldest first so
            # repeated invocations make consistent forward progress.
            limit = batch_size
            if max_jobs is not None:
                limit = min(limit, max_jobs - scanned)
            jobs = session.execute(
                select(Job)
                .where(
                    Job.raw_json.isnot(None),
                    Job.id.notin_(select(existing_subq.c.job_id)),
                )
                .order_by(Job.first_seen_at.asc())
                .limit(limit)
            ).scalars().all()
            if not jobs:
                break

            now = datetime.now(timezone.utc)
            for job in jobs:
                scanned += 1
                html_content, text_content = extract_description(
                    job.platform or "", job.raw_json or {}
                )
                if not text_content and not html_content:
                    # Extractor couldn't parse this row — log and skip.
                    # The scoring fallback handles this case at scoring
                    # time, but persisting an empty row would mask the
                    # gap from monitoring (F101 explicitly wants a
                    # `has_description` signal).
                    skipped_no_text += 1
                    continue
                word_count = len(text_content.split()) if text_content else 0
                session.add(
                    JobDescription(
                        id=uuid.uuid4(),
                        job_id=job.id,
                        html_content=html_content,
                        text_content=text_content,
                        word_count=word_count,
                        fetched_at=now,
                    )
                )
                backfilled += 1

            session.commit()
            logger.info(
                "backfill_job_descriptions: batch done — scanned=%d backfilled=%d skipped=%d",
                scanned, backfilled, skipped_no_text,
            )

        logger.info(
            "backfill_job_descriptions complete: scanned=%d backfilled=%d skipped_no_text=%d",
            scanned, backfilled, skipped_no_text,
        )
        return {
            "scanned": scanned,
            "backfilled": backfilled,
            "skipped_no_text": skipped_no_text,
        }
    except Exception as e:
        logger.exception("backfill_job_descriptions failed: %s", e)
        session.rollback()
        raise
    finally:
        session.close()


@celery_app.task(name="app.workers.tasks.maintenance_task.auto_target_companies")
def auto_target_companies():
    """Mark companies as targets if they have 2+ relevant (clustered) active jobs.

    This ensures companies actively hiring for infra/security roles get higher
    scoring weight (company_fit_score: 1.0 vs 0.3).
    """
    logger.info("Starting auto_target_companies")
    session = SyncSession()

    try:
        # Find companies with 2+ clustered active jobs
        active_statuses = ["new", "under_review", "accepted"]
        result = session.execute(
            select(Job.company_id, func.count(Job.id))
            .where(
                Job.status.in_(active_statuses),
                Job.role_cluster != "",
                Job.role_cluster.isnot(None),
            )
            .group_by(Job.company_id)
            .having(func.count(Job.id) >= 2)
        )
        qualifying_ids = [row[0] for row in result]

        if not qualifying_ids:
            logger.info("auto_target_companies: no qualifying companies")
            return {"targeted": 0}

        # Mark these as targets (don't un-target existing manual targets)
        updated = session.execute(
            update(Company)
            .where(
                Company.id.in_(qualifying_ids),
                Company.is_target.is_(False),
            )
            .values(is_target=True)
        )
        count = updated.rowcount
        session.commit()

        logger.info("auto_target_companies: %d companies targeted (%d qualifying)",
                     count, len(qualifying_ids))
        return {"targeted": count, "qualifying": len(qualifying_ids)}

    except Exception as e:
        logger.exception("auto_target_companies failed: %s", e)
        session.rollback()
        raise
    finally:
        session.close()


@celery_app.task(name="app.workers.tasks.maintenance_task.fix_stuck_enrichments")
def fix_stuck_enrichments():
    """Reset companies stuck in 'enriching' status for more than 1 hour."""
    logger.info("Starting fix_stuck_enrichments")
    session = SyncSession()

    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)

        result = session.execute(
            update(Company)
            .where(
                Company.enrichment_status == "enriching",
                Company.updated_at < cutoff,
            )
            .values(
                enrichment_status="pending",
                enrichment_error="Reset from stuck enriching state",
            )
        )
        count = result.rowcount
        session.commit()

        logger.info("fix_stuck_enrichments: %d companies reset", count)
        return {"reset": count}

    except Exception as e:
        logger.exception("fix_stuck_enrichments failed: %s", e)
        session.rollback()
        raise
    finally:
        session.close()


@celery_app.task(name="app.workers.tasks.maintenance_task.fix_stuck_discovery_runs")
def fix_stuck_discovery_runs():
    """Sweep DiscoveryRun rows stuck in 'pending' or 'running' for >1 hour.

    Regression finding 186: before the API/worker wiring fix, any
    ``POST /discovery/runs`` call left a 'pending' row orphaned
    forever. Even post-fix we still need a safety net for cases
    where Celery was unreachable at dispatch time, or the worker
    crashed mid-run. Marks anything older than the cutoff as
    'failed' so admins can see failure in the UI and re-trigger,
    rather than staring at a spinner.
    """
    logger.info("Starting fix_stuck_discovery_runs")
    session = SyncSession()

    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)

        result = session.execute(
            update(DiscoveryRun)
            .where(
                DiscoveryRun.status.in_(["pending", "running"]),
                DiscoveryRun.started_at < cutoff,
            )
            .values(
                status="failed",
                completed_at=datetime.now(timezone.utc),
            )
        )
        count = result.rowcount
        session.commit()

        logger.info("fix_stuck_discovery_runs: %d runs reset to 'failed'", count)
        return {"reset": count}

    except Exception as e:
        logger.exception("fix_stuck_discovery_runs failed: %s", e)
        session.rollback()
        raise
    finally:
        session.close()
