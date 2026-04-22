"""Add admin-only profiles + profile_documents tables.

Revision ID: x4s5t6u7v8w9
Revises: w3r4s5t6u7v8
Create Date: 2026-04-19

New feature: admin/superadmin-only KYC document vault for storing
personal / HR documents tied to a person-profile (name + DOB + email).
Used for onboarding / offboarding / compliance workflows.

Schema design decisions:

* **Two tables.** ``profiles`` holds structured fields (name, dob,
  email, father_name, UAN, PF, notes). ``profile_documents`` holds
  uploaded files (Aadhaar, PAN, marksheets, etc.) as 1→N.
* **Email UNIQUE.** One profile per person. Allows upsert-by-email
  on bulk imports.
* **Soft delete.** ``profiles.archived_at`` instead of hard DELETE —
  preserves audit trail + complies with retention obligations.
  Same pattern on ``profile_documents``. API filters archived rows
  by default; a dedicated "archived" view requires explicit query.
* **``doc_type`` is a String(40)`` not PG ENUM.** Follows the
  existing ``Job.status`` / ``Application.status`` convention. New
  doc types (e.g. passport) are app-level constant changes, not
  migrations.
* **``storage_path`` is NULLABLE.** Text fields like "UAN number"
  could be stored as a doc-row with no file (if we ever want a
  unified history view). V1 keeps UAN/PF on the profile row itself
  but the NULL storage_path leaves the door open.
* **``uploaded_by_user_id`` FK RESTRICT.** A user deletion must NOT
  orphan or cascade-delete forensic records. Matches ``AuditLog``
  convention.
* **No FK to ``companies`` / ``jobs``.** This vault is person-
  scoped, not job-scoped. A profile represents an employee /
  contractor, not a job applicant in the sales pipeline sense.

Regulatory notes (DPDP Act 2023 + GDPR):
  * Access audit lands in existing ``audit_logs`` table via
    ``log_action`` calls in the handlers.
  * At-rest encryption is NOT implemented in this migration — files
    are stored with filesystem 0600 permissions. Phase 2 can add
    AES envelope encryption without a schema change (encrypted
    blobs still fit in the same ``storage_path`` file).
  * No automatic purge on ``archived_at`` — retention policy is an
    ops decision, not a migration default.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision = "x4s5t6u7v8w9"
down_revision = "w3r4s5t6u7v8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── profiles ──
    op.create_table(
        "profiles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        # Required identity fields. Email UNIQUE so bulk import can
        # upsert-by-email without creating dupes.
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("dob", sa.Date(), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        # Structured fields that don't get a file upload. father_name
        # is a string because only the NAME is here (father_aadhaar
        # and father_pan are docs). UAN / PF numbers are 12-digit
        # strings commonly written with spaces; storing as String not
        # Integer preserves formatting.
        sa.Column("father_name", sa.String(length=200), nullable=True),
        sa.Column("uan_number", sa.String(length=40), nullable=True),
        sa.Column("pf_number", sa.String(length=40), nullable=True),
        # Free-text notes the admin can attach (e.g. "joined via
        # Acme acquisition; docs from HR onboarding packet").
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        # Who created the profile — RESTRICT so user-delete doesn't
        # orphan the audit trail.
        sa.Column(
            "created_by_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        # Soft delete — see module docstring.
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("email", name="uq_profiles_email"),
    )
    # Case-insensitive email lookup — most admin searches will be by
    # email, and the unique constraint above is case-sensitive (Postgres
    # CITEXT not used to keep portability). A lower() functional index
    # makes the search fast without changing the column type.
    op.create_index(
        "ix_profiles_email_lower",
        "profiles",
        [sa.text("lower(email)")],
        unique=False,
    )
    op.create_index("ix_profiles_name", "profiles", ["name"])

    # ── profile_documents ──
    op.create_table(
        "profile_documents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "profile_id",
            UUID(as_uuid=True),
            sa.ForeignKey("profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # `doc_type` is the canonical category (aadhaar | pan |
        # 12th_marksheet | college_marksheet | cancelled_cheque |
        # bank_statement | passbook | epfo_nominee_proof |
        # father_aadhaar | father_pan | address_proof | other).
        # String not ENUM — matches the `status`-string convention
        # across the codebase so adding a new type (e.g. `passport`)
        # is an app-level constant change, not a migration.
        sa.Column("doc_type", sa.String(length=40), nullable=False),
        # Human-readable label. Required for doc_type="other" (so
        # the admin can see what the file actually is); redundant-
        # but-stored for the canonical types so a UI can render
        # consistently without special-casing.
        sa.Column("doc_label", sa.String(length=200), nullable=False, server_default=""),
        # Original filename the admin uploaded, preserved for
        # display + download-time Content-Disposition. NOT used for
        # storage path construction (that's UUID-based to prevent
        # path traversal).
        sa.Column("filename", sa.String(length=500), nullable=False),
        # Canonical file-type tag we compute from the MIME + magic
        # bytes at upload time (pdf | jpg | png | heic | docx).
        # Not the raw Content-Type header because that's
        # spoofable — magic-byte validated in the handler.
        sa.Column("file_type", sa.String(length=20), nullable=False),
        # Relative path under the configured doc-storage root —
        # e.g. ``profile-docs/{profile_id}/{doc_id}.{ext}``. Never
        # includes user-controlled path segments, so no traversal
        # vector via `../` etc.
        sa.Column("storage_path", sa.String(length=500), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        # Integrity check — SHA-256 of the stored bytes. Lets a
        # later audit detect tampering with the on-disk files.
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False, server_default=""),
        sa.Column(
            "uploaded_by_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "uploaded_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        # Soft delete — keeps the storage_path pointer until an
        # ops-level retention sweep actually unlinks the file.
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_profile_documents_profile_id", "profile_documents", ["profile_id"])
    op.create_index("ix_profile_documents_doc_type", "profile_documents", ["doc_type"])


def downgrade() -> None:
    op.drop_index("ix_profile_documents_doc_type", table_name="profile_documents")
    op.drop_index("ix_profile_documents_profile_id", table_name="profile_documents")
    op.drop_table("profile_documents")
    op.drop_index("ix_profiles_name", table_name="profiles")
    op.drop_index("ix_profiles_email_lower", table_name="profiles")
    op.drop_table("profiles")
