"""Mine our own job database for company intelligence.

Uses sync SQLAlchemy Session (for Celery tasks).
"""

import logging
import re
from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.job import Job
from app.services.enrichment.base import EnrichmentResult

logger = logging.getLogger(__name__)

# Common tech keywords to detect in job description text
_TECH_KEYWORDS = [
    "kubernetes", "docker", "terraform", "ansible", "aws", "azure", "gcp",
    "python", "go", "golang", "rust", "java", "typescript", "javascript",
    "react", "node.js", "nodejs", "postgresql", "mysql", "mongodb", "redis",
    "kafka", "rabbitmq", "elasticsearch", "grafana", "prometheus", "datadog",
    "jenkins", "github actions", "gitlab ci", "circleci", "argocd", "helm",
    "linux", "nginx", "envoy", "istio", "vault", "consul", "splunk",
    "cloudflare", "fastapi", "django", "flask", "spring", "rails",
    "graphql", "grpc", "rest api", "microservices", "serverless",
    "ci/cd", "siem", "soar", "okta", "crowdstrike", "sentinelone",
    "snyk", "wiz", "prisma cloud", "soc 2", "iso 27001", "pci dss",
    "nist", "zero trust", "sso", "saml", "oauth", "oidc",
]

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

# Generic/system email prefixes to exclude
_GENERIC_PREFIXES = frozenset([
    "info", "support", "hello", "contact", "sales", "help",
    "admin", "team", "careers", "jobs", "hr", "press", "apply",
    "media", "legal", "billing", "noreply", "no-reply", "privacy",
    "office", "general", "enquiries", "feedback", "security",
    "abuse", "postmaster", "webmaster", "api", "dev", "ops",
    "marketing", "partnerships", "investors", "compliance",
    "recruiting", "talent", "engineering", "it", "itsupport",
])

# Name patterns in job descriptions: "Contact John Smith" or "Recruiter: Jane Doe"
_CONTACT_PATTERN = re.compile(
    r"(?:contact|recruiter|hiring manager|talent partner|reach out to|"
    r"questions\?.*?email|apply.*?to|send.*?resume.*?to)\s*:?\s*"
    r"([A-Z][a-z]+\s+[A-Z][a-z]+)",
    re.IGNORECASE,
)


def _strip_html(html: str) -> str:
    """Strip HTML tags to get plain text."""
    if not html:
        return ""
    return _HTML_TAG_RE.sub(" ", html)


def _extract_tech_stack_from_text(text: str) -> list[str]:
    """Extract technology keywords from job description text."""
    if not text:
        return []
    text_lower = text.lower()
    found = []
    for kw in _TECH_KEYWORDS:
        if kw in text_lower:
            found.append(kw)
    return found


def _extract_description_from_raw_json(raw_json: dict | None) -> str:
    """Extract job description text from raw_json, handling various ATS formats."""
    if not raw_json or not isinstance(raw_json, dict):
        return ""
    # Greenhouse: raw_json['content'] is HTML
    if raw_json.get("content"):
        return _strip_html(str(raw_json["content"]))
    # Lever: raw_json['descriptionPlain'] or raw_json['description']
    if raw_json.get("descriptionPlain"):
        return str(raw_json["descriptionPlain"])
    if raw_json.get("description"):
        return _strip_html(str(raw_json["description"]))
    # Ashby: raw_json['descriptionHtml'] or raw_json['descriptionPlain']
    if raw_json.get("descriptionHtml"):
        return _strip_html(str(raw_json["descriptionHtml"]))
    # Workable: raw_json['description']
    # SmartRecruiters: raw_json['jobAd']['sections']['jobDescription']['text']
    job_ad = raw_json.get("jobAd") or {}
    sections = job_ad.get("sections") or {}
    job_desc = sections.get("jobDescription") or {}
    if job_desc.get("text"):
        return str(job_desc["text"])
    return ""


def _extract_offices_from_raw_json(raw_json: dict | None) -> list[dict]:
    """Extract office locations from raw_json (Greenhouse has 'offices' key)."""
    if not raw_json or not isinstance(raw_json, dict):
        return []
    offices = raw_json.get("offices")
    if not offices or not isinstance(offices, list):
        return []
    results = []
    for office in offices:
        if isinstance(office, dict):
            name = office.get("name", "")
            location = office.get("location", "")
            if name or location:
                # Parse "City, State, Country" format
                loc_str = location or name
                parts = [p.strip() for p in loc_str.split(",")]
                results.append({
                    "label": name,
                    "city": parts[0] if parts else "",
                    "country": parts[-1] if len(parts) >= 2 else "",
                    "source": "ats_data",
                })
    return results


