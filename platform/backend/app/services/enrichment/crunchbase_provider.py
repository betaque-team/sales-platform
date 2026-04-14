"""Extract company funding data from search engine snippets.

Crunchbase's direct pages are blocked by Cloudflare. Instead, we:
1. Search Bing for "[company] site:crunchbase.com" — snippets often contain
   funding totals (e.g. "raised $334.8M in funding over 5 rounds")
2. Search Bing for "[company] funding raised" — news articles and press releases
   contain dollar amounts and round types
3. Search Bing for "[company] funding 2025 OR 2024" — recent funding news

Extracts:
- Total funding raised (display text + USD integer)
- Last funding round type (Seed, Series A-F, IPO, etc.)
- Employee count range
- Founded year
- Short description
- funded_at: approximate date of most recent funding round
- funding_news_url: URL of the funding announcement
"""

import logging
import re
import time
from datetime import datetime, timezone
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
}
_TIMEOUT = 20

# Funding amount patterns — matches "$50M", "$2.4B", "$500K"
_FUNDING_AMOUNT_RE = re.compile(
    r"\$(\d+(?:\.\d+)?)\s*(B(?:illion)?|M(?:illion)?|K(?:thousand)?)",
    re.IGNORECASE,
)

# Broader: "raised X million" / "raised X billion"
_RAISED_TEXT_RE = re.compile(
    r"raised\s+\$?(\d+(?:\.\d+)?)\s*(billion|million|thousand|[BMK])\b",
    re.IGNORECASE,
)

# Total funding statement from Crunchbase snippets:
# "has raised a total of $334.8M in funding"
# "has raised $50M in total funding"
_CB_TOTAL_RE = re.compile(
    r"raised\s+(?:a\s+total\s+of\s+)?\$(\d+(?:\.\d+)?)\s*(B(?:illion)?|M(?:illion)?|K(?:thousand)?)",
    re.IGNORECASE,
)

_STAGES = [
    "Series H", "Series G", "Series F", "Series E", "Series D",
    "Series C", "Series B", "Series A",
    "Pre-IPO", "IPO",
    "Seed Round", "Pre-Seed Round", "Seed",
    "Venture",
    "Private Equity",
    "Convertible Note",
]

_FOUNDED_RE = re.compile(r"(?:founded|established)\s+(?:in\s+)?(\d{4})", re.IGNORECASE)

# Funding date patterns
_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9,
    "oct": 10, "nov": 11, "dec": 12,
}
# "raised $X in January 2025" / "closed Series B in March 2024"
_FUNDED_MONTH_YEAR_RE = re.compile(
    r"(?:raised|closed|secured|announced|completed|received)\s+[^.]*?\b"
    r"(?:in\s+)?(January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\s+(\d{4})",
    re.IGNORECASE,
)
# "January 2025 funding" or "Series B in May 2024"
_MONTH_YEAR_RE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\s+(\d{4})\b",
    re.IGNORECASE,
)
# "Q1 2025", "Q3 2024"
_QUARTER_YEAR_RE = re.compile(r"\bQ([1-4])\s*(\d{4})\b", re.IGNORECASE)
# Bare year close to funding keywords: "raised ... 2025"
_YEAR_NEAR_FUNDING_RE = re.compile(
    r"(?:raised|closed|secured|funding|round)\s+[^.]{0,80}(20\d{2})", re.IGNORECASE
)
_QUARTER_MONTH = {1: 1, 2: 4, 3: 7, 4: 10}  # quarter → start month

_EMP_RANGE_RE = re.compile(
    r"(\d[\d,]*)\s*[–\-to]+\s*(\d[\d,]*)\s*employees",
    re.IGNORECASE,
)
_EMP_APPROX_RE = re.compile(
    r"(\d[\d,]+)\+?\s*employees",
    re.IGNORECASE,
)


def _amount_to_usd(amount_str: str, suffix: str) -> tuple[str, int]:
    """Convert amount string + suffix to display text and integer USD."""
    try:
        amount = float(amount_str)
    except ValueError:
        return "", 0

    s = suffix.upper()[0] if suffix else ""
    if s == "B":
        usd = int(amount * 1_000_000_000)
        display = f"${amount:.1f}B"
    elif s == "M":
        usd = int(amount * 1_000_000)
        display = f"${int(amount)}M" if amount == int(amount) else f"${amount:.1f}M"
    elif s == "K":
        usd = int(amount * 1_000)
        display = f"${int(amount)}K"
    else:
        usd = int(amount)
        display = f"${usd:,}"
    return display, usd


