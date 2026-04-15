"""ATS board scanning tasks."""

import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.workers.celery_app import celery_app
from app.workers.tasks._db import SyncSession
from app.workers.tasks._scoring import compute_relevance_score
from app.workers.tasks._role_matching import match_role, match_role_with_config, classify_geography, load_cluster_config_sync
from app.models.company import Company, CompanyATSBoard
from app.models.job import Job, JobDescription
from app.models.scan import ScanLog
from app.utils.company_name import looks_like_junk_company_name
from app.utils.scan_lock import release_scan_lock

logger = logging.getLogger(__name__)

# Thread pool for running async fetchers from sync Celery context
_executor = ThreadPoolExecutor(max_workers=4)


def _trigger_alerts_for_new_jobs(session: Session):
    """Find new high-score jobs from the last scan and trigger alert notifications."""
    try:
        from app.models.alert import AlertConfig
        # Check if any alert configs exist
        has_alerts = session.execute(
            select(AlertConfig.id).where(AlertConfig.is_active.is_(True)).limit(1)
        ).scalar_one_or_none()
        if not has_alerts:
            return

        # Find new jobs from the last hour with score >= 50 (lowest possible threshold)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        new_jobs = session.execute(
            select(Job.id).where(
                Job.first_seen_at >= cutoff,
                Job.relevance_score >= 50,
            )
        ).scalars().all()

        if new_jobs:
            job_ids = [str(j) for j in new_jobs]
            from app.workers.tasks.alert_task import check_and_send_alerts
            check_and_send_alerts.delay(job_ids)
            logger.info("Triggered alerts for %d new high-score jobs", len(job_ids))
    except Exception as e:
        logger.warning("Alert trigger failed (non-fatal): %s", e)


def _get_fetcher_for_platform(platform: str):
    """Return an instantiated fetcher for a given ATS platform.

    Each fetcher has a .fetch(slug) method returning a list of normalized dicts.
    """
    from app.fetchers import FETCHER_MAP

    fetcher_cls = FETCHER_MAP.get(platform)
    if fetcher_cls is None:
        return None
    return fetcher_cls()


