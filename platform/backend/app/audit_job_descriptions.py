"""Report `JobDescription` population rates per cluster and per platform (Finding 97).

Usage:
    docker compose exec backend python -m app.audit_job_descriptions

Read-only — emits a table to stdout showing, per (role_cluster, platform):
total job rows, rows with no `JobDescription` row or whose `text_content`
is shorter than 100 chars (call that "empty-or-tiny"), and the
percentage. No DB writes.

Why this exists
---------------
The scan pipeline used to drop the description text that every ATS
fetcher already pulled from upstream — the `Job.raw_json` blob was
preserved but nothing ever populated `JobDescription.text_content`. The
ATS scoring task reads only from `JobDescription`, so for 50%+ of rows
the keyword extractor received `description_text=""`, fell back to the
role-cluster baseline, and produced byte-identical matched/missing
keyword lists across 200+ jobs. Overall ATS scores collapsed to 4
distinct values across the relevant-jobs pool.

Run this after deploying the scan-pipeline fix to confirm the coverage
gap is closing scan cycle by scan cycle. Expect the first run post-deploy
to still show high empty-percentages; subsequent runs should show the
percentage dropping as the scan cycle re-upserts each slug.

The threshold is `< 100 chars` rather than `IS NULL or = ''` because
some fetchers' list-endpoint responses contain a 20-char stub like
"See full job description on our site." which is useless for keyword
matching. Treating those as "empty" surfaces the real gap.
"""

import asyncio

from sqlalchemy import case, func, select

from app.database import engine as async_engine
from app.models.job import Job, JobDescription


async def _main() -> None:
    # Use the raw async engine directly so this script can be run outside
    # the FastAPI request lifecycle (and outside Celery's sync session).
    from sqlalchemy.ext.asyncio import AsyncSession

    async with AsyncSession(async_engine) as session:
        # Per-row empty_or_tiny expression — 1 when no JD row exists OR the
        # text is shorter than the usable threshold, else 0. The two
        # branches in `case(...)` both resolve to 1 because `sum` over
        # these gives us the count of empty rows for free.
        empty_expr = case(
            (JobDescription.text_content.is_(None), 1),
            (func.length(JobDescription.text_content) < 100, 1),
            else_=0,
        )

        # LEFT JOIN so jobs without a `JobDescription` row still show up
        # (those are the worst case — no row at all, definitely empty).
        rows = (
            await session.execute(
                select(
                    Job.role_cluster,
                    Job.platform,
                    func.count(Job.id).label("total"),
                    func.sum(empty_expr).label("empty_or_tiny"),
                )
                .outerjoin(JobDescription, JobDescription.job_id == Job.id)
                .group_by(Job.role_cluster, Job.platform)
                .order_by(func.count(Job.id).desc())
            )
        ).all()

        print(
            f"{'cluster':<15s} {'platform':<18s} "
            f"{'total':>8s} {'empty':>8s} {'%':>6s}"
        )
        print("-" * 60)
        for r in rows:
            total = int(r.total or 0)
            empty = int(r.empty_or_tiny or 0)
            pct = 100 * empty / max(total, 1)
            cluster_label = r.role_cluster or "(none)"
            print(
                f"{cluster_label:<15s} {r.platform:<18s} "
                f"{total:>8d} {empty:>8d} {pct:>5.1f}%"
            )

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main())