def _extract_funded_at(text: str) -> datetime | None:
    """Try to extract a funding announcement date from text. Returns UTC datetime or None."""
    now_year = datetime.now().year

    # 1. Most specific: month + year near funding keywords
    m = _FUNDED_MONTH_YEAR_RE.search(text)
    if not m:
        m = _MONTH_YEAR_RE.search(text)
    if m:
        month_name = m.group(1).lower()[:3]
        if month_name == "sep":
            month_name = "sep"
        month = _MONTHS.get(month_name) or _MONTHS.get(m.group(1).lower())
        year = int(m.group(2))
        if month and 2018 <= year <= now_year:
            try:
                return datetime(year, month, 1, tzinfo=timezone.utc)
            except ValueError:
                pass

    # 2. Quarter + year
    m2 = _QUARTER_YEAR_RE.search(text)
    if m2:
        quarter = int(m2.group(1))
        year = int(m2.group(2))
        if 2018 <= year <= now_year:
            return datetime(year, _QUARTER_MONTH[quarter], 1, tzinfo=timezone.utc)

    # 3. Bare year near funding keyword
    m3 = _YEAR_NEAR_FUNDING_RE.search(text)
    if m3:
        year = int(m3.group(1))
        if 2020 <= year <= now_year:
            return datetime(year, 1, 1, tzinfo=timezone.utc)

    return None


def _extract_from_text(text: str) -> dict:
    """Extract funding/company data from any block of text."""
    result: dict = {}

    # Total funding — try Crunchbase pattern first (most specific)
    m = _CB_TOTAL_RE.search(text)
    if not m:
        m = _FUNDING_AMOUNT_RE.search(text)
    if not m:
        m = _RAISED_TEXT_RE.search(text)

    if m:
        display, usd = _amount_to_usd(m.group(1), m.group(2))
        if display and usd >= 100_000:  # skip tiny amounts that are probably not funding
            result["total_funding"] = display
            result["total_funding_usd"] = usd

    # Funding stage — check for most specific stages first
    text_lower = text.lower()
    for stage in _STAGES:
        if stage.lower() in text_lower:
            result["funding_stage"] = stage
            break

    # Founded year
    m2 = _FOUNDED_RE.search(text)
    if m2:
        yr = int(m2.group(1))
        if 1980 <= yr <= 2025:
            result["founded_year"] = yr

    # Employee count
    m3 = _EMP_RANGE_RE.search(text)
    if m3:
        result["employee_count"] = f"{m3.group(1)}-{m3.group(2)}"
    else:
        m3 = _EMP_APPROX_RE.search(text)
        if m3:
            result["employee_count"] = f"{m3.group(1)}+"

    # Funding date — only attach if we found funding data
    if result.get("total_funding") or result.get("funding_stage"):
        dt = _extract_funded_at(text)
        if dt:
            result["funded_at"] = dt

    return result


def _get_bing_results(client: httpx.Client, query: str) -> list[dict]:
    """Search Bing and return list of {text, url} dicts."""
    try:
        url = f"https://www.bing.com/search?q={quote_plus(query)}&count=10"
        resp = client.get(url)
        if resp.status_code != 200:
            return []
        soup = BeautifulSoup(resp.text, "html.parser")

        results: list[dict] = []

        for item in soup.find_all("li", class_=re.compile(r"b_algo")):
            # Extract URL
            link = item.find("a", href=True)
            href = link["href"] if link else ""
            # Extract snippet text
            texts = []
            for el in item.find_all(["p", "div", "h2"], class_=re.compile(r"b_lineclamp|b_caption|b_snippet|b_algoSlug|b_title", re.I)):
                t = el.get_text(separator=" ", strip=True)
                if len(t) > 10:
                    texts.append(t)
            if not texts:
                texts = [item.get_text(separator=" ", strip=True)]
            combined = " ".join(texts)
            if combined:
                results.append({"text": combined, "url": href})

        # Broad sweep for funding lines
        full_text = soup.get_text(separator="\n", strip=True)
        for line in full_text.split("\n"):
            line = line.strip()
            if len(line) > 30 and any(
                kw in line.lower() for kw in ["raised", "funding", "series", "founded", "employees", "crunchbase"]
            ):
                results.append({"text": line, "url": ""})

        return results

    except Exception as exc:
        logger.debug("Bing search failed for %r: %s", query, exc)
        return []