def _upsert_job(session: Session, company: Company, board: CompanyATSBoard, raw_job: dict, cluster_config: dict | None = None) -> str:
    """Upsert a single job record. Returns 'new', 'updated', or 'skipped'."""
    external_id = raw_job.get("external_id", "")
    if not external_id:
        return "skipped"

    title = raw_job.get("title", "").strip()

    # --- Validation: reject garbage data ---
    # Skip empty or too-short titles
    if not title or len(title) < 5:
        return "skipped"

    # Skip titles that are clearly not job postings
    _title_lower = title.lower()
    garbage_signals = [
        "test", "template", "do not apply", "internal only",
        "dummy", "example", "placeholder",
    ]
    if any(_title_lower == g for g in garbage_signals):
        return "skipped"

    location_raw = raw_job.get("location_raw", "") or ""
    remote_scope = raw_job.get("remote_scope", "") or ""

    # Role matching
    role_match = match_role_with_config(title, cluster_config)
    matched_role = role_match["matched_role"]
    role_cluster = role_match["role_cluster"]
    title_normalized = role_match["title_normalized"]

    existing = session.execute(
        select(Job).where(Job.external_id == external_id)
    ).scalar_one_or_none()

    # Regression finding 88: aggregator boards (e.g. Jobgether on Lever)
    # re-post the same logical role with a new Lever job-id every few
    # hours, producing rows with distinct `external_id` but identical
    # `(company_id, title)`. The unique constraint on `external_id`
    # can't help here. Before inserting a brand-new row, look for an
    # existing Job that already covers this `(company_id, title)` — if
    # found, treat it as an update of that row (refresh `last_seen_at`,
    # re-score, etc.) and skip the insert entirely. This keeps the DB
    # at one row per logical role without requiring per-platform
    # "is_aggregator" annotations.
    if not existing and title:
        existing = session.execute(
            select(Job).where(
                Job.company_id == company.id,
                Job.title == title,
            ).limit(1)
        ).scalar_one_or_none()

    # Geography classification
    geography_bucket = classify_geography(location_raw, remote_scope)

    now = datetime.now(timezone.utc)

    if existing:
        existing.title = title
        existing.title_normalized = title_normalized
        existing.url = raw_job.get("url", existing.url)
        existing.location_raw = location_raw
        existing.remote_scope = remote_scope
        existing.department = raw_job.get("department") or ""
        existing.employment_type = raw_job.get("employment_type") or ""
        existing.salary_range = raw_job.get("salary_range") or ""
        existing.matched_role = matched_role
        existing.role_cluster = role_cluster
        existing.geography_bucket = geography_bucket
        existing.last_seen_at = now
        existing.raw_json = raw_job.get("raw_json", {})

        # Recalculate relevance score
        existing.relevance_score = compute_relevance_score(
            title=title,
            matched_role=matched_role,
            role_cluster=role_cluster,
            is_target=company.is_target,
            geography_bucket=geography_bucket,
            remote_scope=remote_scope,
            platform=board.platform,
            posted_at=existing.posted_at,
        )
        return "updated"
    else:
        posted_at = raw_job.get("posted_at")
        if isinstance(posted_at, str):
            try:
                posted_at = datetime.fromisoformat(posted_at)
            except (ValueError, TypeError):
                posted_at = None

        job = Job(
            id=uuid.uuid4(),
            external_id=external_id,
            company_id=company.id,
            title=title,
            title_normalized=title_normalized,
            url=raw_job.get("url", ""),
            platform=board.platform,
            location_raw=location_raw,
            remote_scope=remote_scope,
            department=raw_job.get("department") or "",
            employment_type=raw_job.get("employment_type") or "",
            salary_range=raw_job.get("salary_range") or "",
            geography_bucket=geography_bucket,
            matched_role=matched_role,
            role_cluster=role_cluster,
            relevance_score=0.0,
            status="new",
            posted_at=posted_at,
            first_seen_at=now,
            last_seen_at=now,
            raw_json=raw_job.get("raw_json", {}),
        )
        # Compute relevance score
        job.relevance_score = compute_relevance_score(
            title=title,
            matched_role=matched_role,
            role_cluster=role_cluster,
            is_target=company.is_target,
            geography_bucket=geography_bucket,
            remote_scope=remote_scope,
            platform=board.platform,
            posted_at=posted_at,
        )
        session.add(job)
        return "new"