def _classify_hiring_velocity(count_30d: int) -> str:
    """Classify hiring velocity based on job count in last 30 days."""
    if count_30d >= 10:
        return "high"
    elif count_30d >= 3:
        return "medium"
    else:
        return "low"


def _parse_location_hint(location_raw: str) -> dict:
    """Attempt to parse a raw location string into city/country hints."""
    if not location_raw:
        return {}
    parts = [p.strip() for p in location_raw.split(",")]
    result = {}
    if len(parts) >= 2:
        result["city"] = parts[0]
        result["country"] = parts[-1]
    elif len(parts) == 1:
        result["city"] = parts[0]
    return result


def _detect_departments(titles: list[str]) -> list[str]:
    """Group job titles by pattern to detect active departments."""
    department_keywords = {
        "engineering": ["engineer", "developer", "sre", "devops", "platform", "backend", "frontend", "fullstack", "full-stack"],
        "security": ["security", "devsecops", "soc", "compliance", "grc", "pentest", "ciso"],
        "infrastructure": ["infrastructure", "cloud", "network", "systems"],
        "data": ["data", "analytics", "machine learning", "ml ", "ai "],
        "product": ["product manager", "product owner", "product design"],
        "design": ["designer", "ux", "ui"],
        "sales": ["sales", "account executive", "business development", "bdr", "sdr"],
        "marketing": ["marketing", "content", "growth"],
        "hr": ["recruiter", "talent", "people", "human resources", "hr "],
        "support": ["support", "customer success", "customer experience"],
    }
    found_departments = set()
    for title in titles:
        title_lower = title.lower()
        for dept, keywords in department_keywords.items():
            if any(kw in title_lower for kw in keywords):
                found_departments.add(dept)
                break
    return sorted(found_departments)


def _extract_contacts_from_descriptions(raw_jsons: list[dict], domain: str) -> list[dict]:
    """Extract recruiter/contact emails and names from job descriptions."""
    contacts = []
    seen_emails = set()
    seen_names = set()

    for raw_json in raw_jsons:
        desc_text = _extract_description_from_raw_json(raw_json)
        if not desc_text:
            continue

        # Extract person emails from job descriptions
        emails = _EMAIL_RE.findall(desc_text)
        for email in emails:
            local = email.split("@")[0].lower()
            email_lower = email.lower()

            if email_lower in seen_emails:
                continue
            if local in _GENERIC_PREFIXES:
                continue
            # Must be from the company domain (or a known recruiting domain)
            email_domain = email.split("@")[1].lower()
            if domain and email_domain != domain.lower():
                # Skip emails from other domains (unless it's the recruiter's personal domain)
                continue

            seen_emails.add(email_lower)

            # Try to extract name from the email (first.last@ pattern)
            first_name = ""
            last_name = ""
            parts = re.split(r"[._-]", local)
            if len(parts) >= 2 and all(p.isalpha() and len(p) >= 2 for p in parts[:2]):
                first_name = parts[0].capitalize()
                last_name = parts[1].capitalize()

            contacts.append({
                "first_name": first_name,
                "last_name": last_name,
                "title": "Recruiter / Hiring Contact",
                "role_category": "hiring",
                "seniority": "other",
                "is_decision_maker": False,
                "email": email,
                "linkedin_url": "",
                "source": "job_description",
                "confidence_score": 0.6,
            })

        # Extract named contacts from patterns like "Contact John Smith"
        for match in _CONTACT_PATTERN.finditer(desc_text):
            name = match.group(1).strip()
            if name.lower() in seen_names or len(name) > 40:
                continue
            seen_names.add(name.lower())
            name_parts = name.split(None, 1)
            first_name = name_parts[0] if name_parts else ""
            last_name = name_parts[1] if len(name_parts) > 1 else ""
            if first_name and last_name:
                contacts.append({
                    "first_name": first_name,
                    "last_name": last_name,
                    "title": "Recruiter / Hiring Contact",
                    "role_category": "hiring",
                    "seniority": "other",
                    "is_decision_maker": False,
                    "email": "",
                    "linkedin_url": "",
                    "source": "job_description",
                    "confidence_score": 0.5,
                })

    return contacts[:10]


