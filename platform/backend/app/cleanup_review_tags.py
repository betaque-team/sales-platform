"""Null out `tags` on historical non-rejected Review rows (Finding 73).

Usage (production):
    # Dry run first — prints what would be updated, touches nothing:
    docker compose exec backend python -m app.cleanup_review_tags --dry-run

    # For-real run — zeroes out tags on accepted/skipped rows:
    docker compose exec backend python -m app.cleanup_review_tags

Idempotent — re-running is a no-op once the historical rows are fixed.

Why this exists
---------------
Finding 73 surfaced that the Review submit endpoint used to store
`tags=body.tags` unconditionally, and the frontend on `/review` carried
`selectedTags` across prev/next navigation (finding 72) and submitted
those tags in the Accept payload as well. So Review rows with
`decision in ("accepted", "skipped")` ended up with rejection-tag
strings attached — contaminating the rejection-reason histogram used
by analytics.

The ingest-time fix (same commit as this script) drops `tags` when
`decision != "rejected"`. This script applies the same invariant
retroactively: any historical accepted/skipped row with a non-empty
`tags` array gets set to `[]`.

Semantics
---------
- Scope: `decision in ('accepted', 'skipped') AND cardinality(tags) > 0`
- Action: `UPDATE reviews SET tags = '{}' WHERE id IN (...)`
- `comment` is left alone — the reviewer may have written a genuine
  "great fit" comment; only tags are the contaminated field.
- No FK cascade risk: `tags` is a `text[]` column, not a relation.
"""

import argparse
import asyncio
from typing import Iterable

from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.models.review import Review

settings = get_settings()


async def run(dry_run: bool) -> int:
    engine = create_async_engine(settings.database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # Pre-filter at the DB: only rows that actually have tags to clear.
        # `cardinality(tags) > 0` is the Postgres idiom; it hits the same
        # index/scan path as `tags != '{}'` but is clearer in intent.
        result = await session.execute(
            select(Review).where(
                Review.decision.in_(("accepted", "skipped")),
                func.cardinality(Review.tags) > 0,
            )
        )
        rows = result.scalars().all()

        print(f"Scanned {len(rows)} non-rejected review row(s) with non-empty tags.")

        to_clear = []
        for r in rows:
            print(
                f"  CLEAR id={r.id} decision={r.decision!r:10s} "
                f"tags={r.tags!r} created_at={r.created_at.isoformat()}"
            )
            to_clear.append(r.id)

        if dry_run:
            print(
                f"\n[dry-run] would clear tags on {len(to_clear)} row(s). "
                f"No changes written."
            )
        else:
            if to_clear:
                # Chunk the UPDATE so a large backlog doesn't hit the
                # parameter-limit ceiling. 500 per batch is well under
                # Postgres's 65k parameter max.
                for batch in _chunks(to_clear, 500):
                    await session.execute(
                        update(Review)
                        .where(Review.id.in_(batch))
                        .values(tags=[])
                    )
                await session.commit()
            print(
                f"\nCleared tags on {len(to_clear)} non-rejected review row(s). "
                f"Rejection-reason histogram baseline is now clean."
            )

    await engine.dispose()
    return len(to_clear)


def _chunks(seq: list, n: int) -> Iterable[list]:
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be updated without committing any changes.",
    )
    args = parser.parse_args()
    asyncio.run(run(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