def _scan_board(session: Session, board: CompanyATSBoard, cluster_config: dict | None = None) -> dict:
    """Scan a single ATS board and return scan statistics."""
    stats = {"jobs_found": 0, "new_jobs": 0, "updated_jobs": 0, "skipped_jobs": 0, "errors": 0, "error_message": ""}

    fetcher = _get_fetcher_for_platform(board.platform)
    if not fetcher:
        stats["errors"] = 1
        stats["error_message"] = f"No fetcher for platform: {board.platform}"
        return stats

    company = session.execute(
        select(Company).where(Company.id == board.company_id)
    ).scalar_one_or_none()

    if not company:
        stats["errors"] = 1
        stats["error_message"] = f"Company not found: {board.company_id}"
        return stats

    try:
        raw_jobs = fetcher.fetch(board.slug)
        stats["jobs_found"] = len(raw_jobs)

        # Aggregator platforms fetch jobs from many companies — resolve per-job
        _AGGREGATOR_PLATFORMS = {"himalayas", "weworkremotely", "remoteok", "remotive"}
        is_aggregator = board.platform in _AGGREGATOR_PLATFORMS and board.slug == "__all__"

        for raw_job in raw_jobs:
            try:
                # For aggregator platforms, resolve the actual company from job data
                job_company = company
                if is_aggregator:
                    raw_json = raw_job.get("raw_json", {})
                    # Each aggregator uses different field names for the company
                    agg_company_name = (
                        raw_job.get("company_name")
                        or raw_json.get("companyName", "")
                        or raw_json.get("company_name", "")
                        or raw_json.get("company", "")
                        or ""
                    ).strip()
                    if agg_company_name:
                        # Regression finding 37: drop LinkedIn/aggregator-noise
                        # company names at ingest. `#hashtag` harvests, pure
                        # numerics, staffing-agency shells, and scratch names
                        # like "name"/"1name" all used to land in Company and
                        # then pollute /companies and the Pipeline board.
                        if looks_like_junk_company_name(agg_company_name):
                            logger.info(
                                "scan_task: skipping junk company name %r from %s/%s",
                                agg_company_name, board.platform, board.slug,
                            )
                            stats["skipped_jobs"] += 1
                            continue
                        import re
                        agg_slug = re.sub(r"[^a-z0-9-]", "", agg_company_name.lower().replace(" ", "-"))[:100]
                        # Look up by slug first (unique), then by name
                        existing_co = session.execute(
                            select(Company).where(Company.slug == agg_slug)
                        ).scalar_one_or_none()
                        if not existing_co:
                            existing_co = session.execute(
                                select(Company).where(Company.name == agg_company_name)
                            ).scalar_one_or_none()
                        if existing_co:
                            job_company = existing_co
                        else:
                            # Wrap the insert in a SAVEPOINT so an IntegrityError
                            # on a concurrent duplicate (same slug / same name)
                            # does NOT rollback the outer transaction and wipe
                            # out every job we've already upserted in this batch.
                            try:
                                with session.begin_nested():
                                    job_company = Company(
                                        id=uuid.uuid4(),
                                        name=agg_company_name,
                                        slug=agg_slug,
                                        is_target=False,
                                    )
                                    session.add(job_company)
                            except Exception:
                                # Re-lookup by slug, then by name (uniqueness
                                # can live on either column depending on history)
                                existing_co = session.execute(
                                    select(Company).where(Company.slug == agg_slug)
                                ).scalar_one_or_none()
                                if not existing_co:
                                    existing_co = session.execute(
                                        select(Company).where(Company.name == agg_company_name)
                                    ).scalar_one_or_none()
                                if existing_co:
                                    job_company = existing_co
                                else:
                                    raise

                result = _upsert_job(session, job_company, board, raw_job, cluster_config)
                if result == "new":
                    stats["new_jobs"] += 1
                elif result == "updated":
                    stats["updated_jobs"] += 1
                elif result == "skipped":
                    stats["skipped_jobs"] += 1
            except Exception as e:
                logger.error("Error upserting job %s: %s", raw_job.get("external_id", "?"), e, exc_info=True)
                stats["errors"] += 1

        # Update last_scanned_at on the board
        board.last_scanned_at = datetime.now(timezone.utc)
        session.commit()

    except Exception as e:
        logger.error("Error scanning board %s/%s: %s", board.platform, board.slug, e)
        stats["errors"] += 1
        stats["error_message"] = str(e)[:500]
        session.rollback()

    return stats


