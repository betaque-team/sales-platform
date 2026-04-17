"""Training-data export + stats API (F238).

Three admin-only endpoints:

  GET /api/v1/training-data/stats
      Counts per task_type + class-balance breakdown for the dashboard.

  GET /api/v1/training-data/export?task_type=...&since=...&limit=...
      JSONL streaming export. One row per line. Audit-logged.

  POST /api/v1/training-data/backfill-role-classify
      One-shot backfill: walks existing `jobs` rows and writes one
      `role_classify` training_example per (job, role_cluster) pair.
      Idempotent — re-runs skip jobs already represented in the table.

Auth: every endpoint requires `admin` role. Training data exports
contain scrubbed-but-still-sensitive content (resumes, JDs in scrubbed
form) and the action is audit-logged.

Privacy is enforced upstream — by the time rows land in
`training_examples`, PII has already been scrubbed via
`app.utils.training_scrub.scrub_pii`. The export endpoint is a
straight pass-through; it does not re-scrub or re-process.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import AsyncGenerator, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_role
from app.database import get_db
from app.models.training_example import (
    TASK_TYPE_VALUES,
    TASK_ROLE_CLASSIFY,
    TrainingExample,
)
from app.models.user import User
from app.utils.audit import log_action

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/training-data", tags=["training-data"])


# Hard cap: a single export tops out at this many rows so a misclick
# can't OOM the backend or dump the entire training corpus in one
# shot. Operator can paginate with `since=` if they need more than
# the cap. Tuned to ~1 round-trip-second at typical row sizes
# (resume + JD + label ≈ 8KB → 100K rows ≈ 800MB stream — too much).
EXPORT_MAX_ROWS = 50_000


# ── Stats ────────────────────────────────────────────────────────────────────

@router.get("/stats", dependencies=[Depends(require_role("admin"))])
async def stats(db: AsyncSession = Depends(get_db)):
    """Per-task-type counts + class-balance breakdown.

    Returns:
      {
        "by_task_type": {
          "resume_match":           {"total": 1234, "by_class": {"accepted": 543, "rejected": 612, "skipped": 79}},
          "role_classify":          {"total": 13421, "by_class": {"infra": 5210, "security": 3401, ...}},
          "cover_letter_quality":   {"total": 188,  "by_class": {"generated": 188}},
          "interview_prep_quality": {"total": 91,   "by_class": {"generated": 91}},
          "customize_quality":      {"total": 156,  "by_class": {"generated": 156}},
          "search_intent":          {"total": 0,    "by_class": {}}
        },
        "total_rows": 15090,
        "earliest": "2026-04-17T05:01:23Z",
        "latest":   "2026-04-17T08:42:51Z"
      }
    """
    rows = (await db.execute(
        select(
            TrainingExample.task_type,
            TrainingExample.label_class,
            func.count(TrainingExample.id),
        ).group_by(TrainingExample.task_type, TrainingExample.label_class)
    )).all()

    by_task_type: dict[str, dict] = {
        t: {"total": 0, "by_class": {}} for t in TASK_TYPE_VALUES
    }
    total_rows = 0
    for task_type, label_class, count in rows:
        bucket = by_task_type.setdefault(task_type, {"total": 0, "by_class": {}})
        bucket["total"] += int(count)
        bucket["by_class"][label_class or "_unlabeled"] = int(count)
        total_rows += int(count)

    earliest = (await db.execute(select(func.min(TrainingExample.created_at)))).scalar()
    latest = (await db.execute(select(func.max(TrainingExample.created_at)))).scalar()

    return {
        "by_task_type": by_task_type,
        "total_rows": total_rows,
        "earliest": earliest.isoformat() if earliest else None,
        "latest": latest.isoformat() if latest else None,
    }


# ── Export ───────────────────────────────────────────────────────────────────

async def _stream_jsonl(rows) -> AsyncGenerator[bytes, None]:
    """Yield one JSON-line per row.

    StreamingResponse calls this once per chunk so the full result
    set never sits in memory. Adds a trailing newline per row so
    standard JSONL tooling (jq, polars.read_ndjson) parses cleanly.
    """
    for r in rows:
        payload = {
            "id": str(r.id),
            "task_type": r.task_type,
            "label_class": r.label_class,
            "inputs": r.inputs,
            "labels": r.labels,
            "metadata": r.metadata_json,
            "user_id_hash": r.user_id_hash,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        # `default=str` so any UUID / Decimal / datetime values nested
        # inside JSONB serialize cleanly. Most rows won't need it but
        # it's free insurance.
        yield (json.dumps(payload, default=str) + "\n").encode("utf-8")


@router.get("/export", dependencies=[Depends(require_role("admin"))])
async def export_training_data(
    request: Request,
    task_type: Literal[
        "resume_match",
        "role_classify",
        "cover_letter_quality",
        "interview_prep_quality",
        "customize_quality",
        "search_intent",
    ],
    since: datetime | None = None,
    limit: int = Query(EXPORT_MAX_ROWS, ge=1, le=EXPORT_MAX_ROWS),
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Stream JSONL export of training_examples for `task_type`.

    Filters:
      - `task_type`: required, Literal-validated.
      - `since`: optional ISO datetime; export only rows newer than this.
      - `limit`: optional, capped at EXPORT_MAX_ROWS (50k).

    Audit-logged with the row count + task_type so we can see who
    exported what when.

    Response is `application/x-ndjson` with `Content-Disposition:
    attachment` so a curl-to-file workflow saves it cleanly.
    """
    query = select(TrainingExample).where(TrainingExample.task_type == task_type)
    if since is not None:
        # Coerce to UTC so naive datetimes from query strings don't
        # silently compare against UTC-aware created_at columns and
        # produce empty results.
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        query = query.where(TrainingExample.created_at > since)
    query = query.order_by(TrainingExample.created_at.asc()).limit(limit)

    result = await db.execute(query)
    rows = result.scalars().all()

    await log_action(
        db, admin,
        action="training_data.export",
        resource="training_data",
        request=request,
        metadata={
            "task_type": task_type,
            "since": since.isoformat() if since else None,
            "limit": limit,
            "row_count": len(rows),
        },
    )

    filename = (
        f"training_{task_type}_"
        f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}.jsonl"
    )
    return StreamingResponse(
        _stream_jsonl(rows),
        media_type="application/x-ndjson",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Row-Count": str(len(rows)),
        },
    )


