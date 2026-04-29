"""Pydantic schemas for the work-time window control plane.

Two surfaces:

  * Admin: read/write a user's window (``WorkWindowUpdate``), set a
    one-off ``override_until`` (``WorkWindowOverride``), approve or
    deny extension requests (``ExtensionDecision``).
  * User: read own state (``MyWorkWindowState``), submit a request
    (``ExtensionRequestCreate``).

All time-of-day inputs are validated through ``parse_hhmm_to_minute``
so a malformed ``"09:60"`` 422s at the schema layer instead of writing
a junk minute value to the DB.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.utils.work_window import parse_hhmm_to_minute, format_minute_ist


class WorkWindowUpdate(BaseModel):
    """Admin: PATCH a user's window. All fields optional — partial update."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    # Wire format is ``HH:MM`` (24-hour, IST). Parsed to minute-of-day
    # by the field validator. Stored as ``int`` on the model.
    start_ist: str | None = Field(default=None, description="HH:MM IST")
    end_ist: str | None = Field(default=None, description="HH:MM IST")

    @field_validator("start_ist", "end_ist")
    @classmethod
    def _validate_hhmm(cls, v: str | None) -> str | None:
        if v is None:
            return v
        # Raises ValueError → Pydantic surfaces a 422 with the helper's
        # message ("Hour 0..23, minute 0..59"). Exact same parser the
        # router uses to convert into the int column, so the schema
        # accepts iff the parser will succeed downstream.
        parse_hhmm_to_minute(v)
        return v


class WorkWindowOverride(BaseModel):
    """Admin: set a one-off override that lifts the lock until the
    given UTC instant. Pass ``None`` to clear an existing override.
    """

    model_config = ConfigDict(extra="forbid")

    override_until: datetime | None = Field(
        default=None,
        description="UTC instant; None clears any existing override.",
    )


class WorkWindowResponse(BaseModel):
    """Read shape for both admin and user endpoints."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    start_ist: str  # HH:MM
    end_ist: str  # HH:MM
    override_until: datetime | None
    # Convenience derived fields so the frontend doesn't reimplement
    # the IST conversion in two places. ``server_now_utc`` is included
    # so the lock-out screen can render "you can return at HH:MM (in
    # 47 min)" without trusting the client clock.
    within_window_now: bool
    server_now_utc: datetime


class ExtensionRequestCreate(BaseModel):
    """User: ``POST /work-window/me/extension-requests``."""

    model_config = ConfigDict(extra="forbid")

    # Bounded so an approval is a bounded decision.
    requested_minutes: int = Field(ge=15, le=240)
    # Free-form context for the admin reviewer. Empty string allowed —
    # not every "I need 20 more minutes" needs a paragraph.
    reason: str = Field(default="", max_length=500)


class ExtensionRequestOut(BaseModel):
    """Read shape for one row in the requests list."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    user_id: UUID
    user_name: str
    user_email: str
    requested_minutes: int
    reason: str
    status: Literal["pending", "approved", "denied"]
    requested_at: datetime
    decided_by_user_id: UUID | None
    decided_at: datetime | None
    decision_note: str
    approved_until: datetime | None


class ExtensionRequestListResponse(BaseModel):
    """Paginated list. Uses the canonical envelope shared with /jobs,
    /feedback, etc. so shared frontend pagers render correctly."""

    model_config = ConfigDict(extra="forbid")

    items: list[ExtensionRequestOut]
    total: int
    page: int
    page_size: int
    total_pages: int


class ExtensionDecision(BaseModel):
    """Admin: approve or deny a pending request."""

    model_config = ConfigDict(extra="forbid")

    decision: Literal["approved", "denied"]
    note: str = Field(default="", max_length=500)


# Re-export for code that wants symmetrical typing on the user-facing
# endpoint. Helper to avoid threading ``format_minute_ist`` through the
# router; the router calls this when serialising.
def to_response(
    *,
    enabled: bool,
    start_min: int,
    end_min: int,
    override_until: datetime | None,
    within_window_now: bool,
    server_now_utc: datetime,
) -> WorkWindowResponse:
    return WorkWindowResponse(
        enabled=enabled,
        start_ist=format_minute_ist(start_min),
        end_ist=format_minute_ist(end_min),
        override_until=override_until,
        within_window_now=within_window_now,
        server_now_utc=server_now_utc,
    )
