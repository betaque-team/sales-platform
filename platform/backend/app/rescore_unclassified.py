"""Zero out `relevance_score` on unclassified `jobs` rows (Finding 86).

Usage (production):
    # Dry run first — prints what would be updated, touches nothing:
    docker compose exec backend python -m app.rescore_unclassified --dry-run

    # For-real run — zeros out unclassified rows:
    docker compose exec backend python -m app.rescore_unclassified

Idempotent — re-running is a no-op once every unclassified row is
already at score 0.

Why this exists
---------------
Before Finding 86's ingest-time fix, `compute_relevance_score` applied
60% of the weighted sum to company-fit / geography-clarity / source-
priority / freshness signals even when the title-match score was 0.
Result: 42,966 of the 47,776 rows in `jobs` (89.9%) were unclassified
(`role_cluster IS NULL OR role_cluster = ''`) but had non-zero
relevance scores ranging from 14 to 54. Live examples from the audit:

  - "Junior Software Developer"       cluster='' → score 17
  - "Talent Acquisition Coordinator"  cluster='' → score 44
  - "Human Data Reviewer"             cluster='' → score 42

The 44 for "Talent Acquisition Coordinator" was outranking legitimate
security jobs with sub-50 scores in the cross-cluster `/jobs?sort_by=
relevance_score desc` sort.

The code fix (this commit) short-circuits `compute_relevance_score`
to return 0 when `_title_match_score == 0`, matching the documented
contract in CLAUDE.md ("Jobs outside these clusters are saved but
unscored (relevance_score = 0)"). This script applies the same
correction to the backlog so the new and old rows share one baseline.

Semantics
---------
For each `Job` with `role_cluster IS NULL OR role_cluster = ''` AND
`relevance_score > 0`: set `relevance_score = 0.0`. Nothing else is
touched — the classification columns (`matched_role`, `role_cluster`,
`title_normalized`) are preserved; only the scalar score is zeroed.

Status-agnostic on purpose: a rejected unclassified job should still
report score 0 for consistency with the new ingest contract. The
regular `rescore_jobs` maintenance task only covers active statuses
(`new`, `under_review`, `accepted`) so this script is the broader
net.
"""

import argparse
import asyncio
from typing import Iterable

from sqlalchemy import select, update, or_, func
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.models.job import Job

settings = get_settings()


async def run(dry_run: bool) -> int:
    engine = create_async_engine(settings.database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    updated = 0

    async with async_session() as session:
        # Target rows: unclassified (NULL or empty string) with a
        # non-zero score. Cheap server-side filter — no need to pull
        # 47k rows into memory.
        target_predicate = (
            (or_(Job.role_cluster.is_(None), Job.role_cluster == ""))
            & (Job.relevance_score > 0)
        )

        count_result = await session.execute(
            select(func.count()).select_from(Job).where(target_predicate)
        )
        to_update = count_result.scalar() or 0

        print(f"Found {to_update} unclassified row(s) with relevance_score > 0.")

        if dry_run:
            # Pull a small sample so the operator can eyeball what's
            # about to change without committing anything.
            sample_result = await session.execute(
                select(Job.id, Job.title, Job.role_cluster, Job.relevance_score)
                .where(target_predicate)
                .limit(10)
            )
            for jid, title, cluster, score in sample_result:
                print(
                    f"  ZERO  id={jid} score={score:>5.1f} "
                    f"cluster={cluster!r:6s} title={title!r}"
                )
            print(
                f"\n[dry-run] would zero {to_update} row(s). "
                "No changes written."
            )
        else:
            # Single UPDATE is the right shape — every target row gets
            # the same value (0.0), so no per-row logic is needed.
            await session.execute(
                update(Job).where(target_predicate).values(relevance_score=0.0)
            )
            await session.commit()
            updated = to_update
            print(
                f"\nZeroed relevance_score on {updated} unclassified "
                "row(s). New ingest contract now holds across the backlog."
            )

    await engine.dispose()
    return updated


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be zeroed without committing any changes.",
    )
    args = parser.parse_args()
    asyncio.run(run(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