def enrich_from_internal_data(session: Session, company_id, domain: str = "") -> EnrichmentResult:
    """Query our own database for company intelligence.

    Extracts tech stack from Job.raw_json (the full API response from ATS platforms),
    office data from raw_json, hiring metrics from job counts, departments from titles,
    and recruiter/contact emails from job descriptions.
    """
    result = EnrichmentResult(provider="internal")

    try:
        now = datetime.now(timezone.utc)
        thirty_days_ago = now - timedelta(days=30)

        # Count jobs in last 30 days
        stmt = select(func.count()).select_from(Job).where(
            Job.company_id == company_id,
            Job.first_seen_at >= thirty_days_ago,
        )
        count_30d = session.execute(stmt).scalar() or 0

        # Count non-expired jobs
        stmt = select(func.count()).select_from(Job).where(
            Job.company_id == company_id,
            Job.status.notin_(["expired", "archived"]),
        )
        total_open_roles = session.execute(stmt).scalar() or 0

        # Aggregate tech stack from raw_json content (not JobDescription which is often empty)
        stmt = select(Job.raw_json).where(
            Job.company_id == company_id,
            Job.status.notin_(["expired", "archived"]),
            Job.raw_json.isnot(None),
        )
        rows = session.execute(stmt).all()
        tech_counter: Counter = Counter()
        raw_offices: list[dict] = []
        seen_office_labels = set()

        for (raw_json,) in rows:
            # Extract tech from description text in raw_json
            desc_text = _extract_description_from_raw_json(raw_json)
            for tech in _extract_tech_stack_from_text(desc_text):
                tech_counter[tech] += 1

            # Extract office data from raw_json
            for office in _extract_offices_from_raw_json(raw_json):
                label = office.get("label", "").lower()
                if label and label not in seen_office_labels:
                    seen_office_labels.add(label)
                    raw_offices.append(office)

        # Deduplicated tech stack, sorted by frequency
        tech_stack = [tech for tech, _ in tech_counter.most_common()]

        # Extract recruiter/contact emails from job descriptions
        raw_json_list = [rj for (rj,) in rows if rj and isinstance(rj, dict)]
        job_contacts = _extract_contacts_from_descriptions(raw_json_list, domain)
        if job_contacts:
            result.contacts = job_contacts

        # Extract unique locations for additional office hints
        stmt = select(Job.location_raw).where(
            Job.company_id == company_id,
            Job.location_raw != "",
            Job.location_raw.isnot(None),
            Job.status.notin_(["expired", "archived"]),
        ).distinct()
        location_rows = session.execute(stmt).all()
        location_office_hints = []
        seen_cities = set()
        for (loc_raw,) in location_rows:
            hint = _parse_location_hint(loc_raw)
            city = hint.get("city", "").lower()
            if city and city not in seen_cities and city not in seen_office_labels:
                seen_cities.add(city)
                location_office_hints.append(hint)

        # Merge office sources: raw_json offices first, then location hints
        all_offices = raw_offices + [
            {"label": h.get("city", ""), "city": h.get("city", ""), "country": h.get("country", ""), "source": "job_listings"}
            for h in location_office_hints
        ]

        # Detect departments from job titles
        stmt = select(Job.title).where(
            Job.company_id == company_id,
            Job.status.notin_(["expired", "archived"]),
        )
        title_rows = session.execute(stmt).all()
        titles = [t for (t,) in title_rows]
        departments = _detect_departments(titles)

        # Build result
        result.company_data = {
            "actively_hiring": count_30d > 0,
            "hiring_velocity": _classify_hiring_velocity(count_30d),
            "total_open_roles": total_open_roles,
            "jobs_last_30d": count_30d,
            "tech_stack": tech_stack,
            "departments": departments,
        }
        result.offices = all_offices
        result.success = True

        logger.info(
            "Internal enrichment for company %s: %d open roles, %d tech items, %d offices",
            company_id, total_open_roles, len(tech_stack), len(all_offices),
        )

    except Exception as exc:
        logger.warning("Internal enrichment failed for company %s: %s", company_id, exc, exc_info=True)
        result.error = str(exc)

    return result
