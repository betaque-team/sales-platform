"""Orchestrate full enrichment pipeline for a company.

Coordinates website discovery, domain extraction, internal data mining,
website scraping, email pattern detection, SMTP verification, and
contact relevance scoring.

All operations are synchronous (designed for Celery worker context).
"""

import logging
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.company import Company, CompanyATSBoard
from app.models.company_contact import CompanyContact
from app.models.company_office import CompanyOffice
from app.services.enrichment.domain_extractor import extract_domain
from app.services.enrichment.internal_provider import enrich_from_internal_data
from app.services.enrichment.website_scraper import scrape_company_website
from app.services.enrichment.search_provider import search_company_leadership, get_clearbit_logo
from app.services.enrichment.email_pattern import detect_email_pattern
from app.services.enrichment.email_verifier import verify_email_smtp
from app.services.enrichment.contact_relevance import compute_contact_relevance
from app.services.enrichment.crunchbase_provider import scrape_crunchbase_funding
from app.services.enrichment.linkedin_people_finder import find_linkedin_people

logger = logging.getLogger(__name__)

# ATS board URL patterns (same as schema)
_ATS_BOARD_URLS = {
    "greenhouse": "https://boards.greenhouse.io/{slug}",
    "lever": "https://jobs.lever.co/{slug}",
    "ashby": "https://jobs.ashbyhq.com/{slug}",
    "workable": "https://apply.workable.com/{slug}",
    "bamboohr": "https://{slug}.bamboohr.com/careers",
    "himalayas": "https://himalayas.app/companies/{slug}/jobs",
    "wellfound": "https://wellfound.com/company/{slug}/jobs",
    "jobvite": "https://jobs.jobvite.com/{slug}",
    "smartrecruiters": "https://jobs.smartrecruiters.com/{slug}",
    "recruitee": "https://{slug}.recruitee.com",
}


def _discover_website_from_ats_boards(session: Session, company: Company) -> str:
    """Discover a company's website from ATS board data.

    Strategy (ordered by speed and accuracy):
    1. Try {slug}.com with a HEAD request (fastest, most accurate)
    2. Scrape the ATS board page for links to the company website
    """
    boards = session.execute(
        select(CompanyATSBoard).where(
            CompanyATSBoard.company_id == company.id,
            CompanyATSBoard.is_active.is_(True),
        )
    ).scalars().all()

    if not boards:
        return ""

    headers = {"User-Agent": "Mozilla/5.0 (compatible; JobPlatformBot/1.0)"}

    # --- Strategy 1: Try {slug}.com (fast heuristic) ---
    for board in boards:
        slug = board.slug
        if slug and slug != "__all__" and "." not in slug:
            candidate = f"https://{slug}.com"
            try:
                with httpx.Client(timeout=10, follow_redirects=True, headers=headers) as client:
                    # Try HEAD first, fall back to GET if HEAD is blocked
                    resp = client.head(candidate)
                    if resp.status_code in (403, 405):
                        resp = client.get(candidate)
                    if resp.status_code < 400:
                        final_host = str(resp.url.host) if resp.url else ""
                        if final_host and "parking" not in final_host and "sedoparking" not in final_host:
                            logger.info("Discovered website via slug heuristic: %s", candidate)
                            return candidate
            except Exception:
                pass
            break

    # --- Strategy 2: Scrape ATS board page for website links ---
    for board in boards:
        if board.slug == "__all__":
            continue

        pattern = _ATS_BOARD_URLS.get(board.platform, "")
        if not pattern:
            continue
        board_url = pattern.format(slug=board.slug)

        try:
            with httpx.Client(timeout=15, follow_redirects=True, headers=headers) as client:
                resp = client.get(board_url)
                if resp.status_code != 200:
                    continue

                soup = BeautifulSoup(resp.text, "html.parser")

                # Look for "Visit website", "Company website", or similar links
                for a_tag in soup.find_all("a", href=True):
                    href = str(a_tag["href"]).strip()
                    text = a_tag.get_text(strip=True).lower()

                    # Skip ATS-internal links
                    if any(ats in href.lower() for ats in [
                        "greenhouse.io", "lever.co", "ashbyhq.com",
                        "workable.com", "bamboohr.com", "jobvite.com",
                        "smartrecruiters.com", "recruitee.com",
                        "wellfound.com", "himalayas.app",
                        "linkedin.com", "twitter.com", "facebook.com",
                        "instagram.com", "youtube.com", "github.com",
                        "javascript:", "mailto:", "#",
                    ]):
                        continue

                    # Must be an absolute URL
                    if not href.startswith("http"):
                        continue

                    # Heuristics: link text suggests a website link, or it's a prominent link
                    if any(kw in text for kw in ["website", "visit", "home", "about us", "learn more"]):
                        logger.info("Discovered website from ATS board link text: %s", href)
                        return href.split("?")[0].rstrip("/")

                # Fallback: look for links in header/nav area that go to external sites
                _skip_domains = [
                    "greenhouse.io", "lever.co", "ashbyhq.com",
                    "workable.com", "bamboohr.com", "jobvite.com",
                    "smartrecruiters.com", "recruitee.com",
                    "careers.", "jobs.",  # Skip career subdomains
                ]
                for nav in soup.find_all(["header", "nav"]):
                    for a_tag in nav.find_all("a", href=True):
                        href = str(a_tag["href"]).strip()
                        if href.startswith("http") and not any(skip in href.lower() for skip in _skip_domains):
                            logger.info("Discovered website from ATS board nav: %s", href)
                            return href.split("?")[0].rstrip("/")

        except Exception as exc:
            logger.debug("Failed to scrape ATS board %s for website discovery: %s", board_url, exc)
            continue

    return ""


