"""Pydantic schemas for the admin-only profile-docs vault.

Keep the canonical doc-type list here. Add new types to
``DOC_TYPE_CANONICAL`` (the Literal) — the runtime allow-list for the
``doc_type`` query param derives from it. The ``other`` catch-all
lets admins store docs outside the predefined set with a free-text
``doc_label``.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


# The canonical set of document types the UI knows how to render
# (special-case labels, icons, etc.). Anything else goes under
# ``other`` with a free-text label.
#
# Adding a new type: add to this Literal, update the frontend
# ``PROFILE_DOC_TYPE_LABELS`` map, and (optionally) add an icon +
# upload-slot in the Profile detail UI. No migration required —
# the DB column is ``String(40)``.
DocType = Literal[
    "aadhaar",
    "pan",
    "12th_marksheet",
    "college_marksheet",
    "cancelled_cheque",
    "bank_statement",
    "passbook",
    "epfo_nominee_proof",
    "father_aadhaar",
    "father_pan",
    "address_proof",
    "other",
]


# === Document file-type allow-list ===
# Canonical tag -> (accepted MIME types, magic-byte prefix, extension).
# The handler validates BOTH the MIME type and the magic bytes so a
# ``.pdf``-renamed-binary doesn't slip through. Kept narrow on purpose:
# office docs (.docx) and image scans (jpg/png/heic/pdf) cover 99%+
# of real KYC uploads in the wild. PDF and PNG are magic-byte
# verified; JPEG allows both JFIF and raw EXIF-start bytes.
FILE_TYPE_PDF = "pdf"
FILE_TYPE_JPG = "jpg"
FILE_TYPE_PNG = "png"
FILE_TYPE_HEIC = "heic"
FILE_TYPE_DOCX = "docx"


class ProfileCreate(BaseModel):
    """Payload for ``POST /api/v1/profiles``.

    Strict fields only. Docs are uploaded separately via
    ``POST /api/v1/profiles/{id}/documents``. ``extra="forbid"`` so a
    typo (``nme`` instead of ``name``) 422s at parse time instead of
    being silently dropped.
    """
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=200)
    # Pydantic accepts ISO date strings or date objects.
    dob: date | None = None
    email: EmailStr
    father_name: str | None = Field(default=None, max_length=200)
    # UAN = 12 digits; PF = varies but typically an alphanumeric
    # office-code + account number. Store as strings, lightly
    # length-capped to prevent DB overflow. No format validation —
    # admins may enter numbers with or without spaces.
    uan_number: str | None = Field(default=None, max_length=40)
    pf_number: str | None = Field(default=None, max_length=40)
    notes: str = Field(default="", max_length=5000)


class ProfileUpdate(BaseModel):
    """PATCH payload. All fields optional so the admin can update one
    field at a time. ``extra="forbid"`` catches typos.
    """
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    dob: date | None = None
    email: EmailStr | None = None
    father_name: str | None = Field(default=None, max_length=200)
    uan_number: str | None = Field(default=None, max_length=40)
    pf_number: str | None = Field(default=None, max_length=40)
    notes: str | None = Field(default=None, max_length=5000)


class ProfileDocumentOut(BaseModel):
    """Document metadata. File contents served via
    ``GET /api/v1/profiles/{id}/documents/{doc_id}/download`` so the
    listing endpoint can stay cheap.
    """
    id: UUID
    doc_type: str
    doc_label: str
    filename: str
    file_type: str
    size_bytes: int
    uploaded_by_user_id: UUID
    uploaded_at: datetime
    archived_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ProfileOut(BaseModel):
    id: UUID
    name: str
    dob: date | None = None
    email: str
    father_name: str | None = None
    uan_number: str | None = None
    pf_number: str | None = None
    notes: str = ""
    created_by_user_id: UUID
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None
    # Document count is a cheap GROUP BY on the list endpoint; the
    # actual documents come from a separate query on the detail
    # endpoint.
    document_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class ProfileDetailOut(ProfileOut):
    """Extended profile — same shape + the full document list."""
    documents: list[ProfileDocumentOut] = []


class ProfileListResponse(BaseModel):
    items: list[ProfileOut]
    total: int
    page: int
    page_size: int
    total_pages: int


class DocumentUploadResult(BaseModel):
    """Response for ``POST /api/v1/profiles/{id}/documents``."""
    document: ProfileDocumentOut
    profile_id: UUID
