"""Scrape company website for enrichment data.

Uses httpx + BeautifulSoup. Limited to 8 page fetches per company, 15s timeout each.
"""

import logging
import re
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup, Tag

from app.services.enrichment.base import EnrichmentResult

logger = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
_TIMEOUT = 15
_MAX_FETCHES = 15  # Generous limit since 404s are cheap

# Emails to exclude from person contacts
_GENERIC_EMAIL_PREFIXES = frozenset([
    "info", "support", "hello", "contact", "sales", "help",
    "admin", "team", "careers", "jobs", "hr", "press",
    "media", "legal", "billing", "noreply", "no-reply",
    "office", "general", "enquiries", "feedback",
    "security", "abuse", "postmaster", "webmaster",
    "api", "dev", "engineering", "ops", "devops",
    "marketing", "partnerships", "investors", "compliance",
    "privacy", "data", "accounts", "finance",
])

# Pattern for email local parts that look like person names
_PERSON_EMAIL_RE = re.compile(
    r"^[a-z]{2,}[._-]?[a-z]{2,}$"  # first.last, flast, first_last, etc.
)


def _is_person_email(email: str) -> bool:
    """Check if an email address looks like it belongs to a person (not a system/generic address)."""
    local = email.split("@")[0].lower()
    if local in _GENERIC_EMAIL_PREFIXES:
        return False
    # Multi-word locals with dots that don't look like names
    # e.g., "swap.volume", "total.swaps", "wallets.connected"
    parts = re.split(r"[._-]", local)
    if len(parts) >= 2:
        # Check if parts look like name components (short, alpha-only)
        for part in parts:
            if not part.isalpha():
                return False
            # Common non-name words
            if part in {"swap", "total", "wallets", "volume", "connected", "swaps",
                        "test", "auto", "system", "bot", "alert", "notify", "report",
                        "daily", "weekly", "monthly", "backup", "sync", "update",
                        "service", "internal", "external", "public", "private",
                        "new", "old", "main", "primary", "secondary"}:
                return False
    elif len(local) > 20:
        return False
    return True


def _make_client() -> httpx.Client:
    return httpx.Client(timeout=_TIMEOUT, follow_redirects=True, headers=_HEADERS)


def _fetch_page(client: httpx.Client, url: str, fetch_counter: list[int]) -> BeautifulSoup | None:
    """Fetch a URL and return parsed soup, or None on failure.

    Uses *fetch_counter* (mutable list of one int) to track total fetches.
    """
    if fetch_counter[0] >= _MAX_FETCHES:
        logger.debug("Reached max fetch limit, skipping %s", url)
        return None
    try:
        fetch_counter[0] += 1
        resp = client.get(url)
        if resp.status_code != 200:
            return None
        return BeautifulSoup(resp.text, "html.parser")
    except (httpx.HTTPError, httpx.TimeoutException, Exception) as exc:
        logger.debug("Failed to fetch %s: %s", url, exc)
        return None


def _try_paths(client: httpx.Client, base_url: str, paths: list[str], fetch_counter: list[int]) -> BeautifulSoup | None:
    """Try multiple paths under base_url, return first successful soup."""
    for path in paths:
        url = urljoin(base_url, path)
        soup = _fetch_page(client, url, fetch_counter)
        if soup is not None:
            return soup
    return None


# -------------------------------------------------------------------------
# Homepage extraction
# -------------------------------------------------------------------------

def _extract_meta_description(soup: BeautifulSoup) -> str:
    meta = soup.find("meta", attrs={"name": "description"})
    if meta and meta.get("content"):
        return str(meta["content"]).strip()
    # Also try og:description
    meta_og = soup.find("meta", attrs={"property": "og:description"})
    if meta_og and meta_og.get("content"):
        return str(meta_og["content"]).strip()
    return ""


def _extract_social_links(soup: BeautifulSoup) -> dict:
    """Extract LinkedIn and Twitter URLs from anchor tags."""
    socials: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        href = str(a["href"]).lower()
        if "linkedin.com/company/" in href and "linkedin_url" not in socials:
            socials["linkedin_url"] = str(a["href"]).split("?")[0]
        if ("twitter.com/" in href or "x.com/" in href) and "twitter_url" not in socials:
            socials["twitter_url"] = str(a["href"]).split("?")[0]
    return socials


def _extract_footer_location(soup: BeautifulSoup) -> str:
    """Try to find an address hint in footer elements."""
    footer = soup.find("footer")
    if not footer:
        return ""
    text = footer.get_text(separator=" ", strip=True)
    # Look for patterns like city, state or city, country
    # Simple heuristic: lines with commas and common location words
    for line in text.split("\n"):
        line = line.strip()
        if "," in line and len(line) < 200:
            return line
    return ""


