"""Backup enrichment: search for company leadership and data.

Uses DuckDuckGo API for instant answers and Clearbit's free logo API.
Falls back to scraping Google search results if DuckDuckGo fails.
"""

import logging
import re
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup

from app.services.enrichment.base import EnrichmentResult

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}
_TIMEOUT = 15


def _classify_role_category(title: str) -> str:
    t = title.lower()
    if any(kw in t for kw in ["ceo", "coo", "cfo", "cto", "ciso", "cpo", "cmo", "chief",
                               "founder", "co-founder", "cofounder", "president"]):
        return "c_suite"
    if any(kw in t for kw in ["vp engineering", "engineering director", "head of engineering",
                               "director of engineering", "vp of engineering",
                               "vp technology", "director of technology"]):
        return "engineering_lead"
    if any(kw in t for kw in ["recruiter", "talent", "hiring", "people", "hr"]):
        return "hiring"
    return "executive"


def _classify_seniority(title: str) -> str:
    t = title.lower()
    if any(kw in t for kw in ["ceo", "cto", "cfo", "coo", "ciso", "cpo", "cmo", "chief",
                               "founder", "co-founder", "cofounder"]):
        return "c_suite"
    if any(kw in t for kw in ["vp ", "vp,", "vice president", "president"]):
        return "vp"
    if "director" in t:
        return "director"
    if any(kw in t for kw in ["manager", "lead", "head of", "head,"]):
        return "manager"
    return "other"


_NAME_RE = re.compile(r"^[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}$")

_TITLE_PATTERN = re.compile(
    r"(?:CEO|CTO|CFO|COO|CISO|CPO|CMO|Chief\s+\w+\s+Officer|"
    r"Vice\s+President|VP\s+(?:of\s+)?\w+|Head\s+of\s+\w+|Director\s+of\s+\w+|"
    r"Co-?[Ff]ounder|Founder|President|Managing\s+Director|"
    r"General\s+Manager|Partner)",
    re.IGNORECASE,
)


def _extract_people_from_text(text: str, company_name: str) -> list[dict]:
    """Extract people with titles from text content."""
    people = []
    seen_names = set()

    # Pattern: "Name - Title" or "Name, Title" with company context
    patterns = [
        # LinkedIn-style: "Name - Title at Company"
        r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\s*[-–—]\s*(.+?)\s*(?:at|[-–—])\s*" + re.escape(company_name),
        # "Name, Title"
        r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}),\s*((?:CEO|CTO|CFO|COO|CISO|CPO|CMO|Chief|VP|Vice President|Head|Director|Founder|Co-Founder|President).+?)(?:\s*[-–—|,]|$)",
        # "Name is the Title of Company"
        r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\s+(?:is|as)\s+(?:the\s+)?(.+?)\s+(?:of|at)\s+" + re.escape(company_name),
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            name = match.group(1).strip()
            title = match.group(2).strip()[:200]

            if not _NAME_RE.match(name) or not _TITLE_PATTERN.search(title):
                continue
            if name.lower() in seen_names:
                continue
            seen_names.add(name.lower())

            name_parts = name.split(None, 1)
            first_name = name_parts[0] if name_parts else ""
            last_name = name_parts[1] if len(name_parts) > 1 else ""

            role_category = _classify_role_category(title)
            seniority = _classify_seniority(title)

            people.append({
                "first_name": first_name,
                "last_name": last_name,
                "title": title,
                "role_category": role_category,
                "seniority": seniority,
                "is_decision_maker": seniority in ("c_suite", "vp", "director"),
                "linkedin_url": "",
                "source": "search",
                "confidence_score": 0.5,
            })

    return people[:15]


def get_clearbit_logo(domain: str) -> str:
    """Get company logo URL from Clearbit's free logo API."""
    if not domain:
        return ""
    return f"https://logo.clearbit.com/{domain}"


def search_company_leadership(company_name: str, domain: str = "") -> EnrichmentResult:
    """Search for company leadership/key people.

    Tries multiple approaches:
    1. DuckDuckGo Instant Answer API
    2. Scraping DuckDuckGo search results
    3. Wikipedia lookup for the company

    This is a backup method when website scraping finds no contacts.
    """
    result = EnrichmentResult(provider="search")

    if not company_name:
        result.error = "No company name"
        return result

    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True, headers=_HEADERS) as client:
            all_people = []

            # Method 1: DuckDuckGo search via lite endpoint
            try:
                query = f'"{company_name}" CEO OR CTO OR founder OR "VP Engineering" site:linkedin.com'
                resp = client.post(
                    "https://lite.duckduckgo.com/lite/",
                    data={"q": query},
                )
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    full_text = soup.get_text(separator=" ", strip=True)
                    people = _extract_people_from_text(full_text, company_name)
                    all_people.extend(people)
                    if people:
                        logger.info("DuckDuckGo found %d people for %s", len(people), company_name)
            except Exception as exc:
                logger.debug("DuckDuckGo search failed for %s: %s", company_name, exc)

            # Method 2: Google search (if DuckDuckGo found nothing)
            if not all_people:
                try:
                    query = f'"{company_name}" CEO CTO founder "VP Engineering"'
                    resp = client.get(
                        f"https://www.google.com/search?q={quote_plus(query)}&num=10",
                    )
                    if resp.status_code == 200:
                        soup = BeautifulSoup(resp.text, "html.parser")
                        full_text = soup.get_text(separator=" ", strip=True)
                        people = _extract_people_from_text(full_text, company_name)
                        all_people.extend(people)
                        if people:
                            logger.info("Google found %d people for %s", len(people), company_name)
                except Exception as exc:
                    logger.debug("Google search failed for %s: %s", company_name, exc)

            # Deduplicate by name
            seen = set()
            unique_people = []
            for p in all_people:
                key = (p["first_name"].lower(), p["last_name"].lower())
                if key not in seen:
                    seen.add(key)
                    unique_people.append(p)

            result.contacts = unique_people
            summary_contacts = len(unique_people)

            # Get Clearbit logo if we have a domain
            if domain:
                logo_url = get_clearbit_logo(domain)
                try:
                    logo_resp = client.head(logo_url)
                    if logo_resp.status_code == 200:
                        result.company_data["logo_url"] = logo_url
                except Exception:
                    pass

            result.success = True
            logger.info("Search enrichment for %s: %d contacts, logo=%s",
                        company_name, summary_contacts,
                        "yes" if result.company_data.get("logo_url") else "no")

    except Exception as exc:
        logger.warning("Search enrichment failed for %s: %s", company_name, exc)
        result.error = str(exc)

    return result
