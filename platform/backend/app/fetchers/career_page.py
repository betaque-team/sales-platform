from __future__ import annotations

import hashlib
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class CareerPageFetcher:
    """Lightweight change-detection fetcher for arbitrary career page URLs.

    Unlike ATS fetchers this does not parse individual jobs. It fetches a page,
    hashes the response body, and reports whether the content has changed since
    the last check.
    """

    def __init__(self, client: Optional[httpx.Client] = None):
        self._client = client
        self._own_client = client is None

    def _get_client(self) -> httpx.Client:
        if self._client:
            return self._client
        self._created_client = httpx.Client(timeout=30, follow_redirects=True)
        return self._created_client

    def check(self, url: str, previous_hash: Optional[str] = None) -> dict:
        """Fetch a career page and return change-detection metadata.

        Returns a dict with:
            url          - the URL that was checked
            content_hash - first 16 chars of the SHA-256 hex digest
            changed      - True if content_hash differs from previous_hash
                           (always True when previous_hash is None)
            error        - error message string, or None on success
        """
        client = self._get_client()

        try:
            resp = client.get(url)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            return {
                "url": url,
                "content_hash": None,
                "changed": False,
                "error": f"HTTP {exc.response.status_code}",
            }
        except httpx.RequestError as exc:
            return {
                "url": url,
                "content_hash": None,
                "changed": False,
                "error": str(exc),
            }

        content_hash = hashlib.sha256(resp.content).hexdigest()[:16]

        if previous_hash is None:
            changed = True
        else:
            changed = content_hash != previous_hash

        return {
            "url": url,
            "content_hash": content_hash,
            "changed": changed,
            "error": None,
        }

    def __enter__(self):
        return self

    def __exit__(self, *args):
        if self._own_client and hasattr(self, "_created_client"):
            self._created_client.close()
