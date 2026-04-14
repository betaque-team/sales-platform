"""Find company employees via LinkedIn using search engine results.

Uses DuckDuckGo and Google to search site:linkedin.com/in for people at a company.
No direct LinkedIn scraping — uses public search engine indexes.

LinkedIn result snippets are typically formatted as:
  "First Last - Title at Company | LinkedIn"
  "First Last - Title | LinkedIn"
  "First Last · Senior Engineer at Company"

This approach is:
  - Free (no API keys)
  - Legal (searching public indexes of public profiles)
  - Reliable for finding key decision-makers and leadership
"""

import logging
import re
import time
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup

from app.services.enrichment.base import EnrichmentResult

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
}
_TIMEOUT = 20

# Match LinkedIn profile URLs in search results
_LI_PROFILE_URL_RE = re.compile(
    r"https?://(?:www\.)?linkedin\.com/in/([^/?&\s\"'>]+)",
    re.IGNORECASE,
)

# Parse LinkedIn-style snippet titles
# e.g. "John Doe - Chief Technology Officer at Webflow | LinkedIn"
# e.g. "Jane Smith - VP Engineering | LinkedIn"
# e.g. "Bob Chen · Co-founder & CTO at Acme Corp"
_LI_SNIPPET_FULL_RE = re.compile(
    r"^([A-Z][a-z]+(?:[\s-][A-Z][a-z]+){1,4})"  # Name (2-5 words)
    r"\s*[-–—·]\s*"                                # separator
    r"(.+?)"                                       # title
    r"\s*(?:at\s+.+?)?"                           # optional "at Company"
    r"\s*[|\-–—]\s*LinkedIn",                      # | LinkedIn suffix
    re.IGNORECASE,
)

# Simpler: "Name - Title | LinkedIn" without "at Company"
_LI_SNIPPET_SHORT_RE = re.compile(
    r"^([A-Z][a-z]+(?:[\s-][A-Z][a-z]+){1,4})"
    r"\s*[-–—·]\s*"
    r"(.+?)"
    r"\s*\|\s*LinkedIn",
    re.IGNORECASE,
)

# Title keywords that indicate a relevant/decision-making role
_DECISION_MAKER_TITLES = frozenset([
    "ceo", "cto", "cfo", "coo", "ciso", "cpo", "cmo", "cso",
    "chief", "founder", "co-founder", "cofounder",
    "president", "vice president", "vp",
    "director", "head of", "head,",
    "svp", "evp", "senior vice",
])


def _classify_role_category(title: str) -> str:
    t = title.lower()
    if any(kw in t for kw in ["ceo", "coo", "cfo", "cto", "ciso", "cpo", "cmo", "chief",
                               "founder", "co-founder", "cofounder", "president"]):
        return "c_suite"
    if any(kw in t for kw in ["vp engineering", "engineering director", "head of engineering",
                               "director of engineering", "vp of engineering",
                               "vp technology", "director of technology", "cto"]):
        return "engineering_lead"
    if any(kw in t for kw in ["recruiter", "talent", "hiring", "people ops", "hr "]):
        return "hiring"
    if any(kw in t for kw in ["vp", "vice president", "director", "head of"]):
        return "executive"
    return "other"


def _classify_seniority(title: str) -> str:
    t = title.lower()
    if any(kw in t for kw in ["ceo", "cto", "cfo", "coo", "ciso", "cpo", "cmo", "chief",
                               "founder", "co-founder", "cofounder"]):
        return "c_suite"
    if any(kw in t for kw in ["vp ", "vp,", "vice president"]):
        return "vp"
    if "director" in t:
        return "director"
    if any(kw in t for kw in ["manager", "lead", "head of"]):
        return "manager"
    return "other"


def _is_decision_maker(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in _DECISION_MAKER_TITLES)


