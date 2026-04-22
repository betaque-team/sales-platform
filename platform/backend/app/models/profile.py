"""Admin-only person-profile + KYC document vault.

Modelled for the HR/onboarding use case (Indian KYC specifically —
Aadhaar, PAN, UAN, PF, EPFO, 12th/college marksheets, address proof,
cancelled cheque, bank statement, passbook, father's Aadhaar/PAN/name).
See migration ``x4s5t6u7v8w9`` for the schema-design rationale.

Access is gated to ``admin`` and ``super_admin`` roles at the handler
level (``app.api.v1.profiles``); no viewer/reviewer access path exists.
Every access is audited via the existing ``audit_logs`` infrastructure.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import DateTime, Date, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Profile(Base):
    """A person whose KYC/HR documents we store (employee, contractor,
    or onboarding candidate — not a sales-pipeline job applicant)."""

    __tablename__ = "profiles"
    __table_args__ = (
        UniqueConstraint("email", name="uq_profiles_email"),
        # `lower(email)` index matches the case-insensitive search the
        # API uses. Declared here so autogenerate can pick it up if
        # the migration ever goes through SQLAlchemy metadata compare.
        Index("ix_profiles_name", "name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # `dob` is nullable because an admin may create a profile with
    # partial info and fill the DOB in later from the scanned Aadhaar.
    dob: Mapped[date | None] = mapped_column(Date, nullable=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)

    # Structured fields — text, not file upload. UAN/PF numbers are
    # Indian government identifiers that we store as the number
    # string (not the docs that prove them — those are separate
    # `ProfileDocument` rows). Kept on this table for fast
    # search/export without a JOIN.
    father_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    uan_number: Mapped[str | None] = mapped_column(String(40), nullable=True)
    pf_number: Mapped[str | None] = mapped_column(String(40), nullable=True)

    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)

    # RESTRICT on the FK so user deletion doesn't orphan the audit
    # trail. Matches `AuditLog.user_id` convention.
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    # Soft delete. The `DELETE /profiles/{id}` endpoint sets this
    # instead of issuing a hard DELETE, so records stay queryable
    # for audit / retention obligations. A separate purge job (not
    # shipped here — ops decision) would hard-delete after the
    # retention window.
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    documents: Mapped[list["ProfileDocument"]] = relationship(
        back_populates="profile",
        cascade="all, delete-orphan",
    )


class ProfileDocument(Base):
    """One uploaded document attached to a Profile.

    The canonical ``doc_type`` list lives in ``app.schemas.profile``
    (the Literal ``DOC_TYPE_CANONICAL``) — keep that in sync when
    adding new types. ``other`` is the escape hatch for documents
    outside the predefined set (passports, voter-ID cards, etc.) —
    the admin supplies ``doc_label`` to describe what the file is.
    """

    __tablename__ = "profile_documents"
    __table_args__ = (
        Index("ix_profile_documents_profile_id", "profile_id"),
        Index("ix_profile_documents_doc_type", "doc_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )

    doc_type: Mapped[str] = mapped_column(String(40), nullable=False)
    doc_label: Mapped[str] = mapped_column(String(200), default="", nullable=False)

    # Originally-uploaded filename, preserved so download responses
    # can set Content-Disposition with a sensible name. Never used
    # to construct storage paths — that's UUID-based to prevent
    # path-traversal.
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    # Canonical file-type tag computed at upload time from the MIME
    # type + magic bytes. Not the raw Content-Type header (spoofable).
    file_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # Relative path under the configured doc-storage root — safe by
    # construction (no user-controlled path segments).
    storage_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # SHA-256 of the stored bytes — lets a later integrity audit
    # detect tampering or filesystem corruption.
    checksum_sha256: Mapped[str] = mapped_column(String(64), default="", nullable=False)

    uploaded_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    profile: Mapped["Profile"] = relationship(back_populates="documents")
