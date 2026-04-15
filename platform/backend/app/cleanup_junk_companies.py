"""Delete Company rows whose names are scraper artifacts (Findings 37, 39, 10).

Usage (production):
    # Dry run first — prints what would be deleted, touches nothing:
    docker compose exec backend python -m app.cleanup_junk_companies --dry-run

    # For-real run — deletes the junk rows:
    docker compose exec backend python -m app.cleanup_junk_companies

Idempotent — re-running is a no-op once the junk rows are gone.

Why this exists
---------------
Finding 37 surfaced dozens of junk rows on `/companies` that came from
scraper-side artifacts:
  - LinkedIn hashtag harvest (`#WalkAway Campaign`, `#twiceasnice Recruiting`),
  - Staffing-agency / recruiter shells (`Acme Staffing`, `10000 Solutions LLC`),
  - Purely numeric names (`1800`, `123`),
  - Scratch / test names (`name`, `1name`, `abc`) — Findings 39 and 10.

All of them reached `Company` because nothing upstream rejected them. The
accompanying ingest-time guard now lives in
`app/utils/company_name.py::looks_like_junk_company_name` and is wired into
`app/workers/tasks/scan_task.py` (aggregator upsert) and
`app/api/v1/platforms.py` (admin "add board"). This script retroactively
applies the same rule to already-persisted rows.

Semantics
---------
For each Company whose `name` matches `looks_like_junk_company_name`:

  1. If a `PotentialClient` (sales pipeline entry) is linked to it — skip
     with a warning. That means a human has actually staged it as a deal,
     so we refuse to silently delete and ask the operator to investigate.

  2. Otherwise:
       - null `CareerPageWatch.company_id` rows pointing at it (the URL
         watch itself is still meaningful without the company binding),
       - delete all `Job` rows referencing it (cascades to JobDescription,
         Review, ResumeScore, AICustomizationLog, JobQuestion,
         Application, CompanyContact.job_id),
       - delete the `Company` row (cascades to CompanyATSBoard,
         CompanyContact, CompanyOffice via ORM cascade / FK ON DELETE).

Dry-run prints the same per-row summary but commits nothing.
"""

import argparse
import asyncio
from datetime import datetime, timezone

from sqlalchemy import select, delete, update, func
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.models.company import Company
from app.models.job import Job
from app.models.pipeline import PotentialClient
from app.models.scan import CareerPageWatch
from app.utils.company_name import looks_like_junk_company_name

settings = get_settings()


async def run(dry_run: bool) -> int:
    engine = create_async_engine(settings.database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    deleted_companies = 0
    deleted_jobs = 0
    skipped_with_pipeline = 0

    async with async_session() as session:
        # Pull every Company and filter in Python — the junk predicate is
        # regex-based and keeping the rules in one place (utils/company_name.py)
        # is the whole point. Company table is small enough (<20k rows in
        # the worst case so far) that scanning once per cleanup run is fine.
        result = await session.execute(select(Company).order_by(Company.created_at.asc()))
        companies = result.scalars().all()

        candidates = [c for c in companies if looks_like_junk_company_name(c.name)]

        print(f"Scanned {len(companies)} company rows, {len(candidates)} match junk-name predicate.")

        for c in candidates:
            # Pipeline-entry safety check — if a human has touched this
            # company as a prospective client, leave it alone and surface it.
            pc_count = (await session.execute(
                select(func.count()).select_from(PotentialClient).where(PotentialClient.company_id == c.id)
            )).scalar() or 0
            if pc_count > 0:
                print(
                    f"  SKIP  company={c.id} name={c.name!r} — has {pc_count} "
                    f"PotentialClient row(s); manual investigation required."
                )
                skipped_with_pipeline += 1
                continue

            job_count = (await session.execute(
                select(func.count()).select_from(Job).where(Job.company_id == c.id)
            )).scalar() or 0

            print(
                f"  DEL   company={c.id} name={c.name!r} slug={c.slug!r} "
                f"jobs={job_count} created_at={c.created_at.isoformat() if c.created_at else 'n/a'}"
            )

            if dry_run:
                deleted_jobs += job_count
                deleted_companies += 1
                continue

            # (1) Null CareerPageWatch.company_id — keep the watch row, just
            # unhook it from the junk company.
            await session.execute(
                update(CareerPageWatch)
                .where(CareerPageWatch.company_id == c.id)
                .values(company_id=None)
            )

            # (2) Delete jobs (cascades to JobDescription, Review, ResumeScore,
            # AICustomizationLog, JobQuestion, Application, CompanyContact.job_id).
            # Use bulk DELETE to avoid loading every Job into the session.
            result = await session.execute(
                delete(Job).where(Job.company_id == c.id)
            )
            deleted_jobs += result.rowcount or 0

            # (3) Delete the Company. FK + ORM cascade handles CompanyATSBoard,
            # CompanyContact (company_id), CompanyOffice.
            await session.delete(c)
            deleted_companies += 1

        if dry_run:
            print(
                f"\n[dry-run] would delete {deleted_companies} company row(s) "
                f"and {deleted_jobs} dependent job row(s). "
                f"Skipped {skipped_with_pipeline} with active PotentialClient links. "
                f"No changes written."
            )
        else:
            await session.commit()
            print(
                f"\nDeleted {deleted_companies} company row(s) and {deleted_jobs} "
                f"dependent job row(s). Skipped {skipped_with_pipeline} with "
                f"active PotentialClient links."
            )

    await engine.dispose()
    return deleted_companies


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
