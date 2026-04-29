import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Boolean, DateTime, Text, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    avatar_url: Mapped[str] = mapped_column(String(500), default="")
    role: Mapped[str] = mapped_column(String(50), default="viewer")  # admin | reviewer | viewer
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    active_resume_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("resumes.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    password_reset_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_reset_expires: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # F247 regression fix: when a super_admin force-resets a user's
    # password (``POST /users/{id}/reset-password``), the user must be
    # made to change the temporary password on next login. Pre-fix, the
    # admin endpoint set the temp password but no flag was persisted, so
    # the login response had no way to tell the frontend "redirect to
    # the change-password screen". Defaults to ``False`` so existing
    # rows on prod don't suddenly get prompted; only the admin-reset
    # path flips it to ``True``, and a successful change-password call
    # flips it back to ``False``.
    must_change_password: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
    )
    # F257: per-user filter preferences for the Apply Routine's
    # "next jobs" picker. JSONB so the schema can evolve (new toggles,
    # sliders) without a migration per change. Default is an empty
    # dict — ``top-to-apply`` treats any missing key as
    # "don't filter on this", preserving the legacy behaviour for
    # users who haven't set anything yet.
    #
    # Documented shape (kept in sync with
    # ``app.schemas.routine.RoutinePreferences``):
    #   {
    #     "only_global_remote":     bool,
    #     "allowed_geographies":    list[str],
    #     "min_relevance_score":    int (0-100),
    #     "min_resume_score":       int (0-100),
    #     "allowed_role_clusters":  list[str],
    #     "extra_excluded_platforms": list[str]
    #   }
    routine_preferences: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        server_default="{}",
        nullable=False,
    )

    # ──────────────────────────────────────────────────────────────────
    # Work-time window enforcement (migration c9d0e1f2g3h4)
    #
    # Sales-team members can be restricted to a daily IST shift. Outside
    # the window the API rejects requests with 423 Locked. Admins are
    # always exempt; reviewers/viewers can request a one-off extension.
    # ──────────────────────────────────────────────────────────────────

    # Enforcement is opt-in per user — defaults False so the migration
    # is transparent and admins flip it on individually.
    work_window_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
    )
    # Minutes-since-midnight in IST (Asia/Kolkata, UTC+5:30, no DST).
    # Defaults form a 09:00–18:00 IST shift. Wraparound (start > end)
    # is supported by ``utils.work_window.is_within_window``.
    work_window_start_min: Mapped[int] = mapped_column(
        Integer,
        default=540,  # 09:00
        server_default="540",
        nullable=False,
    )
    work_window_end_min: Mapped[int] = mapped_column(
        Integer,
        default=1080,  # 18:00
        server_default="1080",
        nullable=False,
    )
    # Admin one-off "extend until" grace. Stored in UTC. While now_utc
    # < override_until, enforcement passes regardless of the regular
    # window. Approving a WorkTimeExtensionRequest bumps this column.
    work_window_override_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
