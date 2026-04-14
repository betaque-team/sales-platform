"""Company enrichment Celery tasks."""

import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, or_, func

from app.workers.celery_app import celery_app
from app.workers.tasks._db import SyncSession
from app.models.company import Company
from app.config import get_settings

logger = logging.getLogger(__name__)


@celery_app.task(name="app.workers.tasks.enrichment_task.enrich_company", bind=True, max_retries=2)
def enrich_company(self, company_id: str):
    """Enrich a company record using the self-contained enrichment engine."""
    session = SyncSession()
    try:
        company = session.execute(
            select(Company).where(Company.id == company_id)
        ).scalar_one_or_none()
        if not company:
            logger.warning("Company not found: %s", company_id)
            return {"company_id": company_id, "status": "not_found"}

        company.enrichment_status = "enriching"
        session.commit()

        from app.services.enrichment.orchestrator import run_enrichment
        result = run_enrichment(session, company)

        # Orchestrator already commits final status — just re-read for logging
        session.refresh(company)
        logger.info("Enriched company %s: %s", company.name, result)
        return {"company_id": company_id, "status": company.enrichment_status, **result}

    except Exception as exc:
        logger.exception("enrich_company failed for %s: %s", company_id, exc)
        try:
            company = session.execute(
                select(Company).where(Company.id == company_id)
            ).scalar_one_or_none()
            if company:
                company.enrichment_status = "failed"
                company.enrichment_error = str(exc)[:500]
                session.commit()
        except Exception:
            session.rollback()
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))
    finally:
        session.close()


@celery_app.task(name="app.workers.tasks.enrichment_task.enrich_target_companies_batch")
def enrich_target_companies_batch():
    """Nightly: enrich target companies that are stale or never enriched."""
    session = SyncSession()
    try:
        settings = get_settings()
        stale_cutoff = datetime.now(timezone.utc) - timedelta(days=settings.enrichment_stale_days)

        companies = session.execute(
            select(Company).where(
                Company.is_target.is_(True),
                or_(
                    Company.enriched_at.is_(None),
                    Company.enriched_at < stale_cutoff,
                ),
                Company.enrichment_status != "enriching",
            ).limit(settings.enrichment_batch_size)
        ).scalars().all()

        queued = 0
        for company in companies:
            enrich_company.delay(str(company.id))
            queued += 1

        logger.info("Queued %d target companies for enrichment", queued)
        return {"queued": queued}
    except Exception as exc:
        logger.exception("enrich_target_companies_batch failed: %s", exc)
        raise
    finally:
        session.close()


@celery_app.task(name="app.workers.tasks.enrichment_task.verify_stale_emails")
def verify_stale_emails():
    """Re-verify contact emails that are older than the verification threshold."""
    from app.models.company_contact import CompanyContact

    session = SyncSession()
    try:
        settings = get_settings()
        stale_cutoff = datetime.now(timezone.utc) - timedelta(days=settings.contact_verify_stale_days)

        contacts = session.execute(
            select(CompanyContact).where(
                CompanyContact.email != "",
                CompanyContact.email_status.in_(["unverified", "valid"]),
                or_(
                    CompanyContact.email_verified_at.is_(None),
                    CompanyContact.email_verified_at < stale_cutoff,
                ),
            ).limit(100)
        ).scalars().all()

        verified = 0
        for contact in contacts:
            try:
                from app.services.enrichment.email_verifier import verify_email_smtp
                result = verify_email_smtp(contact.email)
                contact.email_status = result.get("status", "unknown")
                contact.email_verified_at = datetime.now(timezone.utc)
                contact.last_verified_at = datetime.now(timezone.utc)
                verified += 1
            except Exception as e:
                logger.warning("Email verification failed for %s: %s", contact.email, e)

        session.commit()
        logger.info("Verified %d stale emails", verified)
        return {"verified": verified}
    except Exception as exc:
        logger.exception("verify_stale_emails failed: %s", exc)
        session.rollback()
        raise
    finally:
        session.close()


@celery_app.task(name="app.workers.tasks.enrichment_task.deduplicate_contacts")
def deduplicate_contacts():
    """
    Find and merge duplicate contacts within the same company.
    Duplicates are identified by: same company_id + same normalized name.
    The record with higher confidence_score (or more data) is kept; duplicates are deleted.
    """
    from app.models.company_contact import CompanyContact

    session = SyncSession()
    merged = 0
    try:
        # Find groups with same company + same lowercased full name
        dup_groups = session.execute(
            select(
                CompanyContact.company_id,
                func.lower(func.trim(CompanyContact.first_name)).label("fn"),
                func.lower(func.trim(CompanyContact.last_name)).label("ln"),
                func.count(CompanyContact.id).label("cnt"),
            )
            .where(CompanyContact.first_name != "", CompanyContact.last_name != "")
            .group_by(
                CompanyContact.company_id,
                func.lower(func.trim(CompanyContact.first_name)),
                func.lower(func.trim(CompanyContact.last_name)),
            )
            .having(func.count(CompanyContact.id) > 1)
        ).all()

        for row in dup_groups:
            dupes = session.execute(
                select(CompanyContact).where(
                    CompanyContact.company_id == row.company_id,
                    func.lower(func.trim(CompanyContact.first_name)) == row.fn,
                    func.lower(func.trim(CompanyContact.last_name)) == row.ln,
                ).order_by(CompanyContact.confidence_score.desc(), CompanyContact.created_at.asc())
            ).scalars().all()

            if len(dupes) < 2:
                continue

            # Keep the first (highest confidence / earliest created)
            keeper = dupes[0]
            for dup in dupes[1:]:
                # Merge data into keeper — fill any empty fields
                if not keeper.email and dup.email:
                    keeper.email = dup.email
                    keeper.email_status = dup.email_status
                if not keeper.phone and dup.phone:
                    keeper.phone = dup.phone
                if not keeper.linkedin_url and dup.linkedin_url:
                    keeper.linkedin_url = dup.linkedin_url
                if not keeper.title and dup.title:
                    keeper.title = dup.title
                if dup.is_decision_maker:
                    keeper.is_decision_maker = True
                if dup.confidence_score > keeper.confidence_score:
                    keeper.confidence_score = dup.confidence_score
                session.delete(dup)
                merged += 1

        session.commit()
        logger.info("Deduplication removed %d duplicate contacts", merged)
        return {"merged": merged}
    except Exception as exc:
        logger.exception("deduplicate_contacts failed: %s", exc)
        session.rollback()
        raise
    finally:
        session.close()
