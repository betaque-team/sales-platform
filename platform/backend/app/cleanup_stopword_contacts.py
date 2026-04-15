"""Delete CompanyContact rows whose names are English-stop-word noise (Finding 60).

Usage (production):
    # Dry run first — prints what would be deleted, touches nothing:
    docker compose exec backend python -m app.cleanup_stopword_contacts --dry-run

    # For-real run — deletes the noise rows:
    docker compose exec backend python -m app.cleanup_stopword_contacts

Idempotent — re-running is a no-op once the noise rows are gone.

Why this exists
---------------
Finding 60 surfaced that 445 / 3,756 rows in the `/api/v1/export/contacts` CSV
had `first_name` (and often `last_name`) matching English stop-words like
`help`, `for`, `us`, `the`, `in`, `with`, etc. Root cause was in
`services/enrichment/internal_provider._CONTACT_PATTERN` — the `re.IGNORECASE`
flag was applied to the whole pattern, so the supposed Capital-Initial
constraint `[A-Z][a-z]+` matched any word. Phrases like "contact us at…" or
"help you apply" became `(first_name, last_name)` pairs, all with empty
email/phone, all flagged `source=job_description`, all titled
"Recruiter / Hiring Contact".

The ingest-time fix (same commit as this script) scopes the IGNORECASE flag
to just the trigger clause and adds a post-match `_looks_like_real_name()`
stop-word filter. This script applies the same predicate retroactively.

Semantics
---------
For each `CompanyContact` whose `source='job_description'` AND either
`first_name` or `last_name` is empty / too short / too long / in the
stop-word set / not Capital-Initial-shaped — delete it. No backlink to
salvage: these rows have no email, phone, linkedin_url, or outreach state
(by construction of how they got generated).

Contacts from `email_pattern` / `website_scrape` / `manual` sources are
never touched — those have real extraction logic that doesn't go through
the broken regex.
"""

import argparse
import asyncio
from typing import Iterable

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.models.company_contact import CompanyContact

settings = get_settings()

# Keep this list in lockstep with
# app/services/enrichment/internal_provider._NAME_STOPWORDS — the ingest
# filter and the cleanup filter should reject the exact same tokens.
_NAME_STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "been", "both", "by",
    "complex", "each", "for", "from", "help", "here", "how", "if",
    "in", "is", "it", "its", "join", "just", "learn", "let", "more",
    "motivated", "now", "of", "on", "or", "our", "read", "should",
    "team", "that", "the", "their", "them", "they", "this", "to",
    "us", "very", "was", "we", "were", "what", "when", "where",
    "who", "with", "you", "your",
})


def _looks_like_real_name_part(part: str) -> bool:
    """Same predicate used by the ingest filter. Single-name-part version."""
    if not part or not (2 <= len(part) <= 20):
        return False
    if not ("A" <= part[0] <= "Z"):
        return False
    if not part[1:].isalpha() or not part[1:].islower():
        return False
    if part.lower() in _NAME_STOPWORDS:
        return False
    return True


def _is_noise_contact(first: str, last: str) -> bool:
    """True iff EITHER name part fails the real-name predicate — junk row."""
    return not (_looks_like_real_name_part(first or "") and _looks_like_real_name_part(last or ""))


async def run(dry_run: bool) -> int:
    engine = create_async_engine(settings.database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    deleted = 0
    kept = 0

    async with async_session() as session:
        # Scope to `source='job_description'` — the only source that went
        # through the buggy extractor. Pulling all rows into memory is fine
        # at the prod volume of ~3,700 contacts.
        result = await session.execute(
            select(CompanyContact).where(CompanyContact.source == "job_description")
        )
        rows = result.scalars().all()

        print(f"Scanned {len(rows)} `job_description`-sourced contact rows.")

        noise_ids = []
        for c in rows:
            if _is_noise_contact(c.first_name, c.last_name):
                noise_ids.append(c.id)
                print(
                    f"  DEL   id={c.id} first={c.first_name!r:20s} "
                    f"last={c.last_name!r:20s} email={c.email!r}"
                )
                deleted += 1
            else:
                kept += 1

        if dry_run:
            print(
                f"\n[dry-run] would delete {deleted} noise row(s), "
                f"keep {kept}. No changes written."
            )
        else:
            if noise_ids:
                # Chunk the DELETE so we don't hit a parameter-limit ceiling
                # on very large purge runs. 500 per batch is well under
                # Postgres's default 65k parameter limit.
                for batch in _chunks(noise_ids, 500):
                    await session.execute(
                        delete(CompanyContact).where(CompanyContact.id.in_(batch))
                    )
                await session.commit()
            print(
                f"\nDeleted {deleted} noise contact row(s), kept {kept}. "
                f"`source='job_description'` table is now stop-word-free."
            )

    await engine.dispose()
    return deleted


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
