"""Fetch jobs from HN's monthly ``Ask HN: Who is hiring?`` thread.

Why this fetcher exists
-----------------------
The ``whoishiring`` user posts one "Who is hiring?" thread on the
first of every month. Each top-level comment is a job posting by a
different company. Historically 500-800 postings / month, skewed
heavily toward infra / dev-tools / security hiring — one of the
highest-signal free sources on the internet and not covered by any
of our 16 existing fetchers.

Integration model
-----------------
Follows the existing aggregator pattern (``remoteok``, ``remotive``,
``weworkremotely``): slug is always ``__all__``; each emitted job
dict carries its own ``company_name`` + ``company_slug`` so
``scan_task``'s aggregator branch can resolve a distinct ``Company``
row per unique hirer. See
``scan_task.py::_AGGREGATOR_PLATFORMS`` — this fetcher adds
``"hackernews"`` to that set.

Rate-limit protection
---------------------
Our default cadence is every 30 min (``scan_all_platforms``). A
naive re-fetch would hit HN Firebase ~500 times per 30 min — rude
to a free API that's doing us a favour. We short-circuit using the
thread's ``descendants`` count (HN's own comment-count field):

  1. Fetch the thread head (1 request).
  2. Compare ``descendants`` against a Redis marker
     (``hn:whoishiring:{thread_id}:descendants``).
  3. If unchanged, return ``[]`` immediately.
  4. If changed (or no marker yet), fetch every top-level comment.

Net effect: ~1 request per 30 min during the quiet weeks of the
month, ~500 requests on the 1st–3rd when the thread is filling up.

Parse strategy
--------------
HN comments are free-form HTML in a convention that's about 60-70%
regular. We parse the FIRST LINE on a best-effort basis — most
posters follow one of:

    Company | Role(s) | Location | [REMOTE|ONSITE|HYBRID] | url
    Company (YC Wxx) | Role | Location | ...
    Company - Role - Location - ...

Comments that don't yield a (company, url) pair get dropped with a
log line — we'd rather skip 30% than emit junk rows into ``Job``.
Downstream relevance scoring (role cluster match) handles the fact
that even a well-parsed HN comment might not be infra/security.
"""
from __future__ import annotations

import html as html_module
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from app.fetchers.base import BaseFetcher

logger = logging.getLogger(__name__)

# Public HN APIs — no auth, generous rate limits (~100 req/s).
_ALGOLIA_SEARCH_URL = "https://hn.algolia.com/api/v1/search_by_date"
_FIREBASE_ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{item_id}.json"

# Cap comment fetches per run so a misbehaving API can't wedge a
# scan_task run. Real threads max out around ~900 top-level comments.
_MAX_KIDS_PER_RUN = 1000

# Algolia search returns newest stories by `whoishiring`. We want
# the most recent whose title starts with "Ask HN: Who is hiring?"
# — not "Freelancer?" (different monthly thread) and not
# "Who wants to be hired?" (inverse thread).
_WHOISHIRING_TITLE_RE = re.compile(r"(?i)who\s+is\s+hiring")

# First http(s) URL in a comment — used as the apply link.
_URL_RE = re.compile(r"https?://[^\s<>\"'\]\)]+")

# Remote-scope heuristics that take precedence over the base class's
# generic detector. Matches the HN conventions (ALL CAPS | REMOTE ONLY
# | Remote (US), etc.).
_REMOTE_MARKERS = {
    "REMOTE", "Remote", "remote",
    "ONSITE", "Onsite", "on-site", "On-site",
    "HYBRID", "Hybrid", "hybrid",
}


