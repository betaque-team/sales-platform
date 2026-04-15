"""Close legacy duplicate feedback tickets created before the Finding 11 dedup fix.

Usage (production):
    # Dry run first — prints what would be closed, touches nothing:
    docker compose exec backend python -m app.close_legacy_duplicate_feedback --dry-run

    # For-real run — closes the duplicates:
    docker compose exec backend python -m app.close_legacy_duplicate_feedback

Idempotent — re-running is a no-op once there are no more open duplicate groups.

Why this exists
---------------
Finding 11 (regression test report) surfaced eight identical
"Resume Score / Relevance" tickets from the same user, all still open.
The API fix that shipped in the same report adds a 409 dedup check on
*new* submissions (same user + category + lowercased title, open within
7 days), but the already-present historical duplicates don't go away on
their own — this script retroactively applies the same dedup rule and
closes the duplicates. Finding 31 tracks this cleanup.

Semantics
---------
For each (user_id, category, lower(title)) group that has more than one
ticket in status ("open", "in_progress"):
  - keep the OLDEST ticket open (users' history + replies accrue there);
  - close every newer ticket in the group with:
      status        = "closed"
      resolved_at   = now()
      admin_notes   = (existing notes + a system marker pointing to
                       the canonical ticket id so auditors can trace
                       the auto-close)
      resolved_by   = NULL (system action, not attributed to a user)
"""

import argparse
import asyncio
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.models.feedback import Feedback

settings = get_settings()

# Match the API's dedup predicate exactly — same statuses the API
# considers "still open" for dedup purposes. Keep in sync with
# app/api/v1/feedback.py::create_feedback.
ACTIVE_STATUSES = ("open", "in_progress")


def _system_note(canonical_id) -> str:
    return (
        f"[system] Auto-closed as a duplicate of {canonical_id} by "
        f"close_legacy_duplicate_feedback ({datetime.now(timezone.utc).date().isoformat()}). "
        f"Original submission retained for history."
    )


async def run(dry_run: bool) -> int:
    engine = create_async_engine(settings.database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    closed_count = 0
    groups_count = 0

    async with async_session() as session:
        result = await session.execute(
            select(Feedback)
            .where(Feedback.status.in_(ACTIVE_STATUSES))
            .order_by(Feedback.created_at.asc())
        )
        active = result.scalars().all()

        # Bucket by the same key the API uses for its 409 check:
        # (user_id, category, lowercased/stripped title).
        groups: dict[tuple, list[Feedback]] = defaultdict(list)
        for fb in active:
            key = (fb.user_id, fb.category, (fb.title or "").strip().lower())
            groups[key].append(fb)

        for key, tickets in groups.items():
            if len(tickets) < 2:
                continue
            groups_count += 1
            # The query above ordered by created_at ASC, so [0] is the oldest.
            canonical = tickets[0]
            dupes = tickets[1:]

            print(
                f"group: user={canonical.user_id} category={canonical.category} "
                f"title={canonical.title!r} -> keep {canonical.id} "
                f"(created {canonical.created_at.isoformat()}), "
                f"close {len(dupes)} duplicate(s)"
            )

            for dup in dupes:
                print(
                    f"  - closing {dup.id} (status was '{dup.status}', "
                    f"created {dup.created_at.isoformat()})"
                )
                if dry_run:
                    continue
                dup.status = "closed"
                dup.resolved_at = datetime.now(timezone.utc)
                note = _system_note(canonical.id)
                dup.admin_notes = (
                    f"{dup.admin_notes}\n\n{note}" if dup.admin_notes else note
                )
                closed_count += 1

        if dry_run:
            print(f"\n[dry-run] would close {sum(len(v) - 1 for v in groups.values() if len(v) > 1)} "
                  f"ticket(s) across {groups_count} duplicate group(s). No changes written.")
        else:
            await session.commit()
            print(f"\nClosed {closed_count} duplicate ticket(s) across {groups_count} group(s).")

    await engine.dispose()
    return closed_count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be closed without committing any changes.",
    )
    args = parser.parse_args()
    asyncio.run(run(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