@celery_app.task(name="app.workers.tasks.scan_task.scan_all_platforms", bind=True, max_retries=2)
def scan_all_platforms(self):
    """Iterate all active CompanyATSBoard records and scan each one."""
    logger.info("Starting scan_all_platforms")
    start_time = time.time()

    session = SyncSession()
    try:
        cluster_config = load_cluster_config_sync(session)

        boards = session.execute(
            select(CompanyATSBoard).where(CompanyATSBoard.is_active.is_(True))
        ).scalars().all()

        total_stats = {"jobs_found": 0, "new_jobs": 0, "updated_jobs": 0, "errors": 0}

        for board in boards:
            scan_log = ScanLog(
                id=uuid.uuid4(),
                source=f"{board.platform}/{board.slug}",
                platform=board.platform,
            )
            session.add(scan_log)
            session.flush()

            board_start = time.time()
            stats = _scan_board(session, board, cluster_config)
            board_duration = int((time.time() - board_start) * 1000)

            scan_log.completed_at = datetime.now(timezone.utc)
            scan_log.jobs_found = stats["jobs_found"]
            scan_log.new_jobs = stats["new_jobs"]
            scan_log.updated_jobs = stats["updated_jobs"]
            scan_log.errors = stats["errors"]
            scan_log.error_message = stats["error_message"]
            scan_log.duration_ms = board_duration
            session.commit()

            for key in total_stats:
                total_stats[key] += stats.get(key, 0)

        total_duration = int((time.time() - start_time) * 1000)
        logger.info(
            "scan_all_platforms complete: %d boards, %d found, %d new, %d updated, %d errors, %dms",
            len(boards), total_stats["jobs_found"], total_stats["new_jobs"],
            total_stats["updated_jobs"], total_stats["errors"], total_duration,
        )

        # Trigger job alerts for new high-score jobs
        if total_stats["new_jobs"] > 0:
            _trigger_alerts_for_new_jobs(session)

        return total_stats

    except Exception as e:
        logger.exception("scan_all_platforms failed: %s", e)
        session.rollback()
        raise self.retry(exc=e, countdown=60)
    finally:
        session.close()
        # Finding 82: release the Redis concurrency lock acquired by
        # POST /platforms/scan/all. Runs on success, failure, and retry
        # so back-to-back scans are possible once this one finishes.
        release_scan_lock("all")


@celery_app.task(name="app.workers.tasks.scan_task.scan_platform", bind=True, max_retries=2)
def scan_platform(self, platform_name: str):
    """Scan all active boards for a specific platform."""
    logger.info("Starting scan_platform: %s", platform_name)
    start_time = time.time()

    session = SyncSession()
    try:
        cluster_config = load_cluster_config_sync(session)

        boards = session.execute(
            select(CompanyATSBoard).where(
                CompanyATSBoard.platform == platform_name,
                CompanyATSBoard.is_active.is_(True),
            )
        ).scalars().all()

        if not boards:
            logger.warning("No active boards for platform %s", platform_name)
            return {"status": "no_boards", "platform": platform_name}

        total_stats = {"jobs_found": 0, "new_jobs": 0, "updated_jobs": 0, "errors": 0}

        for board in boards:
            scan_log = ScanLog(
                id=uuid.uuid4(),
                source=f"{board.platform}/{board.slug}",
                platform=board.platform,
            )
            session.add(scan_log)
            session.flush()

            board_start = time.time()
            stats = _scan_board(session, board, cluster_config)
            board_duration = int((time.time() - board_start) * 1000)

            scan_log.completed_at = datetime.now(timezone.utc)
            scan_log.jobs_found = stats["jobs_found"]
            scan_log.new_jobs = stats["new_jobs"]
            scan_log.updated_jobs = stats["updated_jobs"]
            scan_log.errors = stats["errors"]
            scan_log.error_message = stats["error_message"]
            scan_log.duration_ms = board_duration
            session.commit()

            for key in total_stats:
                total_stats[key] += stats.get(key, 0)

        total_duration = int((time.time() - start_time) * 1000)
        total_stats["platform"] = platform_name
        total_stats["boards_scanned"] = len(boards)
        logger.info(
            "scan_platform %s complete: %d boards, %d found, %d new, %dms",
            platform_name, len(boards), total_stats["jobs_found"],
            total_stats["new_jobs"], total_duration,
        )
        return total_stats

    except Exception as e:
        logger.exception("scan_platform %s failed: %s", platform_name, e)
        session.rollback()
        raise self.retry(exc=e, countdown=60)
    finally:
        session.close()
        # Finding 82: release the per-platform lock. Scoped by name so
        # different platforms can scan in parallel.
        release_scan_lock(f"platform:{platform_name}")