# ── Backfill role_classify from existing jobs ───────────────────────────────

@router.post(
    "/backfill-role-classify",
    dependencies=[Depends(require_role("admin"))],
)
async def backfill_role_classify(
    request: Request,
    max_jobs: int | None = Query(None, ge=1, le=100_000),
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Walk existing Jobs and emit one role_classify row per job.

    Live capture from `scan_task._upsert_job` would be cleaner but
    that path is sync (Celery worker) and the AsyncSession-driven
    capture helper doesn't fit there. Instead: a one-shot admin
    backfill that the operator triggers after deploys (or after the
    next scan reshuffles cluster assignments via F227 reclassify).

    Idempotent: skips Jobs that already have a `role_classify` row in
    `training_examples` (matched on `metadata_json->>'job_id'`). Safe
    to re-run.

    `max_jobs` lets ops cap a smoke test; default is unbounded
    (the upper Query bound of 100k is the absolute ceiling).
    """
    from app.models.job import Job, JobDescription
    from app.utils.training_scrub import scrub_pii

    # Pull the set of job_ids already represented so we can skip them.
    existing_ids_rows = (await db.execute(
        select(TrainingExample.metadata_json["job_id"].astext)
        .where(TrainingExample.task_type == TASK_ROLE_CLASSIFY)
    )).all()
    existing_ids = {r[0] for r in existing_ids_rows if r[0]}

    # Fetch jobs in batches to keep the working set bounded.
    BATCH = 500
    scanned = 0
    written = 0
    skipped = 0
    while True:
        if max_jobs is not None and scanned >= max_jobs:
            break
        batch_limit = min(BATCH, max_jobs - scanned) if max_jobs else BATCH
        jobs = (await db.execute(
            select(Job, JobDescription.text_content)
            .outerjoin(JobDescription, JobDescription.job_id == Job.id)
            .order_by(Job.first_seen_at.asc())
            .offset(scanned)
            .limit(batch_limit)
        )).all()
        if not jobs:
            break

        for job, jd_text in jobs:
            scanned += 1
            if str(job.id) in existing_ids:
                skipped += 1
                continue
            row = TrainingExample(
                task_type=TASK_ROLE_CLASSIFY,
                label_class=job.role_cluster or "unclassified",
                inputs={
                    "job_title": job.title or "",
                    "job_description": scrub_pii(jd_text or "")[:6000],
                },
                labels={
                    "role_cluster": job.role_cluster or "",
                    "matched_role": job.matched_role or "",
                },
                metadata_json={
                    "job_id": str(job.id),
                    "platform": job.platform,
                    "first_seen_at": job.first_seen_at.isoformat() if job.first_seen_at else None,
                },
                user_id_hash=None,
            )
            db.add(row)
            written += 1

        # Commit per-batch so a long backfill makes incremental
        # progress visible (and so a crash mid-run doesn't lose
        # everything).
        await db.commit()

    await log_action(
        db, admin,
        action="training_data.backfill_role_classify",
        resource="training_data",
        request=request,
        metadata={"scanned": scanned, "written": written, "skipped": skipped},
    )

    return {
        "scanned": scanned,
        "written": written,
        "skipped_already_present": skipped,
    }