# -------------------------------------------------------------------------
# About page extraction
# -------------------------------------------------------------------------

def _extract_about_description(soup: BeautifulSoup) -> str:
    """First <p> with >50 chars inside main content area."""
    # Try <main>, <article>, or fall back to body
    for container_tag in ["main", "article"]:
        container = soup.find(container_tag)
        if container:
            for p in container.find_all("p"):
                text = p.get_text(strip=True)
                if len(text) > 50:
                    return text
            break

    # Fallback: any <p> with >50 chars
    for p in soup.find_all("p"):
        text = p.get_text(strip=True)
        if len(text) > 50:
            return text
    return ""


def _extract_founded_year(soup: BeautifulSoup) -> int | None:
    """Search for founded/established year in page text."""
    text = soup.get_text(separator=" ", strip=True)
    match = re.search(r"(?:founded|established|since)\s*(?:in\s*)?(\d{4})", text, re.IGNORECASE)
    if match:
        year = int(match.group(1))
        if 1900 <= year <= 2030:
            return year
    return None


def _extract_employee_count(soup: BeautifulSoup) -> str:
    """Search for employee count patterns in page text."""
    text = soup.get_text(separator=" ", strip=True)
    patterns = [
        r"(\d[\d,]*)\+?\s*(?:employees|team members|people|staff|associates)",
        r"team of (\d[\d,]*)",
        r"over (\d[\d,]*)\s*(?:employees|people|team members)",
        r"(\d[\d,]+)\s*(?:person|people)\s*(?:team|company|organization)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).replace(",", "")
    return ""


def _extract_funding(soup: BeautifulSoup) -> dict:
    """Search for funding mentions in page text (About, Press, Newsroom pages)."""
    text = soup.get_text(separator=" ", strip=True)
    result: dict = {}

    # Total funding raised
    funding_patterns = [
        (r"raised\s+(?:over\s+|more\s+than\s+)?\$(\d+(?:\.\d+)?)\s*(B|billion)", "B"),
        (r"raised\s+(?:over\s+|more\s+than\s+)?\$(\d+(?:\.\d+)?)\s*(M|million)", "M"),
        (r"\$(\d+(?:\.\d+)?)\s*(B|billion)\s+(?:in\s+)?(?:total\s+)?(?:funding|raised|investment)",  "B"),
        (r"\$(\d+(?:\.\d+)?)\s*(M|million)\s+(?:in\s+)?(?:total\s+)?(?:funding|raised|investment)", "M"),
        (r"(?:total\s+)?(?:funding|investment)\s+of\s+\$(\d+(?:\.\d+)?)\s*(M|B|million|billion)", None),
    ]
    for pattern, default_suffix in funding_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                amount = float(match.group(1))
                suffix_raw = match.group(2) if len(match.groups()) > 1 else (default_suffix or "M")
                suffix = suffix_raw[0].upper()
                if suffix == "B":
                    usd = int(amount * 1_000_000_000)
                    result["total_funding"] = f"${amount:.1f}B"
                else:
                    usd = int(amount * 1_000_000)
                    result["total_funding"] = f"${amount:.0f}M"
                result["total_funding_usd"] = usd
            except (ValueError, IndexError):
                pass
            break

    # Funding round/stage
    for stage in ["Series F", "Series E", "Series D", "Series C",
                  "Series B", "Series A", "Seed Round", "Pre-Seed"]:
        if re.search(r"\b" + re.escape(stage) + r"\b", text, re.IGNORECASE):
            result["funding_stage"] = stage
            break

    return result


# -------------------------------------------------------------------------
# Logo extraction
# -------------------------------------------------------------------------

def _extract_logo_url(soup: BeautifulSoup, base_url: str) -> str:
    """Extract company logo URL from homepage meta tags and link elements."""
    # 1. og:image (most common for company branding)
    og_image = soup.find("meta", attrs={"property": "og:image"})
    if og_image and og_image.get("content"):
        url = str(og_image["content"]).strip()
        if url.startswith("http"):
            return url
        return urljoin(base_url, url)

    # 2. apple-touch-icon (high-res square logo)
    for link in soup.find_all("link", rel=True):
        rels = link.get("rel", [])
        if isinstance(rels, list):
            rels = " ".join(rels)
        if "apple-touch-icon" in rels.lower() and link.get("href"):
            href = str(link["href"]).strip()
            if href.startswith("http"):
                return href
            return urljoin(base_url, href)

    # 3. Large favicon (icon with sizes >= 128)
    for link in soup.find_all("link", rel=True):
        rels = link.get("rel", [])
        if isinstance(rels, list):
            rels = " ".join(rels)
        if "icon" in rels.lower() and link.get("href"):
            sizes = str(link.get("sizes", ""))
            if sizes:
                try:
                    w = int(sizes.split("x")[0])
                    if w >= 128:
                        href = str(link["href"]).strip()
                        if href.startswith("http"):
                            return href
                        return urljoin(base_url, href)
                except (ValueError, IndexError):
                    pass

    # 4. First <img> in header/nav with "logo" in src, alt, or class
    for container in soup.find_all(["header", "nav"]):
        for img in container.find_all("img"):
            src = str(img.get("src", "")).lower()
            alt = str(img.get("alt", "")).lower()
            cls = " ".join(img.get("class", [])).lower() if img.get("class") else ""
            if any(kw in (src + alt + cls) for kw in ["logo", "brand"]):
                href = str(img.get("src", "")).strip()
                if href:
                    if href.startswith("http"):
                        return href
                    return urljoin(base_url, href)

    return ""


# -------------------------------------------------------------------------
# Team page extraction — multi-strategy
# -------------------------------------------------------------------------

# Title keywords that identify a role (not just random text)
_ROLE_KEYWORDS = [
    "ceo", "cto", "cfo", "coo", "ciso", "cpo", "cmo", "chief",
    "president", "founder", "co-founder", "cofounder",
    "vice president", "vp ", "vp,",
    "director", "head of", "head,",
    "manager", "lead", "principal",
    "engineer", "developer", "designer", "architect",
    "recruiter", "talent", "people", "hr ",
    "marketing", "sales", "operations", "finance",
    "counsel", "legal", "officer", "partner",
    "analyst", "scientist", "researcher",
    "advisor", "board member", "evangelist",
    "chairman", "chairperson", "chairwoman", "managing",
    "svp", "evp", "senior vice",
]


def _looks_like_name(text: str) -> bool:
    """Check if text looks like a person's name (2-3 capitalized words, each 2-15 chars).

    Uses a multi-signal approach:
    1. Basic structure (2-4 words, capitalized, no digits)
    2. Blocklist of known non-name words
    3. Role keyword detection (rejects "Chief Revenue Officer" etc.)
    4. English word suffix detection (rejects "Staffing", "Intelligence" etc.)
    """
    if not text or len(text) > 40 or len(text) < 4:
        return False
    # No numbers, special chars (except period for "Jr." or hyphen for double names)
    if re.search(r"\d", text):
        return False
    if re.search(r"[!@#$%^&*()+=\[\]{}<>|/\\]", text):
        return False
    words = text.split()
    if len(words) < 2 or len(words) > 4:
        return False
    # Each word must be 2-15 chars, start with uppercase, be alpha (allow hyphens, periods)
    for w in words:
        if len(w) < 2 or len(w) > 15:
            return False
        if not w[0].isupper():
            return False
        # Must be mostly alphabetic
        alpha_count = sum(1 for c in w if c.isalpha())
        if alpha_count < len(w) * 0.7:
            return False
    # ALL words must start with uppercase (names are always capitalized)
    if not all(w[0].isupper() for w in words):
        return False
    # Block common non-name words
    _non_name_words = {
        # Common English words / page labels
        "the", "our", "meet", "show", "hide", "new", "all", "how", "what",
        "why", "who", "use", "get", "buy", "try", "see", "app", "api",
        "read", "view", "more", "just", "join", "this", "that", "with",
        "for", "and", "are", "was", "not", "has", "had", "but", "about",
        "from", "have", "been", "also", "into", "some", "most", "best",
        "learn", "click", "visit", "start", "build", "close", "great",
        "first", "last", "name", "home", "help", "back", "next", "open",
        "blog", "docs", "news", "team", "case", "data", "your",
        "explore", "discover", "download", "schedule", "request",
        # Business/corporate terms
        "product", "service", "solution", "platform", "company",
        "business", "enterprise", "corporate", "digital", "global",
        "account", "customer", "industry", "training", "compliance",
        "backed", "listed", "career", "domain", "website", "example",
        "motors", "drives", "energy", "building", "leading", "enabling",
        "highly", "skilled", "ready", "powered", "trusted", "network",
        "traffic", "stories", "studies", "resources", "submitted",
        "cloud", "fast", "live", "streaming", "forward", "channel",
        "partners", "integration", "pricing", "billing", "plans",
        "standard", "premium", "pro", "plus", "basic", "suite",
        "mobile", "desktop", "server", "hub", "lab", "labs",
        "edge", "core", "connect", "works", "insights",
        # Section heading words that look like names but aren't
        "advisory", "council", "board", "member", "independent",
        "leadership", "teams", "management", "committee", "group",
        # Company/HR marketing words
        "hire", "hiring", "anywhere", "everywhere", "worldwide",
        "international", "recruitment", "recruiting", "contractor",
        "referral", "program", "provider", "reviews", "record",
        "remote", "onsite", "hybrid", "office", "offices",
        "benefits", "perks", "culture", "values", "mission",
        "overview", "summary", "report", "annual", "quarterly",
        "featured", "latest", "popular", "trending", "upcoming",
        "search", "filter", "sort", "browse", "apply",
        "submit", "login", "signup", "register", "subscribe",
        "toggle", "menu", "submenu", "navigation", "sidebar",
        # Company/product names that appear as page labels
        "docker", "kubernetes", "terraform", "ansible", "github",
        "google", "amazon", "microsoft", "oracle", "cisco",
        "thomson", "reuters", "bloomberg", "deloitte",
        "virtues", "principles", "obsession", "excellence",
        # Common page section / product label words
        "resource", "center", "video", "library", "press", "room", "financial",
        "audit", "code", "threat", "intel", "sharing", "resolution",
        "conflict", "staffing", "dialing", "mode", "agents", "results",
        "feeds", "generator", "description", "numbers", "local",
        "parallel", "safer", "smarter", "future", "manage", "contact",
        "real", "crm", "zoho", "salesforce", "intelligence",
        "rovo", "dev", "agentic", "workforce", "knowledge",
        "mentors", "motivators", "developers",
        "tool", "tools", "license", "responsible", "cookie",
        "policy", "accessibility", "statement", "computer",
        "vision", "academy", "labeling", "powered", "engine",
        "framework", "toolkit", "analytics", "automation",
        "detection", "monitoring", "observability", "logging",
        "dashboard", "console", "portal", "registry",
        "catalog", "marketplace", "gallery", "studio",
    }
    for w in words:
        if w.lower() in _non_name_words:
            return False
    # If the text itself looks like a job title, it's not a name
    # (catches "Chief Revenue Officer", "Board Member", "VP Engineering" etc.)
    t_lower = text.lower()
    if any(kw in t_lower for kw in _ROLE_KEYWORDS):
        return False
    # Reject if ALL words look like common English words (non-name words)
    # based on typical English word suffixes that names rarely have
    _non_name_suffixes = (
        "tion", "sion", "ment", "ness", "ence", "ance", "ity", "ery",
        "ure", "age", "ing", "ism", "ist", "ful", "ous", "ive",
        "ary", "ory", "ble", "ics", "ogy",
    )
    suffix_count = sum(
        1 for w in words
        if len(w) > 5 and w.lower().endswith(_non_name_suffixes)
    )
    # If ALL words end in common suffixes, very unlikely to be a name
    if suffix_count == len(words):
        return False
    # If majority of a 3+ word name has these suffixes, also reject
    if len(words) >= 3 and suffix_count >= len(words) - 1:
        return False
    return True


def _looks_like_title(text: str) -> bool:
    """Check if text looks like a job title (not just any text with a keyword)."""
    if not text or len(text) > 80 or len(text) < 2:
        return False
    # Must be short and clean (actual titles are concise)
    words = text.split()
    if len(words) > 12:
        return False
    # Should not contain sentences (periods followed by more text)
    if ". " in text and text.count(".") > 1:
        return False
    # Should not contain URLs or HTML artifacts
    if any(kw in text.lower() for kw in ["http", "www.", ".com", "<", ">"]):
        return False
    # Should not contain marketing/CTA phrases
    _bad_title_phrases = [
        "find your", "carry the", "partner with", "join the",
        "we carry", "we help", "we build", "your next",
        "learn more", "read more", "see all", "view all",
        "sign up", "log in", "get started", "book a demo",
        "request a demo", "contact us", "talk to",
    ]
    tl = text.lower()
    if any(phrase in tl for phrase in _bad_title_phrases):
        return False
    return any(kw in tl for kw in _ROLE_KEYWORDS)


def _classify_role_category(title: str) -> str:
    """Classify a person's role category based on their title."""
    t = title.lower()
    if any(kw in t for kw in ["ceo", "coo", "cfo", "cto", "ciso", "cpo", "cmo", "chief",
                               "founder", "co-founder", "cofounder", "president",
                               "chairman", "chairperson", "chairwoman"]):
        return "c_suite"
    if any(kw in t for kw in ["vp engineering", "engineering director", "head of engineering",
                               "platform lead", "director of engineering",
                               "vp of engineering", "engineering lead",
                               "director of platform", "head of infrastructure",
                               "vp technology", "director of technology",
                               "svp of engineering", "evp engineering"]):
        return "engineering_lead"
    if any(kw in t for kw in ["vp ", "vp,", "vice president", "svp", "evp"]):
        return "executive"
    if any(kw in t for kw in ["recruiter", "talent acquisition", "hiring manager",
                               "hr director", "people operations", "head of people",
                               "talent partner", "recruiting", "head of talent",
                               "director of people", "people team"]):
        return "hiring"
    if any(kw in t for kw in ["security", "ciso", "devsecops", "infosec"]):
        return "security"
    if any(kw in t for kw in ["engineer", "developer", "architect", "devops",
                               "sre", "platform", "infrastructure"]):
        return "engineering"
    return "other"


def _classify_seniority(title: str) -> str:
    """Classify seniority level from title."""
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


def _clean_title(title: str) -> str:
    """Clean up title text: strip 'at CompanyName' suffixes, trailing noise."""
    if not title:
        return title
    # Remove "at CompanyName" or "atCompanyName" from end of title
    # e.g., "CTOatPlaid" -> "CTO", "Software EngineeratEnvoy" -> "Software Engineer"
    title = re.sub(r"\s*at[A-Z][a-zA-Z]+.*$", "", title)
    # Also handle "at Company" with space
    title = re.sub(r",?\s+at\s+[A-Z].*$", "", title)
    # Remove trailing company name after comma: "CEO, IMPACT" -> "CEO" only if all-caps word looks like company
    # Actually keep "CEO, IMPACT" as-is since IMPACT could be the division
    # Strip trailing "The BBC", "Best Buy" etc. after comma if preceded by recognized title
    title = re.sub(r",\s+The\s+[A-Z].*$", "", title)
    return title.strip()


# Regex to detect where a title starts within concatenated text
_TITLE_START_RE = re.compile(
    r"(Chief|CEO|CTO|CFO|COO|CISO|CPO|CMO|"
    r"VP|Vice|Director|Head|President|Founder|Co-Founder|"
    r"SVP|EVP|Managing|Staff|Senior|Lead|Principal|Associate|"
    r"Software|Machine|Frontend|Backend|Fullstack|Full-Stack|"
    r"Research|General|Executive|Partner)"
)


def _clean_name(name: str) -> str:
    """Clean up name text: strip prefixes like 'Linkedin', 'HomeAbout', etc."""
    if not name:
        return name
    # Strip "Linkedin" prefix (from LinkedIn link anchor text)
    if name.startswith("Linkedin") and len(name) > 8 and name[8].isupper():
        name = name[8:]
    # Strip "Home" prefix
    if name.startswith("Home") and len(name) > 4 and name[4].isupper():
        name = name[4:]
    # Strip "About" prefix
    if name.startswith("About") and len(name) > 5 and name[5].isupper():
        name = name[5:]
    return name.strip()


def _make_contact_dict(full_name: str, title: str, linkedin_url: str = "") -> dict | None:
    """Create a contact dict from name and title. Returns None if invalid.

    STRICT: requires both a valid name AND either a valid title or LinkedIn URL.
    This prevents random page text from being treated as contacts.
    """
    # Clean name prefixes
    full_name = _clean_name(full_name)

    # Handle name+title concatenation (e.g., "Mike PyleChief Revenue Officer",
    # "Allan ReyesStaff Security EngineerVanta")
    concat_match = _TITLE_START_RE.search(full_name)
    if concat_match and concat_match.start() > 4:
        # Split: name is before, title is from the match
        extracted_title = full_name[concat_match.start():]
        full_name = full_name[:concat_match.start()].strip()
        if not title or not _looks_like_title(title):
            title = extracted_title

    # Clean title (strip "atCompanyName" etc.)
    title = _clean_title(title)

    if not full_name or not _looks_like_name(full_name):
        return None

    # Must have either a recognized title OR a LinkedIn URL to confirm this is a real person
    has_valid_title = title and _looks_like_title(title)
    has_linkedin = bool(linkedin_url and "linkedin.com/in/" in linkedin_url.lower())

    if not has_valid_title and not has_linkedin:
        return None

    name_parts = full_name.split(None, 1)
    first_name = name_parts[0] if name_parts else ""
    last_name = name_parts[1] if len(name_parts) > 1 else ""

    if not first_name or not last_name:
        return None

    role_category = _classify_role_category(title) if has_valid_title else "other"
    seniority = _classify_seniority(title) if has_valid_title else "other"
    is_decision_maker = seniority in ("c_suite", "vp", "director")

    return {
        "first_name": first_name,
        "last_name": last_name,
        "title": title if has_valid_title else "",
        "role_category": role_category,
        "seniority": seniority,
        "is_decision_maker": is_decision_maker,
        "linkedin_url": linkedin_url,
        "source": "website_scrape",
    }


def _dedup_contacts(contacts: list[dict]) -> list[dict]:
    """Deduplicate contacts by full name."""
    seen = set()
    result = []
    for c in contacts:
        key = (c.get("first_name", "").lower(), c.get("last_name", "").lower())
        if key not in seen and key != ("", ""):
            seen.add(key)
            result.append(c)
    return result


def _extract_team_members(soup: BeautifulSoup) -> list[dict]:
    """Extract person cards from a team/leadership page using multiple strategies."""
    all_contacts = []

    # === Strategy 1: CSS class matching (original approach, still useful for some sites) ===
    _team_class_re = re.compile(r"team|member|person|leader|staff|people|executive|founder|bio|profile", re.IGNORECASE)
    _title_class_re = re.compile(r"title|role|position|job|designation|bio", re.IGNORECASE)

    cards = soup.find_all(["div", "li", "section", "article"], class_=_team_class_re)
    for card in cards:
        if not isinstance(card, Tag):
            continue
        name_tag = card.find(["h2", "h3", "h4", "h5", "strong"])
        if not name_tag:
            continue
        full_name = name_tag.get_text(strip=True)
        if not _looks_like_name(full_name):
            continue

        title = ""
        title_el = card.find(["p", "span", "div"], class_=_title_class_re)
        if title_el:
            title = title_el.get_text(strip=True)
        else:
            for p in card.find_all(["p", "span"]):
                p_text = p.get_text(strip=True)
                if p_text and p_text != full_name and len(p_text) < 100:
                    if _looks_like_title(p_text):
                        title = p_text
                        break

        linkedin_url = ""
        for a in card.find_all("a", href=True):
            href = str(a["href"])
            if "linkedin.com/in/" in href.lower():
                linkedin_url = href.split("?")[0]
                break

        contact = _make_contact_dict(full_name, title, linkedin_url)
        if contact:
            all_contacts.append(contact)

    # === Strategy 2: Repeated sibling pattern detection ===
    # Find groups of same-tag siblings that look like person cards
    if len(all_contacts) < 3:
        for container_tag in ["ul", "ol", "div", "section"]:
            for container in soup.find_all(container_tag):
                children = [c for c in container.children if isinstance(c, Tag)]
                if len(children) < 3:
                    continue

                # Check if children share the same tag name
                tag_names = [c.name for c in children]
                dominant_tag = max(set(tag_names), key=tag_names.count) if tag_names else ""
                same_tag_children = [c for c in children if c.name == dominant_tag]
                if len(same_tag_children) < 3:
                    continue

                # Try to extract name+title from each child
                group_contacts = []
                for child in same_tag_children:
                    # Look for image (headshot indicator)
                    has_image = child.find("img") is not None

                    # Get all text elements
                    texts = []
                    for el in child.find_all(["h1", "h2", "h3", "h4", "h5", "strong", "b", "p", "span", "div"]):
                        t = el.get_text(strip=True)
                        if t and len(t) < 120 and t not in [x for x, _ in texts]:
                            texts.append((t, el.name))

                    if len(texts) < 2:
                        continue

                    # First heading-like text = name, next text = title
                    name_text = ""
                    title_text = ""
                    for t, tag in texts:
                        if not name_text and _looks_like_name(t):
                            name_text = t
                        elif name_text and not title_text and t != name_text:
                            if _looks_like_title(t):
                                title_text = t

                    # Must have both name AND title (or LinkedIn)
                    if not name_text or not title_text:
                        continue

                    linkedin_url = ""
                    for a in child.find_all("a", href=True):
                        if "linkedin.com/in/" in str(a["href"]).lower():
                            linkedin_url = str(a["href"]).split("?")[0]
                            break

                    contact = _make_contact_dict(name_text, title_text, linkedin_url)
                    if contact:
                        group_contacts.append(contact)

                # Only use this group if we got at least 3 people (indicates a real team grid)
                if len(group_contacts) >= 3:
                    all_contacts.extend(group_contacts)
                    break
            if len(all_contacts) >= 3:
                break

    # === Strategy 3: LinkedIn profile links ===
    # Find all LinkedIn profile links and extract surrounding name/title context
    if len(all_contacts) < 3:
        seen_linkedin = {c.get("linkedin_url", "").lower() for c in all_contacts if c.get("linkedin_url")}
        for a_tag in soup.find_all("a", href=True):
            href = str(a_tag["href"])
            if "linkedin.com/in/" not in href.lower():
                continue
            linkedin_url = href.split("?")[0]
            if linkedin_url.lower() in seen_linkedin:
                continue
            seen_linkedin.add(linkedin_url.lower())

            # Walk up to find the card container
            parent = a_tag.parent
            for _ in range(5):
                if parent is None or parent.name in ("body", "html"):
                    break
                # Check if this parent has name-like text
                texts = []
                for el in parent.find_all(["h2", "h3", "h4", "h5", "strong", "b", "p", "span"]):
                    t = el.get_text(strip=True)
                    if t and len(t) < 120:
                        texts.append(t)

                name_text = ""
                title_text = ""
                for t in texts:
                    if not name_text and _looks_like_name(t):
                        name_text = t
                    elif name_text and not title_text and t != name_text:
                        if _looks_like_title(t):
                            title_text = t

                if name_text:
                    contact = _make_contact_dict(name_text, title_text, linkedin_url)
                    if contact:
                        all_contacts.append(contact)
                    break
                parent = parent.parent

    # === Strategy 4: Heading + paragraph pairs ===
    # Look for h3/h4 (name) followed by p/span (title) within team-section context
    if len(all_contacts) < 3:
        # Find sections with team-related headings
        team_headings = soup.find_all(["h1", "h2", "h3"], string=re.compile(
            r"team|leadership|people|who we are|meet the|our leaders|executives|management",
            re.IGNORECASE,
        ))
        for heading in team_headings:
            # Get the parent section
            section = heading.parent
            if section is None:
                continue

            # Look for name headings within this section
            for name_el in section.find_all(["h3", "h4", "h5", "strong"]):
                if name_el == heading:
                    continue
                full_name = name_el.get_text(strip=True)
                if not _looks_like_name(full_name):
                    continue

                # Find the title: next sibling or next element
                title = ""
                next_el = name_el.find_next_sibling(["p", "span", "div"])
                if next_el:
                    title = next_el.get_text(strip=True)
                    if len(title) > 120:
                        title = ""

                linkedin_url = ""
                parent_card = name_el.parent
                if parent_card:
                    for a in parent_card.find_all("a", href=True):
                        if "linkedin.com/in/" in str(a["href"]).lower():
                            linkedin_url = str(a["href"]).split("?")[0]
                            break

                contact = _make_contact_dict(full_name, title, linkedin_url)
                if contact:
                    all_contacts.append(contact)

    result = _dedup_contacts(all_contacts)
    # Cap at 50 to avoid scraping noise
    return result[:50]


# -------------------------------------------------------------------------
# Contact page extraction
# -------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(r"(?:\+?\d{1,3}[\s\-.]?)?\(?\d{2,4}\)?[\s\-.]?\d{3,4}[\s\-.]?\d{3,4}")


def _extract_contact_info(soup: BeautifulSoup) -> dict:
    """Extract emails, phones, and address from a contact page."""
    text = soup.get_text(separator=" ", strip=True)

    # Emails
    all_emails = list(set(_EMAIL_RE.findall(text)))
    person_emails = []
    company_emails = []
    for email in all_emails:
        if _is_person_email(email):
            person_emails.append(email)
        else:
            company_emails.append(email)

    # Phone numbers
    phones = list(set(_PHONE_RE.findall(text)))
    # Filter very short matches
    phones = [p.strip() for p in phones if len(p.strip()) >= 7]

    # Address: look for structured address elements
    address = ""
    addr_el = soup.find("address")
    if addr_el:
        address = addr_el.get_text(separator=", ", strip=True)
    else:
        # Try common class names
        for cls_name in ["address", "location", "office-address"]:
            el = soup.find(class_=re.compile(cls_name, re.IGNORECASE))
            if el:
                address = el.get_text(separator=", ", strip=True)
                break

    return {
        "person_emails": person_emails[:10],
        "company_emails": company_emails[:10],
        "phones": phones[:5],
        "address": address[:500] if address else "",
    }


# -------------------------------------------------------------------------
# Main scraper
# -------------------------------------------------------------------------

def scrape_company_website(website: str) -> EnrichmentResult:
    """Scrape a company website for enrichment data.

    Fetches up to 8 pages: homepage, about, team/leadership, contact.

    Args:
        website: Company website URL.

    Returns:
        EnrichmentResult with company_data, contacts, and offices.
    """
    result = EnrichmentResult(provider="website_scraper")

    if not website or not website.strip():
        result.error = "No website provided"
        return result

    url = website.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    # Ensure base URL ends without trailing path for urljoin
    base_url = url.rstrip("/") + "/"

    fetch_counter = [0]
    company_data: dict = {}

    try:
        with _make_client() as client:

            # --- 1. Homepage ---
            homepage_soup = _fetch_page(client, url, fetch_counter)
            if homepage_soup:
                desc = _extract_meta_description(homepage_soup)
                if desc:
                    company_data["description"] = desc

                socials = _extract_social_links(homepage_soup)
                company_data.update(socials)

                # Extract logo from homepage
                logo_url = _extract_logo_url(homepage_soup, base_url)
                if logo_url:
                    company_data["logo_url"] = logo_url

                footer_loc = _extract_footer_location(homepage_soup)
                if footer_loc:
                    company_data["footer_location"] = footer_loc

            # --- 2. About page ---
            about_soup = _try_paths(client, base_url, ["/about", "/about-us", "/company"], fetch_counter)
            if about_soup:
                about_desc = _extract_about_description(about_soup)
                if about_desc:
                    company_data["description"] = about_desc

                founded = _extract_founded_year(about_soup)
                if founded:
                    company_data["founded_year"] = founded

                emp_count = _extract_employee_count(about_soup)
                if emp_count:
                    company_data["employee_count"] = emp_count

                # Extract funding mentions from about page
                funding_data = _extract_funding(about_soup)
                if funding_data.get("total_funding") and not company_data.get("total_funding"):
                    company_data["total_funding"] = funding_data["total_funding"]
                if funding_data.get("total_funding_usd") and not company_data.get("total_funding_usd"):
                    company_data["total_funding_usd"] = funding_data["total_funding_usd"]
                if funding_data.get("funding_stage") and not company_data.get("funding_stage"):
                    company_data["funding_stage"] = funding_data["funding_stage"]

            # --- 3. Team/Leadership page (expanded paths) ---
            team_soup = _try_paths(
                client, base_url,
                ["/team", "/about/team", "/leadership", "/about/leadership",
                 "/people", "/our-team", "/about-us/team", "/company/team",
                 "/about-us/leadership", "/who-we-are"],
                fetch_counter,
            )
            contacts = []
            if team_soup:
                contacts = _extract_team_members(team_soup)
                logger.info("Found %d team members on team page", len(contacts))

            # If team page found nothing, try extracting from about page too
            if not contacts and about_soup:
                about_contacts = _extract_team_members(about_soup)
                if about_contacts:
                    contacts = about_contacts
                    logger.info("Found %d team members on about page", len(contacts))

            # Also try homepage if still nothing (some small companies list team on home)
            if not contacts and homepage_soup:
                home_contacts = _extract_team_members(homepage_soup)
                if home_contacts:
                    contacts = home_contacts
                    logger.info("Found %d team members on homepage", len(contacts))

            # --- 4. Contact page ---
            contact_soup = _try_paths(client, base_url, ["/contact", "/contact-us"], fetch_counter)
            offices = []
            if contact_soup:
                contact_info = _extract_contact_info(contact_soup)
                if contact_info.get("address"):
                    offices.append({
                        "label": "Main Office",
                        "address": contact_info["address"],
                        "city": "",
                        "country": "",
                        "is_headquarters": True,
                        "source": "website_scrape",
                    })
                # Store all discovered emails as company-level data
                all_emails = contact_info.get("company_emails", []) + contact_info.get("person_emails", [])
                if all_emails:
                    company_data["company_emails"] = all_emails
                if contact_info.get("phones"):
                    company_data["company_phones"] = contact_info["phones"]

        # --- 5. Press/Newsroom page for funding data (if not yet found) ---
        if not company_data.get("total_funding"):
            press_soup = _try_paths(
                client, base_url,
                ["/press", "/newsroom", "/news", "/blog", "/about/press"],
                fetch_counter,
            )
            if press_soup:
                funding_data = _extract_funding(press_soup)
                if funding_data.get("total_funding"):
                    company_data["total_funding"] = funding_data["total_funding"]
                if funding_data.get("total_funding_usd"):
                    company_data["total_funding_usd"] = funding_data["total_funding_usd"]
                if funding_data.get("funding_stage") and not company_data.get("funding_stage"):
                    company_data["funding_stage"] = funding_data["funding_stage"]

        result.company_data = company_data
        result.contacts = contacts
        result.offices = offices
        result.success = True

        logger.info(
            "Website scrape complete: %d data fields, %d contacts, %d offices",
            len(company_data), len(contacts), len(offices),
        )

    except Exception as exc:
        logger.warning("Website scrape failed for %s: %s", website, exc, exc_info=True)
        result.error = str(exc)

    return result
