"""Purge historical unsafe-scheme `profile_url`s and legacy `archived_*`
credential rows (Findings 77, 78).

Usage (production):
    # Dry run first — prints what would change, touches nothing:
    docker compose exec backend python -m app.cleanup_credentials --dry-run

    # For-real run:
    docker compose exec backend python -m app.cleanup_credentials

Idempotent — re-running is a no-op once historical rows are cleaned.

Why this exists
---------------
Finding 77 (HIGH): `POST /credentials/{resume_id}` accepted `javascript:`,
`data:`, and `vbscript:` URLs in `profile_url` and stored them verbatim.
The frontend rendered them as `<a href={profile_url}>`, so a click ran
the payload in the viewer's session. The ingest-time fix (same commit as
this script) replaces `body: dict` with a Pydantic `CredentialCreate`
whose validator rejects unsafe schemes. This script zeros out any
historical rows that slipped through before the fix.

Finding 78 (MEDIUM): `DELETE /credentials/{resume_id}/{platform}` used to
archive by prefixing the email with `archived_` and blanking the password,
leaving the row in the DB. GDPR Art.17 ("right to erasure") was violated,
and users who thought they'd deleted a credential saw it reappear with a
corrupted email. The new delete is a real `db.delete(cred)`; this script
purges the legacy `archived_*` rows retroactively.

Semantics
---------
Two passes:
  1. **Unsafe URL scrub**: any row whose `profile_url` starts with a
     banned scheme (javascript:, data:, vbscript:, file:, about:, ...)
     gets `profile_url=""`. We do NOT delete the row — the credential
     (email, password) is still valid; only the URL field is neutered.
  2. **Archived-row deletion**: any row whose `email LIKE 'archived_%'`
     is deleted. The prior archive mechanism already blanked the
     password and unset `is_verified`, so these rows are useless to the
     owning user.

Banned URL schemes are matched case-insensitively. The safe-scheme
allowlist (http/https/relative) is NOT used here — we only remove what
we know is dangerous, rather than potentially deleting an unusual but
harmless value.
"""

import argparse
import asyncio
from typing import Iterable

from sqlalchemy import select, delete, update, func
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.models.platform_credential import PlatformCredential

settings = get_settings()

# Schemes to scrub. Keep in sync with `utils/sanitize._SAFE_SCHEMES`
# inverse and `schemas/credential._URL_SAFE_SCHEMES`. These five cover
# every known browser-executable-in-an-<a href=> scheme.
_BANNED_SCHEMES = ("javascript:", "data:", "vbscript:", "file:", "about:")


def _has_unsafe_scheme(value: str) -> bool:
    if not value:
        return False
    low = value.strip().lower()
    return any(low.startswith(s) for s in _BANNED_SCHEMES)


async def run(dry_run: bool) -> tuple[int, int]:
    engine = create_async_engine(settings.database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    scrubbed = 0
    deleted = 0

    async with async_session() as session:
        # Pass 1: unsafe URL scrub. Pull only rows with a non-empty
        # profile_url — small population, safe to materialize.
        url_rows = (await session.execute(
            select(PlatformCredential).where(
                func.char_length(PlatformCredential.profile_url) > 0
            )
        )).scalars().all()

        print(f"Scanned {len(url_rows)} row(s) with a non-empty profile_url.")

        scrub_ids: list = []
        for c in url_rows:
            if _has_unsafe_scheme(c.profile_url):
                scrub_ids.append(c.id)
                print(
                    f"  SCRUB id={c.id} platform={c.platform!r} "
                    f"email={c.email!r} profile_url={c.profile_url!r}"
                )
                scrubbed += 1

        # Pass 2: archived-row deletion. SQL `LIKE 'archived_%'` on email.
        archived_rows = (await session.execute(
            select(PlatformCredential).where(
                PlatformCredential.email.like("archived_%")
            )
        )).scalars().all()

        print(
            f"Scanned {len(archived_rows)} row(s) with "
            f"email LIKE 'archived_%' (legacy soft-archive)."
        )

        archived_ids: list = [r.id for r in archived_rows]
        for r in archived_rows:
            print(
                f"  DEL   id={r.id} platform={r.platform!r} email={r.email!r}"
            )
            deleted += 1

        if dry_run:
            print(
                f"\n[dry-run] would scrub {scrubbed} unsafe profile_url(s) "
                f"and delete {deleted} archived row(s). No changes written."
            )
        else:
            # Batch updates / deletes to avoid parameter-limit ceilings.
            if scrub_ids:
                for batch in _chunks(scrub_ids, 500):
                    await session.execute(
                        update(PlatformCredential)
                        .where(PlatformCredential.id.in_(batch))
                        .values(profile_url="")
                    )
            if archived_ids:
                for batch in _chunks(archived_ids, 500):
                    await session.execute(
                        delete(PlatformCredential)
                        .where(PlatformCredential.id.in_(batch))
                    )
            await session.commit()
            print(
                f"\nScrubbed {scrubbed} unsafe profile_url(s); "
                f"deleted {deleted} archived row(s). "
                f"Credentials table is now policy-compliant."
            )

    await engine.dispose()
    return scrubbed, deleted


def _chunks(seq: list, n: int) -> Iterable[list]:
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would change without committing any changes.",
    )
    args = parser.parse_args()
    asyncio.run(run(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
