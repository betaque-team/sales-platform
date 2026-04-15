"""Platform monitoring API endpoints."""

from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.job import Job
from app.models.company import CompanyATSBoard
from app.models.scan import ScanLog
from app.models.user import User
from app.api.deps import get_current_user, require_role
from app.utils.company_name import looks_like_junk_company_name
from app.utils.scan_lock import acquire_scan_lock, release_scan_lock

router = APIRouter(prefix="/platforms", tags=["platforms"])


@router.get("")
async def list_platforms(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get overview of all monitored platforms with stats."""
    # Count boards per platform
    boards_q = (
        select(
            CompanyATSBoard.platform,
            func.count(CompanyATSBoard.id).label("total_boards"),
            func.sum(case((CompanyATSBoard.is_active == True, 1), else_=0)).label("active_boards"),
        )
        .group_by(CompanyATSBoard.platform)
    )
    boards_result = await db.execute(boards_q)
    boards_by_platform = {row.platform: {"total_boards": row.total_boards, "active_boards": int(row.active_boards or 0)} for row in boards_result}

    # Count jobs per platform
    jobs_q = (
        select(
            Job.platform,
            func.count(Job.id).label("total_jobs"),
            func.sum(case((Job.status == "new", 1), else_=0)).label("new_jobs"),
            func.sum(case((Job.status == "accepted", 1), else_=0)).label("accepted_jobs"),
            func.sum(case((Job.status == "rejected", 1), else_=0)).label("rejected_jobs"),
            func.avg(Job.relevance_score).label("avg_score"),
        )
        .group_by(Job.platform)
    )
    jobs_result = await db.execute(jobs_q)
    jobs_by_platform = {}
    for row in jobs_result:
        jobs_by_platform[row.platform] = {
            "total_jobs": row.total_jobs,
            "new_jobs": int(row.new_jobs or 0),
            "accepted_jobs": int(row.accepted_jobs or 0),
            "rejected_jobs": int(row.rejected_jobs or 0),
            "avg_score": round(float(row.avg_score or 0), 1),
        }

    # Latest scan per platform
    scans_q = (
        select(
            ScanLog.platform,
            func.max(ScanLog.completed_at).label("last_scan"),
            func.sum(ScanLog.errors).label("total_errors"),
        )
        .group_by(ScanLog.platform)
    )
    scans_result = await db.execute(scans_q)
    scans_by_platform = {}
    for row in scans_result:
        scans_by_platform[row.platform] = {
            "last_scan": row.last_scan.isoformat() if row.last_scan else None,
            "total_errors": int(row.total_errors or 0),
        }

    # Combine into platform list
    all_platforms = set(boards_by_platform.keys()) | set(jobs_by_platform.keys())
    platforms = []
    for name in sorted(all_platforms):
        boards = boards_by_platform.get(name, {"total_boards": 0, "active_boards": 0})
        jobs = jobs_by_platform.get(name, {"total_jobs": 0, "new_jobs": 0, "accepted_jobs": 0, "rejected_jobs": 0, "avg_score": 0})
        scans = scans_by_platform.get(name, {"last_scan": None, "total_errors": 0})
        platforms.append({
            "name": name,
            **boards,
            **jobs,
            **scans,
        })

    return {"platforms": platforms}


@router.get("/boards")
async def list_boards(
    platform: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all ATS boards with company info."""
    from app.models.company import Company
    from sqlalchemy.orm import joinedload

    query = select(CompanyATSBoard).options(joinedload(CompanyATSBoard.company))
    if platform:
        query = query.where(CompanyATSBoard.platform == platform)
    query = query.order_by(CompanyATSBoard.platform, CompanyATSBoard.slug)

    result = await db.execute(query)
    boards = result.unique().scalars().all()

    return {
        "items": [
            {
                "id": str(b.id),
                "company_id": str(b.company_id),
                "company_name": b.company.name if b.company else "Unknown",
                "platform": b.platform,
                "slug": b.slug,
                "is_active": b.is_active,
                "last_scanned_at": b.last_scanned_at.isoformat() if b.last_scanned_at else None,
            }
            for b in boards
        ],
        "total": len(boards),
    }


@router.post("/boards/{board_id}/toggle")
async def toggle_board(
    board_id: UUID,
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Enable or disable an ATS board."""
    result = await db.execute(select(CompanyATSBoard).where(CompanyATSBoard.id == board_id))
    board = result.scalar_one_or_none()
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")
    board.is_active = not board.is_active
    await db.commit()
    return {"id": str(board.id), "is_active": board.is_active}


@router.post("/boards")
async def add_board(
    body: dict,
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Add a new ATS board. Requires company_name, platform, slug."""
    from app.models.company import Company
    import uuid as _uuid
    from datetime import datetime, timezone

    company_name = body.get("company_name", "").strip()
    platform = body.get("platform", "").strip().lower()
    slug = body.get("slug", "").strip()

    if not company_name or not platform or not slug:
        raise HTTPException(status_code=400, detail="company_name, platform, and slug are required")

    valid_platforms = ["greenhouse", "lever", "ashby", "workable", "bamboohr", "himalayas", "wellfound", "jobvite", "smartrecruiters", "recruitee"]
    if platform not in valid_platforms:
        raise HTTPException(status_code=400, detail=f"platform must be one of: {', '.join(valid_platforms)}")

    # Regression finding 37: reject LinkedIn-hashtag / staffing / scratch
    # names up-front so manual admin adds can't reintroduce the same
    # junk the ingest filter (scan_task.py) drops automatically.
    if looks_like_junk_company_name(company_name):
        raise HTTPException(
            status_code=400,
            detail=(
                "company_name looks like a scraping artifact (hashtag harvest, "
                "staffing shell, purely numeric, or scratch string). If this "
                "is a real company, please pass a cleaned display name."
            ),
        )

    # Find or create company
    result = await db.execute(select(Company).where(Company.name == company_name))
    company = result.scalar_one_or_none()
    if not company:
        company = Company(
            id=_uuid.uuid4(),
            name=company_name,
            slug=company_name.lower().replace(" ", "-").replace(".", "-"),
            is_target=False,
            created_at=datetime.now(timezone.utc),
        )
        db.add(company)
        await db.flush()

    # Check for duplicate board
    result = await db.execute(
        select(CompanyATSBoard).where(
            CompanyATSBoard.company_id == company.id,
            CompanyATSBoard.platform == platform,
            CompanyATSBoard.slug == slug,
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Board already exists")

    board = CompanyATSBoard(
        id=_uuid.uuid4(),
        company_id=company.id,
        platform=platform,
        slug=slug,
        is_active=True,
    )
    db.add(board)
    await db.commit()

    return {
        "id": str(board.id),
        "company_id": str(company.id),
        "company_name": company.name,
        "platform": board.platform,
        "slug": board.slug,
        "is_active": True,
        "last_scanned_at": None,
    }


@router.delete("/boards/{board_id}")
async def delete_board(
    board_id: UUID,
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Delete an ATS board."""
    result = await db.execute(select(CompanyATSBoard).where(CompanyATSBoard.id == board_id))
    board = result.scalar_one_or_none()
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")
    await db.delete(board)
    await db.commit()
    return {"ok": True}


@router.post("/scan/all")
async def trigger_full_scan(
    user: User = Depends(require_role("admin")),
):
    """Trigger a full scan of all active platforms.

    Regression finding 82: double-click was queueing two tasks that
    each iterated 871 boards. Redis `SET NX EX` lock now dedups at
    the endpoint, returning 409 if a full scan is already in flight.
    """
    from app.workers.tasks.scan_task import scan_all_platforms

    if not await acquire_scan_lock("all"):
        raise HTTPException(
            status_code=409,
            detail="A full scan is already running. Wait for it to complete or check /scan/status.",
        )
    try:
        task = scan_all_platforms.delay()
    except Exception:
        # `.delay()` pushes to Redis; if that fails we own the lock
        # but never kicked off work — release so the admin can retry.
        release_scan_lock("all")
        raise
    return {"task_id": str(task.id), "status": "queued", "scope": "all_platforms"}


@router.post("/scan/{platform}")
async def trigger_platform_scan(
    platform: str,
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Trigger a scan for a specific platform only."""
    from app.workers.tasks.scan_task import scan_platform
    valid_platforms = ["greenhouse", "lever", "ashby", "workable", "bamboohr", "himalayas", "wellfound", "jobvite", "smartrecruiters", "recruitee"]
    if platform not in valid_platforms:
        raise HTTPException(status_code=400, detail=f"Platform must be one of: {', '.join(valid_platforms)}")

    # Verify there are active boards for this platform
    board_count = (await db.execute(
        select(func.count()).select_from(CompanyATSBoard).where(
            CompanyATSBoard.platform == platform,
            CompanyATSBoard.is_active.is_(True),
        )
    )).scalar() or 0
    if board_count == 0:
        raise HTTPException(status_code=400, detail=f"No active boards for platform: {platform}")

    scope = f"platform:{platform}"
    if not await acquire_scan_lock(scope):
        raise HTTPException(
            status_code=409,
            detail=f"A scan of {platform} is already running.",
        )
    try:
        task = scan_platform.delay(platform)
    except Exception:
        release_scan_lock(scope)
        raise
    return {"task_id": str(task.id), "status": "queued", "platform": platform, "boards": board_count}


@router.post("/scan/board/{board_id}")
async def trigger_board_scan(
    board_id: UUID,
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Trigger a scan for a single ATS board."""
    from app.workers.tasks.scan_task import scan_single_board
    result = await db.execute(select(CompanyATSBoard).where(CompanyATSBoard.id == board_id))
    board = result.scalar_one_or_none()
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    scope = f"board:{board_id}"
    if not await acquire_scan_lock(scope):
        raise HTTPException(
            status_code=409,
            detail=f"A scan of {board.platform}/{board.slug} is already running.",
        )
    try:
        task = scan_single_board.delay(str(board_id))
    except Exception:
        release_scan_lock(scope)
        raise
    return {"task_id": str(task.id), "status": "queued", "board": board.slug, "platform": board.platform}


@router.post("/scan/discover")
async def trigger_discovery_scan(
    user: User = Depends(require_role("admin")),
):
    """Trigger platform discovery: find new ATS boards and auto-add them."""
    from app.workers.tasks.discovery_task import discover_and_add_boards

    if not await acquire_scan_lock("discover"):
        raise HTTPException(
            status_code=409,
            detail="A discovery scan is already running.",
        )
    try:
        task = discover_and_add_boards.delay()
    except Exception:
        release_scan_lock("discover")
        raise
    return {"task_id": str(task.id), "status": "queued", "scope": "platform_discovery"}


@router.get("/scan/status/{task_id}")
async def get_scan_status(
    task_id: str,
    user: User = Depends(require_role("admin")),
):
    """Check the status of a scan task."""
    from app.workers.celery_app import celery_app
    result = celery_app.AsyncResult(task_id)
    response = {
        "task_id": task_id,
        "status": result.status,
    }
    if result.ready():
        response["result"] = result.result if result.successful() else str(result.result)
    return response


@router.get("/scan-logs")
async def get_scan_logs(
    platform: str | None = None,
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get recent scan logs."""
    query = select(ScanLog).order_by(ScanLog.started_at.desc()).limit(limit)
    if platform:
        query = query.where(ScanLog.platform == platform)
    result = await db.execute(query)
    logs = result.scalars().all()
    return {
        "items": [
            {
                "id": str(l.id),
                "source": l.source,
                "platform": l.platform,
                "started_at": l.started_at.isoformat() if l.started_at else None,
                "completed_at": l.completed_at.isoformat() if l.completed_at else None,
                "jobs_found": l.jobs_found,
                "new_jobs": l.new_jobs,
                "updated_jobs": l.updated_jobs,
                "errors": l.errors,
                "error_message": l.error_message,
                "duration_ms": l.duration_ms,
            }
            for l in logs
        ]
    }
