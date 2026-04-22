"""Auto-probe companies that recently received funding.

Why this task exists
--------------------
A Series A / B / C announcement is a **leading indicator** for
hiring: post-funding cos typically open 5-15 new reqs within 60
days of the announcement. If we only discover them when their ATS
board appears in our generic probe list (up to weeks later),
competitors already have the leads.

This task closes that gap. We already have funding dates flowing in
via ``services/enrichment/crunchbase_provider.py`` → populating
``Company.funded_at``. This task consumes that signal:

    1. Select Companies where ``funded_at`` is within the last
       ``RECENT_FUNDING_WINDOW_DAYS`` (default 30).
    2. Filter to cos we haven't probed in the last
       ``PROBE_COOLDOWN_DAYS`` (default 7) — so repeat runs don't
       hammer the same set.
    3. Mark ``is_target=True`` — post-funding cos are the highest-
       priority outreach bucket.
    4. Fingerprint the company's public careers page via
       ``app.services.ats_fingerprint.detect_ats_from_url``. Any
       ``(platform, slug)`` pairs we don't already know about get
       filed as ``DiscoveredCompany`` rows and picked up by the
       existing promotion path (``discover_and_add_boards``) on
       its next tick.

Idempotent + rate-safe
----------------------
* ``careers_url_fetched_at`` doubles as a probe cooldown. Even if
  the probe fails, we bump the timestamp so the next schedule tick
  doesn't re-hammer.
* ``DiscoveredCompany.platform + slug`` dedup avoids double-adding
  boards that already exist (same pattern as
  ``fingerprint_existing_companies``).

Design decision — why a new module
----------------------------------
``discovery_task.py`` is already ~850 lines and bundles ATS-centric
discovery (slug probes, sitemap crawls). The funding trigger is a
different *origin* of discovery (company-centric, signal-driven),
even though it reuses the same fingerprint primitive. Splitting
keeps each module's "why" clear and makes the beat schedule readable
("what's this task's purpose?" is answered by the filename).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.workers.celery_app import celery_app
from app.workers.tasks._db import SyncSession
from app.models.company import Company
from app.models.discovery import DiscoveryRun, DiscoveredCompany


logger = logging.getLogger(__name__)


# Tunables — intentionally generous defaults. Push them tighter
# only if beat-runtime becomes a problem; the HTTP cost is ~3
# fetches per company (tries `/careers`, `/jobs`, `/` in order).
RECENT_FUNDING_WINDOW_DAYS = 30
PROBE_COOLDOWN_DAYS = 7


def _pick_candidates(
    companies: list,
    cooldown_cutoff: datetime,
    limit: int,
) -> tuple[list, int]:
    """Pure helper — filters a pre-fetched candidate list by the
    cooldown rule.

    Extracted so it's unit-testable without an SQLAlchemy session.
    ``companies`` is whatever the outer query returned (already
    filtered by ``funded_at`` window server-side). This function
    applies the "probe cooldown" in Python because it's cheap and
    the candidate set is small (tens, not thousands).

    Returns ``(to_probe, skipped_by_cooldown_count)`` where
    ``to_probe`` preserves the input order (freshest-funding-first
    from the outer ``ORDER BY Company.funded_at DESC`` query).
    """
    to_probe = []
    skipped = 0
    for co in companies:
        if co.careers_url_fetched_at and co.careers_url_fetched_at >= cooldown_cutoff:
            skipped += 1
            continue
        to_probe.append(co)
        if len(to_probe) >= limit:
            break
    return to_probe, skipped


@celery_app.task(
    name="app.workers.tasks.funding_followup_task.auto_probe_recent_funding",
    bind=True,
    max_retries=1,
)
def auto_probe_recent_funding(self, window_days: int = RECENT_FUNDING_WINDOW_DAYS, cooldown_days: int = PROBE_COOLDOWN_DAYS, limit: int = 100):
    """Fingerprint every recently-funded company's careers page.

    Args:
        window_days: How far back to look for new funding events.
            Defaults to 30 — captures the "just got funded" burst
            without re-chewing cos from months ago.
        cooldown_days: How long to wait before re-probing a
            company that was probed once (successfully or not).
            Defaults to 7 — once a week per funded co is plenty;
            ATS choices don't churn faster than that.
        limit: Hard cap on companies processed per invocation. The
            defaults expect a few dozen/month; the cap prevents a
            single run from saturating the worker if someone turns
            on a larger historical funding backfill.

    Returns dict with ``{candidates, scanned, new_boards,
    already_probed, errors, run_id}``.
    """
    # Import here — avoids a module-load cycle with the ATS service
    # (which in turn imports httpx lazily, etc.).
    from app.services.ats_fingerprint import detect_ats_from_url

    session = SyncSession()
    try:
        now = datetime.now(timezone.utc)
        funded_cutoff = now - timedelta(days=window_days)
        cooldown_cutoff = now - timedelta(days=cooldown_days)

        run = DiscoveryRun(
            id=uuid.uuid4(),
            source="funding_followup",
            status="running",
        )
        session.add(run)
        session.flush()

        # Candidate query:
        #   - funded recently (within window)
        #   - has a website we can fetch
        #   - either never probed OR not probed in the last cooldown window
        # Ordering: freshest funding first — if we hit `limit` we
        # prefer the most recent events.
        q = (
            select(Company)
            .where(
                Company.funded_at.is_not(None),
                Company.funded_at >= funded_cutoff,
                Company.website != "",
            )
            .order_by(Company.funded_at.desc())
        )
        candidates_all = session.execute(q).scalars().all()

        # Python-side cooldown filter — delegated to the pure helper
        # so it can be unit-tested without an SQLAlchemy session.
        candidates, already_probed = _pick_candidates(
            list(candidates_all), cooldown_cutoff, limit
        )

        # Pre-load (platform, slug) pairs so we dedup without a DB
        # round-trip per detected ATS. Same pattern as
        # `fingerprint_existing_companies`.
        existing_pairs = set(
            (p, s)
            for p, s in session.execute(
                select(DiscoveredCompany.platform, DiscoveredCompany.slug)
            ).all()
        )

        scanned = 0
        new_boards = 0
        errors = 0

        for company in candidates:
            scanned += 1

            # F-specific: mark post-funding cos as targets. Cheap and
            # it's the right signal regardless of whether the probe
            # finds a new ATS — the sales side wants these cos on the
            # pipeline board either way.
            if not company.is_target:
                company.is_target = True
                session.add(company)

            matched_url: str | None = None
            fps: list = []
            try:
                # Try `/careers`, `/jobs`, root — in that order. First
                # page that yields any ATS marker wins. Matches the
                # existing pattern in `fingerprint_existing_companies`.
                for suffix in ("/careers", "/jobs", ""):
                    target = company.website.rstrip("/") + suffix
                    fps = detect_ats_from_url(target, timeout=15)
                    if fps:
                        matched_url = target
                        break
            except Exception as exc:
                errors += 1
                logger.warning(
                    "funding_followup fingerprint failed for %s (website=%s): %s",
                    company.name, company.website, exc,
                )
                # Fall through — we still bump the cooldown so a bad
                # host doesn't get retried every beat.

            # Always update the cooldown timestamp — even on "no ATS
            # found" outcomes. This prevents the same co getting re-
            # fetched on every beat tick during the cooldown window.
            company.careers_url_fetched_at = now
            if matched_url:
                company.careers_url = matched_url
            session.add(company)

            # Translate fingerprints to DiscoveredCompany rows. Dedup
            # against the pre-loaded set to avoid UNIQUE-violation
            # retries on boards we already know about.
            for fp in fps:
                key = (fp.platform, fp.slug)
                if key in existing_pairs:
                    continue
                session.add(DiscoveredCompany(
                    id=uuid.uuid4(),
                    discovery_run_id=run.id,
                    name=company.name or fp.slug.replace("-", " ").title(),
                    platform=fp.platform,
                    slug=fp.slug,
                    careers_url=fp.careers_url,
                    status="new",
                    # Stamp the origin so a follow-up audit can tell
                    # "came from post-funding probe" apart from "came
                    # from reverse fingerprinting". Useful when
                    # diagnosing why a particular board appeared.
                    relevance_hint=(
                        f"post-funding fingerprint of {company.website} "
                        f"(company_id={company.id}, "
                        f"funded_at={company.funded_at.date() if company.funded_at else '?'})"
                    ),
                ))
                existing_pairs.add(key)
                new_boards += 1

        run.completed_at = now
        run.companies_found = scanned
        run.new_companies = new_boards
        run.status = "completed"
        session.commit()

        logger.info(
            "funding_followup: candidates=%d, scanned=%d, new_boards=%d, "
            "already_probed=%d, errors=%d",
            len(candidates_all), scanned, new_boards, already_probed, errors,
        )
        return {
            "candidates": len(candidates_all),
            "scanned": scanned,
            "new_boards": new_boards,
            "already_probed": already_probed,
            "errors": errors,
            "run_id": str(run.id),
            "window_days": window_days,
            "cooldown_days": cooldown_days,
        }

    except Exception as exc:
        logger.exception("funding_followup task failed: %s", exc)
        session.rollback()
        raise self.retry(exc=exc, countdown=300)
    finally:
        session.close()
