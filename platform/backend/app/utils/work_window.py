"""Helpers for the per-user IST work-time window.

The window is stored on ``User`` as a [start_min, end_min) range in
minutes-since-midnight IST. ``is_within_window`` answers the only
question the enforcement layer cares about: given UTC ``now`` and a
user's window config, may the user use the platform right now?

IST is UTC+5:30 with no daylight-savings, so the conversion is a fixed
offset — no zoneinfo lookup needed. Keeps this module pure (no
``zoneinfo`` import = works on slim images and Alpine without the
``tzdata`` package).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.user import User

IST_OFFSET = timedelta(hours=5, minutes=30)
DAY_MINUTES = 24 * 60


def utc_to_ist_minute(now_utc: datetime) -> int:
    """Convert UTC ``datetime`` to IST minute-of-day (0..1439).

    Timezone-naive inputs are treated as UTC for safety — this matches
    the rest of the codebase's "naive == UTC" convention used in unit
    tests.
    """
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    ist = now_utc.astimezone(timezone.utc) + IST_OFFSET
    return ist.hour * 60 + ist.minute


def is_within_window(
    minute_of_day_ist: int, start_min: int, end_min: int
) -> bool:
    """Inclusive-start, exclusive-end membership test.

    Supports wraparound (e.g. night shift 22:00–06:00 → start=1320,
    end=360): when ``start > end`` we accept ``minute >= start`` OR
    ``minute < end``. ``start == end`` is treated as "always closed"
    so a misconfigured zero-length window doesn't accidentally allow
    24/7 access.
    """
    start_min %= DAY_MINUTES
    end_min %= DAY_MINUTES
    if start_min == end_min:
        return False
    if start_min < end_min:
        return start_min <= minute_of_day_ist < end_min
    # Wraparound
    return minute_of_day_ist >= start_min or minute_of_day_ist < end_min


def user_can_access_now(user: User, now_utc: datetime | None = None) -> bool:
    """Final yes/no for the enforcement layer.

    Order of escape hatches (any one passing returns True):

      1. ``work_window_enabled is False`` — feature off for this user.
      2. Active admin override (``override_until > now_utc``).
      3. Current IST minute falls inside the configured window.

    Admin / super_admin role short-circuit happens at the call site
    (``deps.get_current_user``) — this helper is role-agnostic so it
    can be reused by Celery tasks that don't have a request context.
    """
    if not user.work_window_enabled:
        return True
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    if user.work_window_override_until is not None:
        # Both sides timezone-aware; the column is TIMESTAMPTZ so the
        # ORM hands back an aware datetime. Defensive coercion in case
        # a sync session ever inserts a naive value.
        ou = user.work_window_override_until
        if ou.tzinfo is None:
            ou = ou.replace(tzinfo=timezone.utc)
        if ou > now_utc:
            return True

    minute = utc_to_ist_minute(now_utc)
    return is_within_window(
        minute, user.work_window_start_min, user.work_window_end_min
    )


def format_minute_ist(minute_of_day: int) -> str:
    """Render minute-of-day as ``HH:MM`` for the API response.

    Used by both the user-facing "your window is 09:00–18:00 IST" hint
    and the admin panel form. Centralised so the wire format stays
    consistent.
    """
    minute_of_day %= DAY_MINUTES
    return f"{minute_of_day // 60:02d}:{minute_of_day % 60:02d}"


def parse_hhmm_to_minute(value: str) -> int:
    """Inverse of ``format_minute_ist``. Raises ValueError on bad input.

    Accepts ``HH:MM`` 24-hour. Schema validators call this so a bad
    string 422s at parse time instead of writing junk to the DB.
    """
    parts = value.strip().split(":")
    if len(parts) != 2:
        raise ValueError("Expected HH:MM")
    h, m = int(parts[0]), int(parts[1])
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError("Hour 0..23, minute 0..59")
    return h * 60 + m