class HackerNewsFetcher(BaseFetcher):
    """Fetcher for ``Ask HN: Who is hiring?`` monthly threads."""

    PLATFORM = "hackernews"

    # Public attribute for testability — tests can inject a fake
    # Redis / in-memory object to assert the descendants-skip path
    # without a live broker.
    def __init__(self, client: httpx.Client | None = None, redis_client: Any = None):
        super().__init__(client=client)
        self._redis = redis_client

    def _get_redis(self) -> Any:
        """Lazy-get a Redis client for the descendants cache.

        Returns ``None`` if Redis isn't configured — in that case we
        always fetch the full thread (correct but wasteful). A
        broken cache must never break the fetcher.
        """
        if self._redis is not None:
            return self._redis
        try:
            import redis  # type: ignore
            url = os.environ.get("REDIS_URL") or "redis://localhost:6379/0"
            self._redis = redis.Redis.from_url(url, socket_timeout=2)
            # Don't verify connectivity here — the operations below all
            # .get/.set with try/except so a dead Redis degrades to
            # "no cache", not "fetcher crashes".
        except Exception as exc:
            logger.warning("HN fetcher could not init Redis: %s", exc)
            self._redis = None
        return self._redis

    # ── Thread discovery ─────────────────────────────────────────────

    def _find_latest_thread(self, client: httpx.Client) -> dict | None:
        """Locate the most recent ``Who is hiring?`` thread by
        ``whoishiring`` user. Returns a dict with the ``id``,
        ``descendants``, ``created_at_iso`` and ``title`` — or
        ``None`` if none can be found (e.g. Algolia downtime).
        """
        try:
            resp = client.get(
                _ALGOLIA_SEARCH_URL,
                params={
                    "tags": "author_whoishiring",
                    "hitsPerPage": 10,  # cheap; we only need 1 good hit
                },
                timeout=15,
            )
            resp.raise_for_status()
            hits = resp.json().get("hits") or []
        except Exception as exc:
            logger.warning("HN Algolia search failed: %s", exc)
            return None

        # Filter to actual "Who is hiring" stories, sort by created_at
        # descending (Algolia already does this, but be defensive).
        candidates = []
        for hit in hits:
            title = hit.get("title") or ""
            if not _WHOISHIRING_TITLE_RE.search(title):
                continue
            # Some `whoishiring` posts are comments, not stories. We
            # only want stories (the monthly thread head).
            if "story" not in (hit.get("_tags") or []):
                continue
            candidates.append(hit)
        if not candidates:
            logger.info("HN Algolia returned no whoishiring stories")
            return None

        candidates.sort(key=lambda h: h.get("created_at_i") or 0, reverse=True)
        top = candidates[0]
        thread_id = top.get("objectID") or top.get("story_id")
        if not thread_id:
            return None

        # Algolia doesn't surface ``descendants`` (comment count) —
        # refetch the thread head from Firebase for the canonical
        # count + kids list.
        try:
            head_resp = client.get(
                _FIREBASE_ITEM_URL.format(item_id=thread_id), timeout=15
            )
            head_resp.raise_for_status()
            head = head_resp.json()
        except Exception as exc:
            logger.warning("HN thread head fetch failed for %s: %s", thread_id, exc)
            return None

        return {
            "id": str(thread_id),
            "title": head.get("title") or top.get("title") or "",
            "descendants": int(head.get("descendants") or 0),
            "kids": list(head.get("kids") or []),
            "created_at_iso": top.get("created_at"),
            "time_epoch": int(head.get("time") or 0),
        }

    # ── Rate-limit guard ─────────────────────────────────────────────

    def _should_skip(self, thread: dict) -> bool:
        """Return True if the thread's ``descendants`` count matches
        a previously-cached value — no new comments, nothing to do.

        Cache key: ``hn:whoishiring:{thread_id}:descendants`` ·
        TTL: 45 days (threads stop gaining comments after ~30 days).
        """
        r = self._get_redis()
        if r is None:
            return False  # No cache → always do the full fetch
        key = f"hn:whoishiring:{thread['id']}:descendants"
        try:
            cached = r.get(key)
        except Exception as exc:
            logger.warning("HN Redis get failed (%s) — falling through", exc)
            return False
        if cached is None:
            return False
        try:
            cached_val = int(cached)
        except (TypeError, ValueError):
            return False
        return cached_val == thread["descendants"]

    def _remember_descendants(self, thread: dict) -> None:
        r = self._get_redis()
        if r is None:
            return
        key = f"hn:whoishiring:{thread['id']}:descendants"
        try:
            r.set(key, thread["descendants"], ex=45 * 24 * 3600)
        except Exception as exc:
            logger.warning("HN Redis set failed (%s) — cache will miss next run", exc)

    # ── Comment fetch + parse ────────────────────────────────────────

    def _fetch_comment(self, client: httpx.Client, comment_id: int) -> dict | None:
        try:
            r = client.get(_FIREBASE_ITEM_URL.format(item_id=comment_id), timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            # Individual comment failures are normal (deleted, etc.) —
            # log quietly and move on.
            logger.debug("HN comment %s fetch failed: %s", comment_id, exc)
            return None

    @staticmethod
    def _strip_html(text: str) -> str:
        """Crude HN comment HTML → plain text.

        HN uses ``<p>`` to separate paragraphs and ``<a href="...">...</a>``
        for links. We convert ``<p>`` to newlines, strip other tags, and
        unescape HTML entities. Not bulletproof but sufficient for
        parsing the header line which is what we care about.
        """
        if not text:
            return ""
        # Paragraph → newline (HN's convention).
        s = re.sub(r"<p\s*/?>", "\n", text, flags=re.IGNORECASE)
        s = re.sub(r"</?p>", "\n", s, flags=re.IGNORECASE)
        # Links: preserve the URL (href) because that's often the apply
        # link — the anchor text is often just "apply" or the URL itself.
        # We replace `<a href="X">Y</a>` with `X` so the URL regex below
        # can still find it. Anchor text loss is acceptable — the header
        # line's semantic information is company / title / location, not
        # link labels.
        s = re.sub(r'<a\s+[^>]*href="([^"]*)"[^>]*>([^<]*)</a>', r"\1", s, flags=re.IGNORECASE)
        # Strip any remaining tags.
        s = re.sub(r"<[^>]+>", "", s)
        # Entities.
        s = html_module.unescape(s)
        # Normalise whitespace but keep line breaks.
        s = re.sub(r"[ \t]+", " ", s)
        return s.strip()

    @classmethod
    def _parse_header(cls, text: str) -> dict:
        """Best-effort structured parse of an HN job comment.

        Returns a dict with any subset of: ``company``, ``title``,
        ``location``, ``remote_scope``, ``url``. Missing keys are
        left out — caller decides what's "enough" to keep.
        """
        if not text:
            return {}
        # Work with the first 3 lines — most postings cram all their
        # metadata into line 1, occasionally spilling to 2-3.
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if not lines:
            return {}
        header = lines[0]

        out: dict[str, str] = {}

        # URL — prefer the first URL that isn't a tracking junk link
        # (mailto:, hn self-link). First valid http(s) URL anywhere in
        # the comment body.
        url_match = _URL_RE.search(text)
        if url_match:
            out["url"] = url_match.group(0).rstrip(".,;)\"'")

        # Split header on pipes or em-dashes. We try pipes first because
        # they're by far the most common delimiter.
        parts: list[str]
        if "|" in header:
            parts = [p.strip() for p in header.split("|") if p.strip()]
        elif " — " in header:
            parts = [p.strip() for p in header.split(" — ") if p.strip()]
        elif " - " in header:
            # " - " is ambiguous: "Company - Role" vs "e.g. Acme - we're
            # hiring!" — use it only when there's no pipe.
            parts = [p.strip() for p in header.split(" - ") if p.strip()]
        else:
            # No delimiter — treat the whole line as a company name; we
            # keep the comment but with only a company tag.
            parts = [header]

        if parts:
            # Company is nearly always the first segment. Strip the
            # common "(YC Wxx)" / "(yc s21)" batch suffix for cleaner
            # Company rows — the full raw header is preserved in raw_json.
            company_raw = parts[0]
            company_clean = re.sub(
                r"\s*\((?:yc|YC)\s+[wsWS]?\d+\)\s*$",
                "",
                company_raw,
            ).strip()
            out["company"] = company_clean or company_raw

        # Try to pick out the title. Heuristic: the part whose lowercase
        # text contains engineering-ish keywords OR the 2nd segment if
        # no better candidate found and the 2nd segment isn't obviously
        # a location.
        role_keywords = (
            "engineer", "developer", "sre", "devops", "security",
            "infrastructure", "platform", "staff", "senior", "lead",
            "principal", "architect", "manager", "director", "scientist",
            "analyst", "designer", "product", "full-stack", "fullstack",
            "frontend", "backend", "data", "ml", "machine learning",
            "ai ", " ai", "research", "ops", "cloud", "kubernetes",
            "multiple roles", "multiple positions", "multiple",
            "various roles",
        )
        title_candidate = None
        for p in parts[1:]:  # skip company
            pl = p.lower()
            if any(kw in pl for kw in role_keywords):
                title_candidate = p
                break
        if not title_candidate and len(parts) >= 2:
            # Fall back to 2nd segment if it doesn't look like a pure
            # location or remote marker.
            second = parts[1]
            if second.upper() not in _REMOTE_MARKERS and not _looks_like_location(second):
                title_candidate = second
        if title_candidate:
            out["title"] = title_candidate

        # Location: first segment that looks like a place OR the remote
        # marker if explicit.
        remote_scope = None
        location_candidate = None
        for p in parts[1:]:
            # Explicit remote-marker → record scope and keep scanning.
            if p.upper() in _REMOTE_MARKERS or p.strip().lower() in ("remote", "onsite", "on-site", "hybrid"):
                up = p.upper()
                if "REMOTE" in up:
                    remote_scope = remote_scope or "remote"
                continue
            # `Remote (US only)` / `Remote - EU` / `Remote US` — infer.
            if "remote" in p.lower():
                remote_scope = remote_scope or "remote"
                # Also useful as location.
                location_candidate = location_candidate or p
                continue
            if _looks_like_location(p):
                location_candidate = location_candidate or p
        if location_candidate:
            out["location"] = location_candidate
        if remote_scope:
            out["remote_scope"] = remote_scope
        # Worldwide check on the full header — "work from anywhere",
        # "worldwide", etc.
        worldwide = cls._detect_remote_scope(header, text[:400])
        if worldwide == "worldwide":
            out["remote_scope"] = "worldwide"

        return out

    # ── Fetch entry point ────────────────────────────────────────────

    def fetch(self, slug: str) -> list[dict]:
        """Fetch + parse the latest Who-is-hiring thread.

        ``slug`` is ignored — this is an aggregator fetcher and the
        convention is to register a single board with slug
        ``__all__``. Returning ``[]`` is always safe: either no new
        comments since last run, or an upstream error we've logged.
        """
        client = self._get_client()
        thread = self._find_latest_thread(client)
        if not thread:
            logger.info("HN whoishiring: no thread found")
            return []

        if self._should_skip(thread):
            logger.info(
                "HN whoishiring: thread %s unchanged (descendants=%d) — skip",
                thread["id"], thread["descendants"],
            )
            return []

        kids = thread["kids"][:_MAX_KIDS_PER_RUN]
        logger.info(
            "HN whoishiring: fetching %d comments from thread %s (title=%r)",
            len(kids), thread["id"], thread["title"][:60],
        )

        jobs: list[dict] = []
        skipped_parse = 0
        for cid in kids:
            comment = self._fetch_comment(client, cid)
            if not comment or comment.get("deleted") or comment.get("dead"):
                continue
            plain = self._strip_html(comment.get("text") or "")
            parsed = self._parse_header(plain)
            # Minimum viable record: a company name and a URL. Without a
            # URL we can't route a candidate to an apply page, and
            # without a company we can't build a Company row. Drop the
            # comment rather than emit a malformed job.
            if not parsed.get("company") or not parsed.get("url"):
                skipped_parse += 1
                continue
            normalized = self._normalize(comment, parsed, thread)
            if normalized:
                jobs.append(normalized)

        logger.info(
            "HN whoishiring: thread %s → %d jobs (skipped %d unparseable of %d)",
            thread["id"], len(jobs), skipped_parse, len(kids),
        )
        # Only update the cache after a successful full fetch so a
        # mid-run crash doesn't poison the "nothing to do" short-circuit.
        self._remember_descendants(thread)
        return jobs

    # Mandatory override of `_normalize` since the base flags it
    # `NotImplementedError`. Signature extended with the parsed dict
    # and thread metadata so the caller can pass already-extracted
    # fields without re-parsing.
    def _normalize(self, raw: dict, parsed: dict | None = None, thread: dict | None = None) -> dict:  # type: ignore[override]
        # Called with just `raw` by the base class's `fetch_one` if
        # we ever implement single-comment lookup. Bail gracefully —
        # HN job links don't have a natural single-item endpoint so
        # `fetch_one` doesn't fit; return empty dict.
        if parsed is None or thread is None:
            return {}

        company_name = parsed["company"]
        # Slug for synthetic Company rows. scan_task's aggregator
        # branch regenerates the slug itself — this copy just keeps
        # the dict self-describing for logging / debugging.
        company_slug = re.sub(
            r"[^a-z0-9-]", "",
            company_name.lower().replace(" ", "-"),
        )[:100] or "unknown-hn-company"

        posted_at = ""
        time_epoch = raw.get("time")
        if isinstance(time_epoch, (int, float)) and time_epoch > 0:
            posted_at = datetime.fromtimestamp(time_epoch, tz=timezone.utc).isoformat()

        comment_id = str(raw.get("id") or "")
        # external_id lives forever in `Job.external_id` so the
        # "hn-" prefix both namespaces the id and makes join debug
        # obvious ("where did this row come from?"). Also matches the
        # pattern RemoteOK uses ("rok-<id>").
        external_id = f"hn-{comment_id}"

        # Direct HN comment URL — useful as a fallback if `parsed["url"]`
        # happens to be a dead link. We still prefer the company link
        # for Job.url so clicking it goes to the actual apply page,
        # not the HN thread.
        hn_permalink = f"https://news.ycombinator.com/item?id={comment_id}"

        return {
            "external_id": external_id,
            "company_slug": company_slug,
            "company_name": company_name,
            "title": parsed.get("title") or "Multiple roles",
            "url": parsed["url"],
            "platform": self.PLATFORM,
            "location_raw": parsed.get("location", ""),
            "remote_scope": parsed.get("remote_scope", ""),
            "department": "",
            "employment_type": "",
            "salary_range": "",
            "posted_at": posted_at,
            # Surface HN thread provenance — useful for auditability
            # and for the admin UI "where did this job come from?"
            # drawer.
            "raw_json": {
                "hn_comment_id": comment_id,
                "hn_thread_id": thread["id"],
                "hn_thread_title": thread.get("title"),
                "hn_permalink": hn_permalink,
                "hn_by": raw.get("by"),
                "company_name": company_name,
                "parsed_header": parsed,
            },
        }


def _looks_like_location(s: str) -> bool:
    """Fuzzy location detector for the header parser.

    Heuristic — we don't need perfection, just enough to keep
    "San Francisco" out of the title slot. Returns True if the
    segment looks like a geographic place name.
    """
    if not s:
        return False
    low = s.lower()
    if "remote" in low:
        return True
    # Common city/country tokens — kept deliberately short.
    markers = (
        "san francisco", "sf ", "new york", "nyc", "ny,", "boston",
        "chicago", "austin", "seattle", "la,", "los angeles", "denver",
        "london", "berlin", "paris", "dublin", "amsterdam", "munich",
        "singapore", "sydney", "toronto", "vancouver", "montreal",
        "mumbai", "bangalore", "bengaluru", "delhi", "hyderabad",
        "tel aviv", "warsaw", "prague", "zurich", "barcelona", "madrid",
        "usa", "u.s.", "us,", "canada", "uk,", "uk)", "india",
        "brazil", "israel", "japan", "germany",
        # Country-state codes: CA, NY, WA, TX, MA, CO, IL, etc. — match
        # when they appear as ``, XX`` or `XX,` (after or before a
        # comma); skip to avoid matching "Staff" etc.
    )
    if any(m in low for m in markers):
        return True
    # State / country code in ``, XX`` form — common in "Austin, TX".
    if re.search(r",\s*[A-Z]{2}\b", s):
        return True
    return False
