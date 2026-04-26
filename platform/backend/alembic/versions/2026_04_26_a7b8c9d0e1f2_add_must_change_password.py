"""Add ``must_change_password`` flag to users table.

Revision ID: a7b8c9d0e1f2
Revises: z6u7v8w9x0y1
Create Date: 2026-04-26

F247 regression fix. The ``POST /api/v1/users/{id}/reset-password``
super-admin endpoint sets a temporary password for the target user,
but pre-fix had no way to mark the row as "the user must change this
on next login". Result: the admin shares the temp password, the user
logs in successfully, and nothing prompts them to rotate it — leaving
a deterministic credential in circulation indefinitely.

This migration adds a single boolean column ``must_change_password``,
defaulting to ``false`` for every existing row (so no currently
logged-in user is suddenly prompted on their next page load). The
admin-reset handler sets it to ``true``; the change-password handler
clears it back to ``false`` once the user picks a new password.

Idempotent: ``IF NOT EXISTS`` semantics via the inspector check, so
re-running ``alembic upgrade head`` after the column already exists
is a no-op (matches the pattern used by recent vault + insights
migrations).
"""

import sqlalchemy as sa
from alembic import op


revision = "a7b8c9d0e1f2"
down_revision = "z6u7v8w9x0y1"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    if _column_exists("users", "must_change_password"):
        return
    op.add_column(
        "users",
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    if not _column_exists("users", "must_change_password"):
        return
    op.drop_column("users", "must_change_password")
