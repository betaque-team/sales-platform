"""Admin monitoring API endpoints — system health, storage, uptime, VM."""

import time
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.job import Job, JobDescription
from app.models.company import Company, CompanyATSBoard
from app.models.scan import ScanLog
from app.models.user import User
from app.models.review import Review
from app.api.deps import get_current_user, require_role
from app.services.host_stats import get_vm_metrics

router = APIRouter(prefix="/monitoring", tags=["monitoring"])

# Track when the backend started
_BOOT_TIME = time.time()


@router.get("")
async def get_system_health(
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Get full system health overview (admin only)."""
    now = datetime.now(timezone.utc)

    # --- Database health ---
    try:
        await db.execute(text("SELECT 1"))
        db_healthy = True
    except Exception:
        db_healthy = False

    # --- Table row counts ---
    job_count = (await db.execute(select(func.count()).select_from(Job))).scalar() or 0
    company_count = (await db.execute(select(func.count()).select_from(Company))).scalar() or 0
    board_count = (await db.execute(select(func.count()).select_from(CompanyATSBoard))).scalar() or 0
    active_board_count = (await db.execute(
        select(func.count()).select_from(CompanyATSBoard).where(CompanyATSBoard.is_active.is_(True))
    )).scalar() or 0
    review_count = (await db.execute(select(func.count()).select_from(Review))).scalar() or 0
    scan_log_count = (await db.execute(select(func.count()).select_from(ScanLog))).scalar() or 0

    # --- Jobs breakdown ---
    role_clusters = (await db.execute(
        select(Job.role_cluster, func.count()).group_by(Job.role_cluster)
    )).all()
    role_cluster_counts = {(rc or "unclassified"): c for rc, c in role_clusters}

    geography_buckets = (await db.execute(
        select(Job.geography_bucket, func.count()).group_by(Job.geography_bucket)
    )).all()
    geography_counts = {(gb or "unclassified"): c for gb, c in geography_buckets}

    platforms = (await db.execute(
        select(Job.platform, func.count()).group_by(Job.platform)
    )).all()
    platform_counts = {p: c for p, c in platforms}

    status_counts_raw = (await db.execute(
        select(Job.status, func.count()).group_by(Job.status)
    )).all()
    status_counts = {s: c for s, c in status_counts_raw}

    # --- Scoring stats ---
    scored_count = (await db.execute(
        select(func.count()).select_from(Job).where(Job.relevance_score > 0)
    )).scalar() or 0
    avg_score = (await db.execute(
        select(func.avg(Job.relevance_score)).where(Job.relevance_score > 0)
    )).scalar() or 0

    # --- Recent scan activity ---
    last_24h = now - timedelta(hours=24)
    scans_24h = (await db.execute(
        select(func.count()).select_from(ScanLog).where(ScanLog.started_at >= last_24h)
    )).scalar() or 0
    new_jobs_24h = (await db.execute(
        select(func.sum(ScanLog.new_jobs)).where(ScanLog.started_at >= last_24h)
    )).scalar() or 0

    last_scan = (await db.execute(
        select(ScanLog).order_by(ScanLog.started_at.desc()).limit(1)
    )).scalar_one_or_none()

    errors_24h = (await db.execute(
        select(func.sum(ScanLog.errors)).where(ScanLog.started_at >= last_24h)
    )).scalar() or 0

    # --- Database size (PostgreSQL) ---
    try:
        db_size_result = await db.execute(text("SELECT pg_database_size(current_database())"))
        db_size_bytes = db_size_result.scalar() or 0
    except Exception:
        db_size_bytes = 0

    # Table sizes
    try:
        table_sizes_result = await db.execute(text("""
            SELECT relname AS table_name,
                   pg_total_relation_size(relid) AS total_bytes
            FROM pg_catalog.pg_statio_user_tables
            ORDER BY pg_total_relation_size(relid) DESC
            LIMIT 10
        """))
        table_sizes = [{"table": r[0], "size_bytes": r[1]} for r in table_sizes_result]
    except Exception:
        table_sizes = []

    # --- Uptime ---
    uptime_seconds = int(time.time() - _BOOT_TIME)

    return {
        "timestamp": now.isoformat(),
        "uptime_seconds": uptime_seconds,
        "database": {
            "healthy": db_healthy,
            "size_bytes": db_size_bytes,
            "size_mb": round(db_size_bytes / (1024 * 1024), 1),
            "table_sizes": table_sizes,
        },
        "data_counts": {
            "jobs": job_count,
            "companies": company_count,
            "boards_total": board_count,
            "boards_active": active_board_count,
            "reviews": review_count,
            "scan_logs": scan_log_count,
            "scored_jobs": scored_count,
        },
        "jobs_breakdown": {
            "by_role_cluster": role_cluster_counts,
            "by_geography": geography_counts,
            "by_platform": platform_counts,
            "by_status": status_counts,
        },
        "scoring": {
            "scored_count": scored_count,
            "unscored_count": job_count - scored_count,
            "avg_score": round(float(avg_score), 2),
        },
        "activity_24h": {
            "scans_run": scans_24h,
            "new_jobs_added": new_jobs_24h or 0,
            "errors": errors_24h,
            "last_scan_at": last_scan.started_at.isoformat() if last_scan else None,
            "last_scan_source": last_scan.source if last_scan else None,
        },
    }


@router.get("/vm", dependencies=[Depends(require_role("admin"))])
async def get_vm_health():
    """VM host-level metrics + Oracle Always-Free guardrails (admin only).

    Data is sourced from a JSON snapshot written by the host collector
    (`/usr/local/bin/collect-host-metrics.sh`, cron every 1 min). If the
    snapshot file is absent (dev, CI), the response has `available: False`.
    """
    return get_vm_metrics()


@router.post("/backup", dependencies=[Depends(require_role("admin"))])
async def trigger_backup(label: str = "manual"):
    """Trigger an on-demand database backup (admin only)."""
    from app.workers.tasks.backup_task import run_backup
    task = run_backup.delay(label=label)
    return {"task_id": task.id, "status": "queued", "label": label}


@router.get("/backups", dependencies=[Depends(require_role("admin"))])
async def list_backups():
    """List available backups with manifest metadata."""
    import json
    from pathlib import Path
    backup_root = Path("/app/backups")
    if not backup_root.exists():
        return {"backups": []}
    items = []
    for d in sorted(backup_root.iterdir(), reverse=True):
        if not d.is_dir() or not d.name[0].isdigit():
            continue
        manifest_path = d / "manifest.json"
        entry: dict = {"timestamp": d.name, "path": str(d)}
        if manifest_path.exists():
            with open(manifest_path) as f:
                m = json.load(f)
            entry.update({
                "created_at":       m.get("created_at"),
                "label":            m.get("label", ""),
                "alembic_revision": m.get("alembic_revision"),
                "total_rows":       m.get("total_rows", 0),
                "dump_size_mb":     round(m.get("dump_size_bytes", 0) / 1024 / 1024, 2),
            })
        items.append(entry)
    return {"backups": items, "count": len(items)}


@router.get("/scan-errors", dependencies=[Depends(require_role("admin"))])
async def list_scan_errors(
    days: int = 7,
    db: AsyncSession = Depends(get_db),
):
    """Regression finding 104: surface per-error detail from ScanLog.

    Returns the most recent scan logs where `errors > 0` or
    `error_message != ''`, grouped by platform/source, so admins can
    diagnose silently-failing boards without tailing container logs.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    result = await db.execute(
        select(ScanLog)
        .where(ScanLog.started_at >= cutoff)
        .where((ScanLog.errors > 0) | (ScanLog.error_message != ""))
        .order_by(ScanLog.started_at.desc())
        .limit(200)
    )
    errors = result.scalars().all()

    items = []
    for e in errors:
        items.append({
            "id": str(e.id),
            "platform": e.platform,
            "source": e.source,
            "started_at": e.started_at.isoformat(),
            "completed_at": e.completed_at.isoformat() if e.completed_at else None,
            "errors": e.errors,
            "error_message": e.error_message,
            "jobs_found": e.jobs_found,
            "duration_ms": e.duration_ms,
        })

    # Summary by platform
    by_platform: dict[str, int] = {}
    for item in items:
        by_platform[item["platform"]] = by_platform.get(item["platform"], 0) + 1

    return {
        "items": items,
        "total": len(items),
        "by_platform": by_platform,
        "days": days,
    }