def _update_field(company: Company, field: str, value, overwrite_empty_only: bool = True):
    """Update a company field, optionally only if current value is empty/None."""
    if value is None or value == "" or value == []:
        return
    current = getattr(company, field, None)
    if overwrite_empty_only and current and current != "" and current != []:
        return
    setattr(company, field, value)


def _find_existing_contact(session: Session, company_id, first_name: str, last_name: str, email: str) -> CompanyContact | None:
    """Find an existing contact by name match or email match."""
    if email:
        result = session.execute(
            select(CompanyContact).where(
                CompanyContact.company_id == company_id,
                CompanyContact.email == email,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing

    if first_name and last_name:
        result = session.execute(
            select(CompanyContact).where(
                CompanyContact.company_id == company_id,
                CompanyContact.first_name == first_name,
                CompanyContact.last_name == last_name,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing

    return None


def _upsert_contact(session: Session, company_id, contact_data: dict) -> tuple[CompanyContact, bool]:
    """Create or update a contact record. Returns (contact, is_new)."""
    first_name = contact_data.get("first_name", "").strip()
    last_name = contact_data.get("last_name", "").strip()
    email = contact_data.get("email", "").strip()

    existing = _find_existing_contact(session, company_id, first_name, last_name, email)

    if existing:
        for field in ("title", "role_category", "seniority", "linkedin_url", "phone", "source"):
            new_val = contact_data.get(field, "")
            if new_val:
                current_val = getattr(existing, field, "")
                if not current_val:
                    setattr(existing, field, new_val)
        if contact_data.get("is_decision_maker"):
            existing.is_decision_maker = True
        if email and not existing.email:
            existing.email = email
        return existing, False

    contact = CompanyContact(
        company_id=company_id,
        first_name=first_name,
        last_name=last_name,
        title=contact_data.get("title", ""),
        role_category=contact_data.get("role_category", "other"),
        seniority=contact_data.get("seniority", "other"),
        email=email,
        phone=contact_data.get("phone", ""),
        linkedin_url=contact_data.get("linkedin_url", ""),
        source=contact_data.get("source", "website_scrape"),
        is_decision_maker=contact_data.get("is_decision_maker", False),
        confidence_score=0.7,
    )
    session.add(contact)
    session.flush()
    return contact, True


def _find_existing_office(session: Session, company_id, label: str, city: str) -> bool:
    """Check if an office with similar label/city already exists."""
    if label:
        existing = session.execute(
            select(CompanyOffice).where(
                CompanyOffice.company_id == company_id,
                CompanyOffice.label == label,
            )
        ).scalar_one_or_none()
        if existing:
            return True
    if city:
        existing = session.execute(
            select(CompanyOffice).where(
                CompanyOffice.company_id == company_id,
                CompanyOffice.city == city,
            )
        ).scalar_one_or_none()
        if existing:
            return True
    return False


def run_enrichment(session: Session, company: Company) -> dict:
    """Run full enrichment pipeline for a company.

    Steps:
        0. Discover website from ATS boards if not set
        1. Extract domain from website
        2. Run internal data provider (our job database)
        3. Run website scraper
        4. Upsert contacts and run email detection/verification
        5. Compute contact relevance to active jobs
    """
    summary = {
        "contacts_found": 0,
        "contacts_new": 0,
        "emails_verified": 0,
        "offices_found": 0,
        "errors": [],
    }

    logger.info("Starting enrichment for company %s (%s)", company.name, company.id)

    # ---------------------------------------------------------------
    # Step 0: Discover website from ATS boards if not set
    # ---------------------------------------------------------------
    if not company.website:
        try:
            discovered_website = _discover_website_from_ats_boards(session, company)
            if discovered_website:
                company.website = discovered_website
                logger.info("Discovered website: %s", discovered_website)
        except Exception as exc:
            logger.warning("Website discovery failed: %s", exc)
            summary["errors"].append(f"website_discovery: {exc}")

    # ---------------------------------------------------------------
    # Step 1: Extract domain
    # ---------------------------------------------------------------
    domain = ""
    try:
        if company.website:
            domain = extract_domain(company.website)
            if domain:
                company.domain = domain
                logger.info("Extracted domain: %s", domain)
        else:
            domain = company.domain or ""
    except Exception as exc:
        logger.warning("Domain extraction failed: %s", exc)
        domain = company.domain or ""
        summary["errors"].append(f"domain_extraction: {exc}")

    # Collect all contacts from all providers before upserting
    scraped_contacts = []

    # ---------------------------------------------------------------
    # Step 2: Internal data provider
    # ---------------------------------------------------------------
    try:
        internal_result = enrich_from_internal_data(session, company.id, domain=domain)
        if internal_result.success:
            data = internal_result.company_data
            if data.get("tech_stack"):
                company.tech_stack = data["tech_stack"]
            # Store internal insights in metadata
            meta = dict(company.metadata_json or {})
            meta["hiring_velocity"] = data.get("hiring_velocity", "")
            meta["actively_hiring"] = data.get("actively_hiring", False)
            meta["total_open_roles"] = data.get("total_open_roles", 0)
            meta["departments"] = data.get("departments", [])
            company.metadata_json = meta

            # Upsert offices from internal data (ATS raw_json + location hints)
            for office_data in internal_result.offices:
                label = office_data.get("label", "")
                city = office_data.get("city", "")
                if not _find_existing_office(session, company.id, label, city):
                    office = CompanyOffice(
                        company_id=company.id,
                        label=label,
                        city=city,
                        country=office_data.get("country", ""),
                        source=office_data.get("source", "job_listings"),
                    )
                    session.add(office)
                    summary["offices_found"] += 1

            # Contacts from job descriptions (recruiter emails, etc.)
            if internal_result.contacts:
                scraped_contacts.extend(internal_result.contacts)
                logger.info("Internal provider found %d contacts from job descriptions",
                            len(internal_result.contacts))

            logger.info("Internal enrichment: %d tech items, velocity=%s, %d offices",
                        len(data.get("tech_stack", [])), data.get("hiring_velocity"),
                        len(internal_result.offices))
        elif internal_result.error:
            summary["errors"].append(f"internal: {internal_result.error}")
    except Exception as exc:
        logger.warning("Internal enrichment failed: %s", exc, exc_info=True)
        summary["errors"].append(f"internal: {exc}")

    # ---------------------------------------------------------------
    # Step 3: Website scraper
    # ---------------------------------------------------------------
    try:
        if company.website:
            scrape_result = scrape_company_website(company.website)
            if scrape_result.success:
                data = scrape_result.company_data

                _update_field(company, "description", data.get("description"))
                _update_field(company, "founded_year", data.get("founded_year"))
                _update_field(company, "linkedin_url", data.get("linkedin_url"))
                _update_field(company, "twitter_url", data.get("twitter_url"))
                _update_field(company, "employee_count", data.get("employee_count"))
                _update_field(company, "logo_url", data.get("logo_url"))
                _update_field(company, "total_funding", data.get("total_funding"))
                _update_field(company, "total_funding_usd", data.get("total_funding_usd"))
                _update_field(company, "funding_stage", data.get("funding_stage"))

                scraped_contacts = scrape_result.contacts
                summary["contacts_found"] = len(scraped_contacts)

                # Upsert offices from website scrape
                for office_data in scrape_result.offices:
                    label = office_data.get("label", "")
                    city = office_data.get("city", "")
                    if not _find_existing_office(session, company.id, label, city):
                        office = CompanyOffice(
                            company_id=company.id,
                            label=label,
                            address=office_data.get("address", ""),
                            city=city,
                            country=office_data.get("country", ""),
                            is_headquarters=office_data.get("is_headquarters", False),
                            source="website_scrape",
                        )
                        session.add(office)
                        summary["offices_found"] += 1

                logger.info("Website scrape: %d contacts, %d offices",
                            len(scraped_contacts), len(scrape_result.offices))
            elif scrape_result.error:
                logger.warning("Website scrape error: %s", scrape_result.error)
                summary["errors"].append(f"scrape: {scrape_result.error}")
        else:
            logger.info("No website available for %s, skipping website scrape", company.name)
    except Exception as exc:
        logger.warning("Website scrape failed: %s", exc, exc_info=True)
        summary["errors"].append(f"scrape: {exc}")

    # ---------------------------------------------------------------
    # Step 3B: Crunchbase — funding, size, founded year
    # ---------------------------------------------------------------
    try:
        cb_result = scrape_crunchbase_funding(company.name, domain)
        if cb_result.success and cb_result.company_data:
            data = cb_result.company_data
            _update_field(company, "total_funding", data.get("total_funding"))
            _update_field(company, "total_funding_usd", data.get("total_funding_usd"))
            _update_field(company, "founded_year", data.get("founded_year"))
            _update_field(company, "employee_count", data.get("employee_count"))
            _update_field(company, "description", data.get("description"))
            _update_field(company, "linkedin_url", data.get("linkedin_url"))
            _update_field(company, "funding_stage", data.get("funding_stage"))
            # Funding signal: always overwrite with most recent date found
            if data.get("funded_at"):
                if not company.funded_at or data["funded_at"] > company.funded_at:
                    company.funded_at = data["funded_at"]
            _update_field(company, "funding_news_url", data.get("funding_news_url"))
            logger.info("Crunchbase enrichment: %s", {k: v for k, v in data.items() if v})
        elif cb_result.error:
            summary["errors"].append(f"crunchbase: {cb_result.error}")
    except Exception as exc:
        logger.warning("Crunchbase enrichment failed for %s: %s", company.name, exc)
        summary["errors"].append(f"crunchbase: {exc}")

    # Also pull funding from website scrape if Crunchbase missed it
    # (website_scraper already extracted these into scrape_result.company_data)

    # ---------------------------------------------------------------
    # Step 3C: LinkedIn people finder (via search engine)
    # ---------------------------------------------------------------
    if len(scraped_contacts) < 5:
        try:
            li_result = find_linkedin_people(company.name, domain)
            if li_result.success and li_result.contacts:
                scraped_contacts.extend(li_result.contacts)
                summary["contacts_found"] = len(scraped_contacts)
                logger.info("LinkedIn search found %d people for %s",
                            len(li_result.contacts), company.name)
            elif li_result.error:
                summary["errors"].append(f"linkedin: {li_result.error}")
        except Exception as exc:
            logger.warning("LinkedIn people search failed for %s: %s", company.name, exc)
            summary["errors"].append(f"linkedin: {exc}")

    # ---------------------------------------------------------------
    # Step 3D: DuckDuckGo/Google backup for leadership (if still few contacts)
    # ---------------------------------------------------------------
    if len(scraped_contacts) < 3:
        try:
            search_result = search_company_leadership(company.name, domain)
            if search_result.success:
                if search_result.contacts:
                    scraped_contacts.extend(search_result.contacts)
                    summary["contacts_found"] = len(scraped_contacts)
                    logger.info("Search backup found %d people for %s",
                                len(search_result.contacts), company.name)

                # Clearbit logo fallback
                if not company.logo_url and search_result.company_data.get("logo_url"):
                    company.logo_url = search_result.company_data["logo_url"]
                    logger.info("Got Clearbit logo for %s", company.name)
            elif search_result.error:
                summary["errors"].append(f"search: {search_result.error}")
        except Exception as exc:
            logger.warning("Search backup failed for %s: %s", company.name, exc)
            summary["errors"].append(f"search: {exc}")

    # Clearbit logo as final fallback (even if search was skipped)
    if not company.logo_url and domain:
        try:
            company.logo_url = get_clearbit_logo(domain)
        except Exception:
            pass

    # ---------------------------------------------------------------
    # Step 4: Upsert contacts + email detection/verification
    # ---------------------------------------------------------------
    try:
        for contact_data in scraped_contacts:
            # Skip contacts with no name (noise from scraping)
            if not contact_data.get("first_name", "").strip():
                continue
            contact, is_new = _upsert_contact(session, company.id, contact_data)
            if is_new:
                summary["contacts_new"] += 1

            # Email pattern detection: if contact has no email but we have domain and name
            if not contact.email and domain and contact.first_name and contact.last_name:
                try:
                    pattern_result = detect_email_pattern(
                        contact.first_name, contact.last_name, domain
                    )
                    if pattern_result.get("email"):
                        contact.email = pattern_result["email"]
                        contact.email_status = pattern_result.get("status", "unverified")
                        contact.source = contact.source or "email_pattern"
                        if pattern_result["status"] == "valid":
                            contact.confidence_score = min(contact.confidence_score + 0.2, 1.0)
                            contact.email_verified_at = datetime.now(timezone.utc)
                            summary["emails_verified"] += 1
                        logger.debug("Email pattern found for %s %s: %s (%s)",
                                     contact.first_name, contact.last_name,
                                     pattern_result["email"], pattern_result["status"])
                except Exception as exc:
                    logger.debug("Email pattern detection failed for %s %s: %s",
                                 contact.first_name, contact.last_name, exc)

            # SMTP verification: if contact has email but it's unverified
            elif contact.email and contact.email_status in ("unverified", ""):
                try:
                    verify_result = verify_email_smtp(contact.email)
                    contact.email_status = verify_result.get("status", "unknown")
                    if verify_result["status"] == "valid":
                        contact.confidence_score = min(contact.confidence_score + 0.2, 1.0)
                        contact.email_verified_at = datetime.now(timezone.utc)
                        summary["emails_verified"] += 1
                    logger.debug("SMTP verification for %s: %s", contact.email, verify_result["status"])
                except Exception as exc:
                    logger.debug("SMTP verification failed for %s: %s", contact.email, exc)

        session.flush()
    except Exception as exc:
        logger.warning("Contact upsert/verification failed: %s", exc, exc_info=True)
        summary["errors"].append(f"contacts: {exc}")

    # ---------------------------------------------------------------
    # Step 4B: Role-based email discovery (if few contacts and we have domain)
    # ---------------------------------------------------------------
    if domain and summary["contacts_new"] < 3:
        try:
            _role_emails = [
                ("", "", "ceo", "CEO", "c_suite", "c_suite"),
                ("", "", "cto", "CTO", "c_suite", "c_suite"),
                ("", "", "hr", "HR Contact", "hiring", "other"),
                ("", "", "careers", "Careers Contact", "hiring", "other"),
                ("", "", "recruiting", "Recruiting Contact", "hiring", "other"),
            ]
            for fn, ln, local, title, role_cat, sen in _role_emails:
                email = f"{local}@{domain}"
                # Check if already exists
                existing = _find_existing_contact(session, company.id, fn, ln, email)
                if existing:
                    continue
                try:
                    verify_result = verify_email_smtp(email)
                    if verify_result.get("status") == "valid":
                        contact = CompanyContact(
                            company_id=company.id,
                            first_name="",
                            last_name="",
                            title=title,
                            role_category=role_cat,
                            seniority=sen,
                            email=email,
                            email_status="valid",
                            email_verified_at=datetime.now(timezone.utc),
                            source="role_email",
                            is_decision_maker=role_cat == "c_suite",
                            confidence_score=0.4,
                        )
                        session.add(contact)
                        summary["contacts_new"] += 1
                        summary["emails_verified"] += 1
                        logger.info("Found valid role email: %s for %s", email, company.name)
                except Exception:
                    pass
            session.flush()
        except Exception as exc:
            logger.debug("Role email discovery failed for %s: %s", company.name, exc)

    # ---------------------------------------------------------------
    # Step 5: Contact relevance computation
    # ---------------------------------------------------------------
    try:
        relevance_count = compute_contact_relevance(session, company.id)
        summary["relevance_records"] = relevance_count
    except Exception as exc:
        logger.warning("Contact relevance computation failed: %s", exc, exc_info=True)
        summary["errors"].append(f"relevance: {exc}")

    # ---------------------------------------------------------------
    # Finalize
    # ---------------------------------------------------------------
    try:
        company.enrichment_status = "enriched"
        company.enriched_at = datetime.now(timezone.utc)
        if summary["errors"]:
            company.enrichment_error = "; ".join(str(e) for e in summary["errors"])
        else:
            company.enrichment_error = ""
        session.commit()
    except Exception as exc:
        logger.error("Failed to commit enrichment results: %s", exc, exc_info=True)
        session.rollback()
        summary["errors"].append(f"commit: {exc}")

    logger.info(
        "Enrichment complete for %s: %d contacts found, %d new, %d emails verified, %d offices",
        company.name, summary["contacts_found"], summary["contacts_new"],
        summary["emails_verified"], summary["offices_found"],
    )

    return summary