@celery_app.task(name="app.workers.tasks.scan_task.scan_single_board", bind=True, max_retries=2)
def scan_single_board(self, board_id: str):
    """Scan a single ATS board by its ID."""
    logger.info("Starting scan_single_board: %s", board_id)
    start_time = time.time()

    session = SyncSession()
    try:
        cluster_config = load_cluster_config_sync(session)

        board = session.execute(
            select(CompanyATSBoard).where(CompanyATSBoard.id == board_id)
        ).scalar_one_or_none()

        if not board:
            logger.warning("Board not found: %s", board_id)
            return {"status": "not_found", "board_id": board_id}

        scan_log = ScanLog(
            id=uuid.uuid4(),
            source=f"{board.platform}/{board.slug}",
            platform=board.platform,
        )
        session.add(scan_log)
        session.flush()

        stats = _scan_board(session, board, cluster_config)
        duration = int((time.time() - start_time) * 1000)

        scan_log.completed_at = datetime.now(timezone.utc)
        scan_log.jobs_found = stats["jobs_found"]
        scan_log.new_jobs = stats["new_jobs"]
        scan_log.updated_jobs = stats["updated_jobs"]
        scan_log.errors = stats["errors"]
        scan_log.error_message = stats["error_message"]
        scan_log.duration_ms = duration
        session.commit()

        stats["board_id"] = board_id
        stats["platform"] = board.platform
        stats["slug"] = board.slug
        logger.info(
            "scan_single_board %s/%s complete: %d found, %d new, %dms",
            board.platform, board.slug, stats["jobs_found"], stats["new_jobs"], duration,
        )
        return stats

    except Exception as e:
        logger.exception("scan_single_board %s failed: %s", board_id, e)
        session.rollback()
        raise self.retry(exc=e, countdown=60)
    finally:
        session.close()
        # Finding 82: release the per-board lock. Short 5-min TTL means
        # even if this finally is bypassed (process kill), the lock
        # self-heals quickly.
        release_scan_lock(f"board:{board_id}")


@celery_app.task(name="app.workers.tasks.scan_task.scan_single_company", bind=True, max_retries=2)
def scan_single_company(self, company_id: str):
    """Scan all ATS boards for a single company."""
    logger.info("Starting scan_single_company: %s", company_id)
    start_time = time.time()

    session = SyncSession()
    try:
        cluster_config = load_cluster_config_sync(session)

        boards = session.execute(
            select(CompanyATSBoard).where(
                CompanyATSBoard.company_id == company_id,
                CompanyATSBoard.is_active.is_(True),
            )
        ).scalars().all()

        if not boards:
            logger.warning("No active boards for company %s", company_id)
            return {"status": "no_boards"}

        total_stats = {"jobs_found": 0, "new_jobs": 0, "updated_jobs": 0, "errors": 0}

        for board in boards:
            scan_log = ScanLog(
                id=uuid.uuid4(),
                source=f"{board.platform}/{board.slug}",
                platform=board.platform,
            )
            session.add(scan_log)
            session.flush()

            board_start = time.time()
            stats = _scan_board(session, board, cluster_config)
            board_duration = int((time.time() - board_start) * 1000)

            scan_log.completed_at = datetime.now(timezone.utc)
            scan_log.jobs_found = stats["jobs_found"]
            scan_log.new_jobs = stats["new_jobs"]
            scan_log.updated_jobs = stats["updated_jobs"]
            scan_log.errors = stats["errors"]
            scan_log.error_message = stats["error_message"]
            scan_log.duration_ms = board_duration
            session.commit()

            for key in total_stats:
                total_stats[key] += stats.get(key, 0)

        total_duration = int((time.time() - start_time) * 1000)
        logger.info(
            "scan_single_company %s complete: %d boards, %d found, %d new, %dms",
            company_id, len(boards), total_stats["jobs_found"],
            total_stats["new_jobs"], total_duration,
        )
        return total_stats

    except Exception as e:
        logger.exception("scan_single_company %s failed: %s", company_id, e)
        session.rollback()
        raise self.retry(exc=e, countdown=60)
    finally:
        session.close()
