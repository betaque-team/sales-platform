"""Trim oversized `question` / `answer` columns in `answer_book_entries`
(Finding 80).

Usage (production):
    # Dry run first — prints what would be trimmed, touches nothing:
    docker compose exec backend python -m app.trim_oversized_answer_book --dry-run

    # For-real run:
    docker compose exec backend python -m app.trim_oversized_answer_book

Idempotent — re-running is a no-op once every row fits under the caps.

Why this exists
---------------
Before Finding 80's ingest-time fix, `POST /api/v1/answer-book` and
`PATCH /api/v1/answer-book/{id}` accepted `body: dict` with no length
validation. `question` and `answer` are both Postgres `Text` columns,
so a malformed or malicious client could POST a multi-megabyte payload
and it was stored verbatim — bloating every `GET /answer-book` response
(paginated at 50, full rows shipped).

Same shape as `trim_oversized_feedback.py` (Finding #53 cleanup). This
script walks `answer_book_entries`, finds rows whose text columns
exceed the new caps, and truncates them with an explicit elision
marker so the row is still legible but within bounds.

Semantics
---------
For each `AnswerBookEntry`:
  - If `char_length(question) > 2000` → truncate to `1984 + " [TRUNCATED]"`
    (16-char marker keeps total at exactly 2000).
  - If `char_length(answer) > 8000` → truncate to `7984 + " [TRUNCATED]"`.

Rows under both caps are skipped. `question_key` is left unchanged —
even if the source question is truncated, the normalized key remains
a valid matcher. We don't delete any row; historical answers are kept
where legible.
"""

import argparse
import asyncio
from typing import Iterable

from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.models.answer_book import AnswerBookEntry

settings = get_settings()

# Keep in lockstep with `schemas/answer_book._QUESTION_MAX` and
# `_ANSWER_MAX`. The truncation marker is counted in the cap — a
# 2000-char max means we truncate raw content to 1984 + the 16-char
# marker " [TRUNCATED]" (12 visible chars + leading space + marker
# punctuation).
_QUESTION_MAX = 2000
_ANSWER_MAX = 8000
_TRUNC_MARKER = " [TRUNCATED]"  # 12 chars including the leading space


def _truncated(value: str, cap: int) -> str:
    """Truncate `value` so that `len(result) <= cap`, appending the
    elision marker. Idempotent on inputs already at/below cap.
    """
    if len(value) <= cap:
        return value
    keep = cap - len(_TRUNC_MARKER)
    if keep < 0:
        # Defensive — the cap is always way bigger than the marker, but
        # if some future caller passes a tiny cap, just hard-truncate.
        return value[:cap]
    return value[:keep] + _TRUNC_MARKER


async def run(dry_run: bool) -> tuple[int, int]:
    engine = create_async_engine(settings.database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    trimmed_q = 0
    trimmed_a = 0

    async with async_session() as session:
        # Pull only rows where at least one column is over-cap —
        # cheap server-side filter, avoids loading the entire table
        # into memory on large user bases.
        result = await session.execute(
            select(AnswerBookEntry).where(
                (func.char_length(AnswerBookEntry.question) > _QUESTION_MAX)
                | (func.char_length(AnswerBookEntry.answer) > _ANSWER_MAX)
            )
        )
        rows = result.scalars().all()

        print(f"Found {len(rows)} over-cap row(s).")

        updates: list[tuple] = []  # (id, new_question, new_answer)
        for e in rows:
            new_q = _truncated(e.question or "", _QUESTION_MAX)
            new_a = _truncated(e.answer or "", _ANSWER_MAX)
            changed_q = new_q != (e.question or "")
            changed_a = new_a != (e.answer or "")
            if not (changed_q or changed_a):
                continue
            if changed_q:
                trimmed_q += 1
                print(
                    f"  TRIM  id={e.id} question "
                    f"{len(e.question or ''):>6d} -> {len(new_q):>6d}"
                )
            if changed_a:
                trimmed_a += 1
                print(
                    f"  TRIM  id={e.id} answer   "
                    f"{len(e.answer or ''):>6d} -> {len(new_a):>6d}"
                )
            updates.append((e.id, new_q, new_a))

        if dry_run:
            print(
                f"\n[dry-run] would trim {trimmed_q} question(s) and "
                f"{trimmed_a} answer(s). No changes written."
            )
        else:
            # Per-row UPDATE — each row has its own new content, so a
            # single `UPDATE … WHERE id IN (…)` won't work. Batching
            # via executemany keeps the round-trip count down.
            for batch in _chunks(updates, 200):
                for eid, nq, na in batch:
                    await session.execute(
                        update(AnswerBookEntry)
                        .where(AnswerBookEntry.id == eid)
                        .values(question=nq, answer=na)
                    )
                await session.commit()
            print(
                f"\nTrimmed {trimmed_q} question(s) and {trimmed_a} "
                f"answer(s). `answer_book_entries` is now within caps."
            )

    await engine.dispose()
    return trimmed_q, trimmed_a


def _chunks(seq: list, n: int) -> Iterable[list]:
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


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