def _parse_name(full_name: str) -> tuple[str, str]:
    """Split full name into (first_name, last_name)."""
    parts = full_name.strip().split(None, 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return parts[0], ""


def _parse_snippet(snippet: str, company_name: str) -> dict | None:
    """Extract name and title from a search result snippet."""
    snippet = snippet.strip()

    # Try full pattern first (with "at Company")
    for pattern in [_LI_SNIPPET_FULL_RE, _LI_SNIPPET_SHORT_RE]:
        m = pattern.match(snippet)
        if m:
            name = m.group(1).strip()
            title = m.group(2).strip()
            # Remove trailing "at Company" from title
            title = re.sub(r"\s+at\s+.+$", "", title, flags=re.IGNORECASE).strip()
            # Trim long titles
            title = title[:200]
            if name and title:
                return {"name": name, "title": title}

    # Fallback: look for "Name - Title" pattern with known title keywords
    m = re.match(
        r"^([A-Z][a-z]+(?:[\s-][A-Z][a-z]+){1,4})\s*[-–—·]\s*(.{5,150})",
        snippet,
        re.IGNORECASE,
    )
    if m:
        name = m.group(1).strip()
        title = m.group(2).strip()
        # Must contain a recognizable title keyword
        title_lower = title.lower()
        if any(kw in title_lower for kw in [
            "ceo", "cto", "cfo", "coo", "ciso", "chief", "founder",
            "president", "director", "head of", "vp ", "vice president",
            "manager", "engineer", "recruiter", "talent", "lead",
        ]):
            title = re.sub(r"\s*[|\-–—]\s*linkedin.*$", "", title, flags=re.IGNORECASE).strip()
            title = re.sub(r"\s+at\s+.+$", "", title, flags=re.IGNORECASE).strip()
            return {"name": name, "title": title[:200]}

    return None


def _extract_people_from_search_results(
    soup: BeautifulSoup, company_name: str, max_results: int = 20
) -> list[dict]:
    """Extract people from DuckDuckGo/Google search result HTML."""
    people: list[dict] = []
    seen_names: set[str] = set()
    seen_urls: set[str] = set()

    # Find all result blocks — DuckDuckGo and Google use different structures
    result_containers = (
        soup.find_all("tr", class_="result-sponsored")  # DuckDuckGo
        or soup.find_all("div", class_=re.compile(r"result|snippet", re.I))  # Generic
        or [soup]  # Fallback: entire page
    )

    # Extract all text blocks that look like LinkedIn snippets
    full_text = soup.get_text(separator="\n", strip=True)
    lines = [l.strip() for l in full_text.split("\n") if l.strip()]

    # Also extract LinkedIn URLs from the page
    url_to_snippet: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        href = str(a["href"])
        m = _LI_PROFILE_URL_RE.search(href)
        if m:
            clean_url = f"https://www.linkedin.com/in/{m.group(1)}"
            if clean_url not in seen_urls:
                seen_urls.add(clean_url)
                # Try to find associated text near this link
                context = a.get_text(strip=True)
                if not context:
                    parent = a.parent
                    if parent:
                        context = parent.get_text(strip=True)
                url_to_snippet[clean_url] = context or ""

    # Parse lines for LinkedIn-style snippets
    for line in lines:
        if "linkedin" not in line.lower() and company_name.lower()[:8] not in line.lower():
            continue
        parsed = _parse_snippet(line, company_name)
        if not parsed:
            continue

        name_key = parsed["name"].lower()
        if name_key in seen_names:
            continue
        seen_names.add(name_key)

        first, last = _parse_name(parsed["name"])
        if not first or not last:
            continue

        title = parsed["title"]
        role_category = _classify_role_category(title)
        seniority = _classify_seniority(title)

        # Try to match with a LinkedIn URL we extracted
        linkedin_url = ""
        for url, snippet_text in url_to_snippet.items():
            if first.lower() in snippet_text.lower() or last.lower() in snippet_text.lower():
                linkedin_url = url
                break

        people.append({
            "first_name": first,
            "last_name": last,
            "title": title,
            "role_category": role_category,
            "seniority": seniority,
            "is_decision_maker": _is_decision_maker(title),
            "linkedin_url": linkedin_url,
            "source": "linkedin_search",
            "confidence_score": 0.55,
        })

        if len(people) >= max_results:
            break

    return people


def find_linkedin_people(company_name: str, domain: str = "") -> EnrichmentResult:
    """Find company employees via LinkedIn using search engines.

    Tries two queries:
      1. site:linkedin.com/in "[company]" CEO OR CTO OR founder
      2. site:linkedin.com/in "[domain]" (broader, domain-specific)

    Returns people extracted from search result snippets.
    """
    result = EnrichmentResult(provider="linkedin_search")

    if not company_name:
        result.error = "No company name"
        return result

    try:
        with httpx.Client(
            timeout=_TIMEOUT,
            follow_redirects=True,
            headers=_HEADERS,
        ) as client:
            all_people: list[dict] = []
            seen_names: set[str] = set()

            queries = [
                # High-priority roles first
                f'site:linkedin.com/in "{company_name}" CEO OR CTO OR founder OR "VP Engineering" OR "Head of Engineering"',
                # Broader search by domain
                f'site:linkedin.com/in "@{domain}"' if domain else "",
                # General leadership
                f'site:linkedin.com/in "{company_name}" director OR "vice president" OR "head of"',
            ]

            for i, query in enumerate(queries):
                if not query:
                    continue

                # Brief pause between queries to avoid rate-limiting
                if i > 0:
                    time.sleep(1)

                # Use Bing — DuckDuckGo is unreachable; Google 429s under batch load
                try:
                    url = f"https://www.bing.com/search?q={quote_plus(query)}&count=20"
                    resp = client.get(url)
                    if resp.status_code == 200:
                        soup = BeautifulSoup(resp.text, "html.parser")
                        people = _extract_people_from_search_results(soup, company_name)
                        for p in people:
                            key = (p["first_name"].lower(), p["last_name"].lower())
                            if key not in seen_names:
                                seen_names.add(key)  # type: ignore[arg-type]
                                all_people.append(p)
                        if people:
                            logger.info("LinkedIn search (Bing) found %d people for %s", len(people), company_name)
                except Exception as exc:
                    logger.debug("Bing LinkedIn search failed: %s", exc)

                # Stop after finding enough people
                if len(all_people) >= 10:
                    break

            result.contacts = all_people[:20]
            result.success = True

            if all_people:
                logger.info(
                    "LinkedIn people search complete for %s: %d contacts found",
                    company_name, len(all_people),
                )
            else:
                logger.debug("LinkedIn search found no people for %s", company_name)

    except Exception as exc:
        logger.warning("LinkedIn people search failed for %s: %s", company_name, exc)
        result.error = str(exc)

    return result
