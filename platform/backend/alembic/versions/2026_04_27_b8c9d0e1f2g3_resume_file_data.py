"""Add ``file_data`` column to resumes for in-app preview.

Revision ID: b8c9d0e1f2g3
Revises: a7b8c9d0e1f2
Create Date: 2026-04-27

The Resume Score page needs to render the originally-uploaded PDF/DOCX
inline (iframe for PDF, download for DOCX). Pre-fix the upload handler
extracted text and discarded the bytes — the only persisted artifact
was ``text_content``. Result: no way to show the user the source-of-truth
file the scorer is looking at.

This migration adds a nullable ``file_data BYTEA`` column. Existing rows
stay NULL (they pre-date the persist hook); new uploads get the bytes
stored verbatim. The 5 MB upload cap (``MAX_FILE_SIZE``) bounds the
column size, so a typical user with 1-5 resumes stays well under
typical TOAST thresholds.

The column is loaded ``deferred=True`` on the ORM side
(see ``app/models/resume.py``) so list queries that return dozens of
resumes don't pull megabytes of bytes per row — only the dedicated
``GET /resume/{id}/file`` endpoint pays the cost.

Idempotent: ``IF NOT EXISTS`` semantics via the inspector check.
"""

import sqlalchemy as sa
from alembic import op


revision = "b8c9d0e1f2g3"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    if _column_exists("resumes", "file_data"):
        return
    op.add_column(
        "resumes",
        sa.Column("file_data", sa.LargeBinary(), nullable=True),
    )


def downgrade() -> None:
    if not _column_exists("resumes", "file_data"):
        return
    op.drop_column("resumes", "file_data")
