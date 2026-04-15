"""Truncate oversized legacy free-text fields on Feedback rows (Finding 53).

Usage (production):
    # Dry run first — prints what would be trimmed, touches nothing:
    docker compose exec backend python -m app.trim_oversized_feedback --dry-run

    # For-real run — truncates the oversized rows:
    docker compose exec backend python -m app.trim_oversized_feedback

Idempotent — re-running is a no-op once every row is under the cap.

Why this exists
---------------
Finding 25 bounded every long Feedback free-text field to 8,000 chars via
Pydantic `max_length=` on `FeedbackCreate` — but that only affects *new*
submissions. Pre-existing rows remained untouched, and Finding 53 surfaced
that `GET /api/v1/feedback` was serving a ~1 MB `description` field on a
legacy row (a Round-2 probe submission) to every caller. The React table
CSS-truncates the cell, but the DOM still carries the full string, which
bloats TTFB and wastes bandwidth on the list endpoint.

This script applies the same 8,000-char cap to the stored rows so the
list serializer no longer ships 1 MB strings. Each trimmed field gets a
` [truncated legacy row]` marker appended so it's obvious in the UI that
the ticket was retroactively shortened (auditability).

Fields trimmed (same set Pydantic already caps on write):
  - description, steps_to_reproduce, expected_behavior, actual_behavior,
    use_case, proposed_solution, impact, admin_notes

`title` is already bounded to 200 chars by the column type (String(200)),
so it can't exceed the cap. Not touched here.
"""

import argparse
import asyncio
from datetime import datetime, timezone

from sqlalchemy import select, or_, func
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.models.feedback import Feedback

settings = get_settings()

# Keep in lockstep with `_LONG_TEXT_MAX` in app/schemas/feedback.py —
# the Pydantic bound on writes should match the cleanup bound on reads,
# otherwise newly-submitted rows would immediately get re-trimmed.
_LONG_TEXT_MAX = 8000

# Fields that are free-text and Pydantic-bounded to _LONG_TEXT_MAX on write.
# Mirror of FeedbackCreate + FeedbackUpdate fields of type `str | None`.
_BOUNDED_FIELDS = (
    "description",
    "steps_to_reproduce",
    "expected_behavior",
    "actual_behavior",
    "use_case",
    "proposed_solution",
    "impact",
    "admin_notes",
)

_TRUNCATION_MARKER = " [truncated legacy row]"


def _needs_trim(value: str | None) -> bool:
    return value is not None and len(value) > _LONG_TEXT_MAX


def _trimmed(value: str) -> str:
    # Reserve the marker length so the final string is still ≤ _LONG_TEXT_MAX.
    keep = _LONG_TEXT_MAX - len(_TRUNCATION_MARKER)
    return value[:keep] + _TRUNCATION_MARKER


async def run(dry_run: bool) -> int:
    engine = create_async_engine(settings.database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    trimmed_rows = 0
    trimmed_fields = 0

    async with async_session() as session:
        # Narrow the scan — only pull rows where at least one bounded
        # column exceeds the cap. Avoids loading the whole feedback table
        # just to no-op most of it.
        length_over_cap = [
            func.length(getattr(Feedback, col)) > _LONG_TEXT_MAX
            for col in _BOUNDED_FIELDS
        ]
        result = await session.execute(
            select(Feedback).where(or_(*length_over_cap))
        )
        rows = result.scalars().all()

        print(f"Found {len(rows)} feedback row(s) with at least one oversized field.")

        for fb in rows:
            per_row_fields = []
            for col in _BOUNDED_FIELDS:
                current = getattr(fb, col)
                if _needs_trim(current):
                    per_row_fields.append((col, len(current)))
                    if not dry_run:
                        setattr(fb, col, _trimmed(current))
            if per_row_fields:
                trimmed_rows += 1
                trimmed_fields += len(per_row_fields)
                print(
                    f"  {'DRY ' if dry_run else 'TRIM'} id={fb.id} "
                    f"user={fb.user_id} created={fb.created_at.isoformat() if fb.created_at else 'n/a'}"
                )
                for col, length in per_row_fields:
                    print(f"    - {col}: {length} chars → {_LONG_TEXT_MAX}")

        if dry_run:
            print(
                f"\n[dry-run] would trim {trimmed_fields} field(s) across "
                f"{trimmed_rows} row(s). No changes written."
            )
        else:
            await session.commit()
            print(
                f"\nTrimmed {trimmed_fields} field(s) across {trimmed_rows} row(s)."
            )

    await engine.dispose()
    return trimmed_rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be trimmed without committing any changes.",
    )
    args = parser.parse_args()
    asyncio.run(run(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
