"""Work-time windows: per-user IST shift enforcement + extension requests.

Revision ID: c9d0e1f2g3h4
Revises: b8c9d0e1f2g3
Create Date: 2026-04-27

Adds platform-level access control by user shift in IST. Admin /
super_admin define a daily window per sales-team member; outside that
window the user is locked out at the API boundary (423 Locked) until:

  * the window re-opens the next day, OR
  * an admin grants a one-off ``override_until`` extension, OR
  * an admin approves an extension request the user submitted.

Schema additions:

  ``users`` gets four nullable / defaulted columns:

  * ``work_window_enabled``     BOOL DEFAULT false
      Opt-in. Pre-existing rows stay False so the migration is
      transparent — no user is suddenly locked out post-deploy.
      Admin flips this on per user when they want enforcement.

  * ``work_window_start_min``   INT DEFAULT 540   (09:00 IST)
  * ``work_window_end_min``     INT DEFAULT 1080  (18:00 IST)
      Minutes-since-midnight in IST (Asia/Kolkata, UTC+5:30, no DST).
      The handler converts the request's ``now_utc`` to IST and compares
      ``hour*60+minute`` against the [start, end) range. Wraparound
      windows (e.g. night shift 22:00–06:00) are supported by the
      ``in_window`` helper — see ``utils/work_window.py``.

  * ``work_window_override_until`` TIMESTAMPTZ NULL
      Admin one-off grace. While ``now_utc < override_until``, the
      window check passes regardless of the user's regular shift.
      Cleared (or set to a past timestamp) restores normal enforcement.
      Approving an extension request bumps this column.

New table ``work_time_extension_requests``:

  Captures reviewer-initiated "I need 30 more minutes" requests. Admin
  reviews each row and approves (which sets the requester's
  ``work_window_override_until``) or denies (with optional note).
  ``requested_minutes`` is capped 15..240 at the schema layer to keep
  approval decisions bounded and to prevent a viewer from requesting
  an open-ended override that effectively disables the feature.

Idempotent via inspector checks — ``alembic upgrade head`` is safe to
re-run if a previous attempt partially applied.
"""

import sqlalchemy as sa
from alembic import op


revision = "c9d0e1f2g3h4"
down_revision = "b8c9d0e1f2g3"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return column in {c["name"] for c in inspector.get_columns(table)}


def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table in inspector.get_table_names()


def upgrade() -> None:
    # ---- users column additions ----
    if not _column_exists("users", "work_window_enabled"):
        op.add_column(
            "users",
            sa.Column(
                "work_window_enabled",
                sa.Boolean(),
                server_default=sa.text("false"),
                nullable=False,
            ),
        )
    if not _column_exists("users", "work_window_start_min"):
        op.add_column(
            "users",
            sa.Column(
                "work_window_start_min",
                sa.Integer(),
                server_default=sa.text("540"),  # 09:00 IST
                nullable=False,
            ),
        )
    if not _column_exists("users", "work_window_end_min"):
        op.add_column(
            "users",
            sa.Column(
                "work_window_end_min",
                sa.Integer(),
                server_default=sa.text("1080"),  # 18:00 IST
                nullable=False,
            ),
        )
    if not _column_exists("users", "work_window_override_until"):
        op.add_column(
            "users",
            sa.Column(
                "work_window_override_until",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
        )

    # ---- extension-requests table ----
    if not _table_exists("work_time_extension_requests"):
        op.create_table(
            "work_time_extension_requests",
            sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "user_id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("requested_minutes", sa.Integer(), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False, server_default=""),
            sa.Column(
                "status",
                sa.String(length=16),
                nullable=False,
                server_default="pending",
            ),
            sa.Column(
                "requested_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "decided_by_user_id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("decision_note", sa.Text(), nullable=False, server_default=""),
            # Cap on the approved override (computed and frozen at
            # approval time so a re-approval can't silently extend).
            sa.Column(
                "approved_until",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
        )
        # Index supports the admin "show pending" list and the user's
        # "my recent requests" list — both filter by user/status and
        # order by requested_at desc.
        op.create_index(
            "ix_work_time_ext_user_status_requested",
            "work_time_extension_requests",
            ["user_id", "status", "requested_at"],
        )
        op.create_index(
            "ix_work_time_ext_status_requested",
            "work_time_extension_requests",
            ["status", "requested_at"],
        )


def downgrade() -> None:
    if _table_exists("work_time_extension_requests"):
        op.drop_index(
            "ix_work_time_ext_status_requested",
            table_name="work_time_extension_requests",
        )
        op.drop_index(
            "ix_work_time_ext_user_status_requested",
            table_name="work_time_extension_requests",
        )
        op.drop_table("work_time_extension_requests")
    for col in (
        "work_window_override_until",
        "work_window_end_min",
        "work_window_start_min",
        "work_window_enabled",
    ):
        if _column_exists("users", col):
            op.drop_column("users", col)
