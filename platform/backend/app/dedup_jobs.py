"""Deduplicate jobs that share (company_id, title) — Finding 88.

Usage (production):
    # Dry run first — prints what would be deleted, touches nothing:
    docker compose exec backend python -m app.dedup_jobs --dry-run

    # For-real run — deletes duplicate rows keeping the newest per group:
    docker compose exec backend python -m app.dedup_jobs

Idempotent — re-running is a no-op once every `(company_id, title)`
pair has at most one row.

Why this exists
---------------
Regression finding 88 surfaced that ~47% of recently scraped job rows
were duplicate `(title, company)` pairs. One company in particular —
Jobgether — is itself a job-aggregator that re-posts employer roles
under its own Lever board, each with a distinct external_id but the
same logical title. The `Job.external_id` unique constraint protects
the DB from exact-ID duplicates, but does nothing about
"same role, different Lever posting".

Consequences that were visible in the UI:
  - "Total Jobs 47,776" was inflated (~357 excess rows just from
    Jobgether, with individual titles repeated up to 42×).
  - `/jobs?role_cluster=relevant` listings had Jobgether near-copies
    filling every 4th page.
  - The Review Queue showed the same title 15 times in a row.
  - Scoring signals got 42× the weight for Jobgether roles, biasing
    the feedback engine toward whatever reviewers did with them.

Strategy
--------
This is the "now" cleanup lane of Finding 88 — the one-shot purge
that gets the DB back to one row per logical role. The long-term
fixes (collapse at ingest, mark aggregators) are separate work.

For each `(company_id, title)` group with >1 row:
  1. Keep the row with the MAX(first_seen_at) — the most recently
     observed posting is the freshest representation of the role.
  2. Ties broken by MAX(id) so the delete set is deterministic.
  3. Delete every other row in the group. `Review` and
     `JobDescription` rows cascade via ondelete="CASCADE" and
     `cascade="all, delete-orphan"` respectively.

The finding's SQL sketch used `MIN(id)` as the survivor. We prefer
`MAX(first_seen_at)` because the survivor is the row most likely to
carry the up-to-date `relevance_score`, `status`, and
`last_seen_at` — all of which the frontend reads.

Safety
------
Dry-run prints a sample of the top 20 duplicate groups plus totals.
Real run chunks DELETEs in batches of 500 IDs to stay under
Postgres's parameter limit and to keep the lock footprint small
even on the full 47k-row backlog.
"""

import argparse
import asyncio
from typing import Iterable

from sqlalchemy import select, delete, func, and_
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.models.job import Job
from app.models.company import Company

settings = get_settings()


async def run(dry_run: bool) -> int:
    engine = create_async_engine(settings.database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # Identify duplicate groups: (company_id, title) with count > 1.
        dup_groups_q = (
            select(
                Job.company_id,
                Job.title,
                func.count(Job.id).label("row_count"),
            )
            .group_by(Job.company_id, Job.title)
            .having(func.count(Job.id) > 1)
            .order_by(func.count(Job.id).desc())
        )
        dup_groups = (await session.execute(dup_groups_q)).all()

        total_rows_in_dups = sum(g.row_count for g in dup_groups)
        excess = total_rows_in_dups - len(dup_groups)  # rows above 1-per-group

        print(
            f"Found {len(dup_groups)} duplicate (company_id, title) group(s); "
            f"{total_rows_in_dups} rows across them; {excess} excess row(s) "
            f"that would be removed."
        )

        if not dup_groups:
            print("Nothing to do — every (company_id, title) already unique.")
            await engine.dispose()
            return 0

        # Preview top 20 groups in dry-run mode so the operator can spot-check.
        if dry_run:
            top = dup_groups[:20]
            print("\nTop duplicate groups (up to 20 shown):")
            for g in top:
                # Resolve the company name for the log line — purely cosmetic.
                comp = (await session.execute(
                    select(Company.name).where(Company.id == g.company_id)
                )).scalar() or "<unknown>"
                print(
                    f"  {g.row_count:3d}× {comp!r:35s} | {g.title!r}"
                )

        # Collect the IDs to delete: everything in each group EXCEPT the
        # row with the latest first_seen_at (ties broken by MAX(id)).
        ids_to_delete: list = []
        survivor_count = 0
        for g in dup_groups:
            rows_in_group = (await session.execute(
                select(Job.id, Job.first_seen_at)
                .where(
                    and_(
                        Job.company_id == g.company_id,
                        Job.title == g.title,
                    )
                )
                .order_by(Job.first_seen_at.desc().nullslast(), Job.id.desc())
            )).all()
            # First row is the survivor.
            survivor_count += 1
            for row in rows_in_group[1:]:
                ids_to_delete.append(row.id)

        deleted = 0
        if dry_run:
            print(
                f"\n[dry-run] would delete {len(ids_to_delete)} row(s), "
                f"keep {survivor_count} survivor(s) (one per group). "
                f"No changes written."
            )
        else:
            for batch in _chunks(ids_to_delete, 500):
                res = await session.execute(
                    delete(Job).where(Job.id.in_(batch))
                )
                deleted += res.rowcount or 0
            await session.commit()
            print(
                f"\nDeleted {deleted} duplicate job row(s); kept "
                f"{survivor_count} survivor(s). Every (company_id, title) "
                f"pair is now unique."
            )

    await engine.dispose()
    return len(ids_to_delete) if dry_run else deleted


def _chunks(seq: list, n: int) -> Iterable[list]:
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be deleted without committing any changes.",
    )
    args = parser.parse_args()
    asyncio.run(run(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
