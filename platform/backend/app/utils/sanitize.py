"""HTML sanitization for untrusted third-party content (e.g. ATS job postings).

We receive job descriptions as HTML strings from Greenhouse, Lever, Ashby,
etc. That HTML is then rendered by the frontend via `dangerouslySetInnerHTML`.
If we don't strip script tags / event handlers / javascript: URLs, a job
poster on any ATS could execute stored XSS on our origin.

This module uses BeautifulSoup (already a dependency) to walk the DOM and
remove dangerous elements/attributes with a conservative allowlist.
"""

from __future__ import annotations

from bs4 import BeautifulSoup


# Tags that are safe for plain-prose job descriptions. Everything else is
# unwrapped (children kept, tag stripped) unless it's in the hard-drop set.
_ALLOWED_TAGS = {
    "a", "b", "blockquote", "br", "code", "div", "em", "h1", "h2", "h3",
    "h4", "h5", "h6", "hr", "i", "li", "ol", "p", "pre", "span", "strong",
    "sub", "sup", "table", "tbody", "td", "th", "thead", "tr", "u", "ul",
}

# Tags that are unconditionally removed along with all their children.
# These never belong in a plain job posting.
_HARD_DROP_TAGS = {
    "script", "style", "iframe", "embed", "object", "applet", "link",
    "meta", "form", "input", "button", "textarea", "select", "option",
    "base", "frame", "frameset", "noscript", "template", "svg",
}

# Attributes that are safe to keep on any element.
_ALLOWED_ATTRS = {"href", "title", "alt", "src", "class"}

# URL schemes allowed on href/src. Anything else (javascript:, data:, vbscript:,
# file:, about:, …) gets stripped.
_SAFE_SCHEMES = ("http://", "https://", "mailto:", "/", "#")


def _is_safe_url(value: str) -> bool:
    if not value:
        return True
    stripped = value.strip().lower()
    return stripped.startswith(_SAFE_SCHEMES)


def strip_html_tags(raw: str | None) -> str:
    """Return plain-text version of `raw` with all HTML tags + event attrs stripped.

    Use this for fields rendered AS TEXT (not HTML) — e.g. feedback ticket
    titles, comment bodies, ticket descriptions — where any markup is noise
    and a stored `<img onerror=…>` would become XSS only if the frontend
    ever `dangerouslySetInnerHTML`'d it. Normalising to plain text at the
    API boundary removes that possibility regardless of the renderer.

    Hard-drop tags (script, style, …) are removed WITH their subtree so
    their text content doesn't survive. Every remaining tag is unwrapped,
    keeping its visible text. Returns an empty string for None/empty input.
    """
    if not raw:
        return ""
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup.find_all(list(_HARD_DROP_TAGS)):
        tag.decompose()
    return soup.get_text(separator=" ", strip=False)


def sanitize_html(raw: str) -> str:
    """Return a safe subset of the given HTML.

    Strategy:
    - Drop hard-drop tags (script, style, iframe, etc.) along with their children.
    - Unwrap anything not in the allowlist (keep text, drop the tag).
    - On surviving tags, drop any attribute that's not allowlisted, plus
      any `href` / `src` whose scheme is not safe.
    - Drop every `on*` attribute (onclick, onload, onerror, …).
    """
    if not raw:
        return ""

    soup = BeautifulSoup(raw, "html.parser")

    # Hard drop: script/style/iframe/etc. plus their subtree.
    for tag in soup.find_all(list(_HARD_DROP_TAGS)):
        tag.decompose()

    for tag in list(soup.find_all(True)):
        name = (tag.name or "").lower()

        # Unwrap unknown tags — keep their text content.
        if name not in _ALLOWED_TAGS:
            tag.unwrap()
            continue

        # Filter attributes.
        for attr in list(tag.attrs.keys()):
            attr_lower = attr.lower()
            # Any event handler → drop.
            if attr_lower.startswith("on"):
                del tag.attrs[attr]
                continue
            if attr_lower not in _ALLOWED_ATTRS:
                del tag.attrs[attr]
                continue
            # href / src must use a safe scheme.
            if attr_lower in ("href", "src"):
                val = tag.attrs[attr]
                if isinstance(val, list):
                    val = " ".join(val)
                if not _is_safe_url(str(val)):
                    del tag.attrs[attr]

        # Force external links to open safely.
        if name == "a" and tag.get("href"):
            tag.attrs["rel"] = "noopener noreferrer nofollow"
            tag.attrs["target"] = "_blank"

    return str(soup)
