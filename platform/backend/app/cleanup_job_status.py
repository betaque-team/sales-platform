"""Normalize `Job.status` values outside the documented vocabulary (Finding 99).

Usage (production):
    # Dry run first — prints what would be reset, touches nothing:
    docker compose exec backend python -m app.cleanup_job_status --dry-run

    # For-real run — resets rows with illegal status values to 'new':
    docker compose exec backend python -m app.cleanup_job_status

Idempotent — re-running is a no-op once every row is within the allowed set.

Why this exists
---------------
Finding 99 surfaced that `POST /api/v1/jobs/bulk-action` and
`PATCH /api/v1/jobs/{id}` previously declared `action: str` / `status: str`
on their Pydantic schemas with no Literal constraint, and the handlers
wrote the value straight onto `Job.status` without an allowlist check.
Result on prod: 25 rows landed in an illegal `status="reset"` state
(plus unknown count of `"Accepted"` / `"accept"` casing typos), and
these silently fell off `?status=new` queries, under-counting the
review queue and corrupting the pipeline-stats aggregates that key
on `status="accepted"`.

The API-layer fix (same commit) swaps the schemas to
`Literal[JOB_STATUS_VALUES]` so future writes bounce at 422. This
script retroactively normalizes the bad rows that are already in
the DB, and the deploy-time migration adds a Postgres CHECK
constraint as belt-and-suspenders.

Semantics
---------
For each `Job` row whose `status` is NOT in `JOB_STATUS_VALUES`
(the canonical allowlist shared with the API schema), reset to `"new"`.
Rationale for "new" as the destination: the bogus rows were almost
certainly reviewer-workflow mistakes ("reset" → probably meant to
undo a prior accept/reject; "accept" → casing typo). Kicking them
back to the top of the review queue is the safest landing — the
reviewer will see them again and pick the right status.

We do NOT attempt to guess what the user meant (e.g. `"Accepted"` →
`"accepted"`). That's the kind of silent normalization that caused
the mess in the first place. Explicit reset-to-new keeps the audit
clear.

The CHECK constraint added in migration `o5j6k7l8m9n0_add_job_status_check`
runs AFTER this cleanup so the constraint can't reject the existing
garbage on creation.
"""

import argparse
import asyncio
from typing import Iterable

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.models.job import Job
from app.schemas.job import JOB_STATUS_VALUES

settings = get_settings()


async def run(dry_run: bool) -> int:
    engine = create_async_engine(settings.database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    normalized = 0

    async with async_session() as session:
        # Scope to rows whose `status` is NOT in the allowlist. Safe even
        # if `status` is NULL on some legacy row — NOT IN with NULL yields
        # UNKNOWN and the row is excluded (which is desired; we don't
        # clobber NULLs, we only reset obvious garbage strings).
        result = await session.execute(
            select(Job.id, Job.status, Job.title, Job.company_id)
            .where(Job.status.notin_(JOB_STATUS_VALUES))
            .where(Job.status.is_not(None))
        )
        rows = result.all()

        print(
            f"Scanned for rows outside the allowlist "
            f"({', '.join(JOB_STATUS_VALUES)}). Found {len(rows)} offenders."
        )

        # Group by the offending status value for a compact summary.
        counts_by_status: dict[str, int] = {}
        for r in rows:
            counts_by_status[r.status] = counts_by_status.get(r.status, 0) + 1
            normalized += 1

        for bad_status, cnt in sorted(counts_by_status.items(), key=lambda p: -p[1]):
            print(f"  {cnt:>5d}  status={bad_status!r}")

        if dry_run:
            print(
                f"\n[dry-run] would reset {normalized} row(s) to status='new'. "
                "No changes written."
            )
        else:
            if normalized:
                # Single UPDATE — the predicate matches exactly the rows
                # we just enumerated, and the destination is constant.
                # No need to chunk by id.
                await session.execute(
                    update(Job)
                    .where(Job.status.notin_(JOB_STATUS_VALUES))
                    .where(Job.status.is_not(None))
                    .values(status="new")
                )
                await session.commit()
            print(
                f"\nReset {normalized} row(s) to status='new'. "
                "Job.status column is now allowlist-clean."
            )

    await engine.dispose()
    return normalized


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be reset without committing any changes.",
    )
    args = parser.parse_args()
    asyncio.run(run(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
