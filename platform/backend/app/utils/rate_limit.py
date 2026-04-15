"""Lightweight in-memory rate limiter for the login endpoint.

Regression finding 24: /auth/login had no rate limiting, lockout, or
CAPTCHA — 25 wrong-password attempts were all accepted, enabling online
credential-stuffing. This module provides a per-key sliding-window
counter that tracks failed login attempts and blocks further attempts
for the remainder of the window once a threshold is exceeded.

Backed by a process-local dict with an `asyncio.Lock`. That is enough
for the current deployment (single backend container in docker-compose).
If the backend is ever scaled horizontally, switch the implementation
to a Redis-backed counter — Redis is already in the stack for Celery,
and the only change needed is in this file. The public API
(`is_limited`, `record_failure`, `record_success`) stays the same.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field


# Tunables. 5 failures in 15 minutes → cooled down for the rest of the
# 15-minute window. Password-reset flows unlock the same key immediately
# (via `record_success`) so a legitimate user who forgot their password
# isn't locked out after they successfully reset it.
MAX_FAILURES = 5
WINDOW_SECONDS = 15 * 60


@dataclass
class _Entry:
    timestamps: list[float] = field(default_factory=list)


class LoginRateLimiter:
    """Per-key failure counter with a sliding window."""

    def __init__(self, max_failures: int = MAX_FAILURES, window_seconds: int = WINDOW_SECONDS):
        self._max = max_failures
        self._window = window_seconds
        self._data: dict[str, _Entry] = {}
        self._lock = asyncio.Lock()

    def _prune(self, entry: _Entry, now: float) -> None:
        cutoff = now - self._window
        entry.timestamps[:] = [t for t in entry.timestamps if t > cutoff]

    async def is_limited(self, key: str) -> tuple[bool, int]:
        """Return (limited, retry_after_seconds)."""
        now = time.monotonic()
        async with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return False, 0
            self._prune(entry, now)
            if len(entry.timestamps) < self._max:
                return False, 0
            oldest = entry.timestamps[0]
            retry_after = max(1, int(oldest + self._window - now))
            return True, retry_after

    async def record_failure(self, key: str) -> None:
        now = time.monotonic()
        async with self._lock:
            entry = self._data.setdefault(key, _Entry())
            self._prune(entry, now)
            entry.timestamps.append(now)

    async def record_success(self, key: str) -> None:
        """Clear a key after a successful auth (or deliberate reset)."""
        async with self._lock:
            self._data.pop(key, None)


# Module-level singleton — import and share across requests.
login_limiter = LoginRateLimiter()