def _get_bing_snippets(client: httpx.Client, query: str) -> list[str]:
    """Search Bing and return all result snippet texts."""
    from urllib.parse import quote_plus
    try:
        url = f"https://www.bing.com/search?q={quote_plus(query)}&count=10"
        resp = client.get(url)
        if resp.status_code != 200:
            return []
        soup = BeautifulSoup(resp.text, "html.parser")

        snippets: list[str] = []

        # Bing result snippets are in <p class="b_lineclamp..."> or <div class="b_caption">
        for el in soup.find_all(["p", "div"], class_=re.compile(r"b_lineclamp|b_caption|b_snippet|b_algoSlug", re.I)):
            text = el.get_text(separator=" ", strip=True)
            if len(text) > 20:
                snippets.append(text)

        # Also grab result titles which sometimes contain funding info
        for el in soup.find_all("h2"):
            text = el.get_text(separator=" ", strip=True)
            if len(text) > 10:
                snippets.append(text)

        # Broad sweep: any line mentioning funding keywords
        full_text = soup.get_text(separator="\n", strip=True)
        for line in full_text.split("\n"):
            line = line.strip()
            if len(line) > 30 and any(
                kw in line.lower() for kw in ["raised", "funding", "series", "founded", "employees", "crunchbase"]
            ):
                snippets.append(line)

        return snippets

    except Exception as exc:
        logger.debug("Bing search failed for %r: %s", query, exc)
        return []


def scrape_crunchbase_funding(company_name: str, domain: str = "") -> EnrichmentResult:
    """Extract funding data for a company via Bing search snippets.

    Uses two Bing searches:
    1. site:crunchbase.com search — Crunchbase snippets often contain funding totals
    2. General funding news search — catches press releases and announcements
    """
    result = EnrichmentResult(provider="crunchbase")

    if not company_name:
        result.error = "No company name"
        return result

    cur_year = datetime.now().year
    try:
        with httpx.Client(
            timeout=_TIMEOUT,
            follow_redirects=True,
            headers=_HEADERS,
        ) as client:
            merged: dict = {}
            news_url: str = ""

            def _absorb(results: list[dict]) -> bool:
                """Absorb results into merged dict. Returns True if fully populated."""
                nonlocal news_url
                for item in results:
                    data = _extract_from_text(item["text"])
                    for k, v in data.items():
                        if k not in merged:
                            merged[k] = v
                    # Capture first news URL that mentions funding
                    if not news_url and item.get("url") and any(
                        kw in item["text"].lower() for kw in ["raised", "series", "funding"]
                    ):
                        u = item["url"]
                        if u and not u.startswith("https://www.bing.com") and "crunchbase.com" not in u:
                            news_url = u
                return bool(merged.get("total_funding") and merged.get("funding_stage"))

            # Query 1: Crunchbase snippet (most reliable for total funding)
            q1 = f'"{company_name}" site:crunchbase.com funding'
            _absorb(_get_bing_results(client, q1))

            # Query 2: general funding news
            if not merged.get("total_funding") or not merged.get("funding_stage"):
                time.sleep(0.5)
                q2 = f'"{company_name}" raised funding'
                _absorb(_get_bing_results(client, q2))

            # Query 3: recent funding — specifically targets 2024/2025 news
            if not merged.get("funded_at"):
                time.sleep(0.5)
                q3 = f'"{company_name}" funding raised {cur_year} OR {cur_year - 1}'
                _absorb(_get_bing_results(client, q3))

            if news_url:
                merged["funding_news_url"] = news_url

            if merged:
                result.company_data = merged
                result.success = True
                logger.info(
                    "Funding search: %s → funding=%s, stage=%s, funded_at=%s",
                    company_name,
                    merged.get("total_funding", "—"),
                    merged.get("funding_stage", "—"),
                    merged.get("funded_at", "—"),
                )
            else:
                result.success = True
                logger.debug("No funding data found for %s", company_name)

    except Exception as exc:
        logger.warning("Funding search failed for %s: %s", company_name, exc)
        result.error = str(exc)

    return result
