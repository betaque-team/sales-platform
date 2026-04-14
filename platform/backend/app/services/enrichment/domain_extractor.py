"""Extract bare domain from a company website URL."""

from urllib.parse import urlparse


def extract_domain(website: str) -> str:
    """Parse a company website URL and return the bare domain.

    Examples:
        "https://www.canonical.com/careers" -> "canonical.com"
        "canonical.com" -> "canonical.com"
        "http://www.example.co.uk/" -> "example.co.uk"
        "" -> ""
    """
    if not website or not website.strip():
        return ""

    url = website.strip()

    # Add scheme if missing so urlparse can handle it
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
    except Exception:
        return ""

    if not hostname:
        return ""

    # Strip www. prefix
    if hostname.startswith("www."):
        hostname = hostname[4:]

    return hostname.lower()
