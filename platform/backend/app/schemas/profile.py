"""Pydantic schemas for the admin-only profile-docs vault.

Keep the canonical doc-type list here. Add new types to
``DOC_TYPE_CANONICAL`` (the Literal) — the runtime allow-list for the
``doc_type`` query param derives from it. The ``other`` catch-all
lets admins store docs outside the predefined set with a free-text
``doc_label``.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


# F240(a) regression fix: DOB calendar-plausibility range.
# Pydantic's ``date`` field only validates ISO-format parse; any
# syntactically-valid date (``0001-01-01``, ``9999-12-31``) sails
# through. For KYC data we want to reject obvious data-entry
# mistakes — a 1850-01-01 DOB is a typo, a 9999-12-31 is a form-fill
# scripting artefact. 1900 is a conservative upper bound for
# "old enough to be plausibly alive"; we don't enforce a strict
# ≥18 lower bound because the vault stores onboarding candidates
# whose DOB may be future-adjusted pending document verification.
# Uses module-level constants so the admin UI can mirror the range
# via the ``/api/v1/profiles`` OpenAPI spec if it wants to.
_DOB_MIN = date(1900, 1, 1)


def _validate_dob_range(value: date | None) -> date | None:
    """Enforce 1900 ≤ DOB ≤ today. Raise ValueError otherwise so
    Pydantic surfaces a 422 with the reason.
    """
    if value is None:
        return value
    today = date.today()
    if value < _DOB_MIN:
        raise ValueError(
            f"dob must be on or after {_DOB_MIN.isoformat()}; got {value.isoformat()}"
        )
    if value > today:
        raise ValueError(
            f"dob cannot be in the future; got {value.isoformat()} (today is {today.isoformat()})"
        )
    return value


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
    # F240(a): also gated by ``_validate_dob_range`` below so obvious
    # calendar-sanity errors (pre-1900, post-today) 422 instead of
    # being persisted.
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

    _validate_dob = field_validator("dob")(lambda cls, v: _validate_dob_range(v))


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

    # F240(a): same calendar-sanity guard as ProfileCreate.
    _validate_dob = field_validator("dob")(lambda cls, v: _validate_dob_range(v))

    # F242(a) regression fix: reject ``{"name": null}`` / ``{"email": null}``
    # / ``{"notes": null}`` at parse time. Pre-fix, the schema declared
    # these fields as ``str | None`` (so the field could be OMITTED from
    # a partial-update body) but the underlying Postgres columns are
    # ``NOT NULL``. An explicit JSON null sailed past Pydantic, the
    # handler ``setattr(profile, "name", None)``'d it, and asyncpg raised
    # ``IntegrityError`` which escaped as a bare HTTP 500 plain-text
    # body — same shape as F239's pre-fix crash.
    #
    # We use ``model_validator(mode="before")`` rather than per-field
    # validators because Pydantic V2 cannot distinguish "field omitted"
    # from "field explicitly null" inside a normal ``field_validator``
    # — both look like ``None``. The raw input dict CAN distinguish
    # them: the key is either present or absent. So we walk the raw
    # input and reject only the explicit-null case.
    #
    # The set of NOT-NULL columns is mirrored from
    # ``app.models.profile.Profile`` — keep them in sync if you add a
    # NOT-NULL column or relax one to nullable. Declared as a
    # ``ClassVar`` so Pydantic doesn't treat it as a model field
    # (a leading-underscore attr would otherwise be parsed as a private
    # ``ModelPrivateAttr`` and become non-iterable inside the validator).
    NOT_NULL_FIELDS: ClassVar[tuple[str, ...]] = ("name", "email", "notes")

    @model_validator(mode="before")
    @classmethod
    def _reject_explicit_null_for_not_null(cls, data):
        # ``data`` is whatever the body parser produced — a dict for a
        # JSON body, but Pydantic also passes through model instances
        # in nested-construction paths. Only the dict path is relevant
        # here (PATCH body is always JSON), but be defensive.
        if not isinstance(data, dict):
            return data
        for field in cls.NOT_NULL_FIELDS:
            if field in data and data[field] is None:
                raise ValueError(
                    f"{field!r} cannot be explicitly null — omit the field "
                    f"to leave it unchanged, or send a non-empty value to "
                    f"update it. The {field!r} column is NOT NULL."
                )
        return data


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


class ProfileListItem(BaseModel):
    """Slim profile shape for the list endpoint.

    F238(c) regression fix: the list view intentionally OMITS the
    hot KYC identifiers (``uan_number``, ``pf_number``) and the
    free-form ``notes`` field. Those are only returned on the detail
    endpoint (``GET /profiles/{id}``) — which is still admin-only but
    also separately audited, so "who saw what" is reconstructable.

    Rationale: a paginated list iterates over many rows at once, which
    makes it the prime screen-scrape target. Pulling the UAN/PF numbers
    into that response turned the list into a bulk-PII export. Even
    though both endpoints require ``admin``, scoping the list payload
    to searchable-metadata-only limits the blast radius of a compromised
    or over-privileged admin session.

    Keep in sync with ``ProfileOut`` below: any field present on both
    MUST have the same name + type so the ORM object validates into
    either.
    """
    id: UUID
    name: str
    dob: date | None = None
    email: str
    father_name: str | None = None
    created_by_user_id: UUID
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None
    document_count: int = 0

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
    # F238(c): list items use the slim shape (no UAN/PF/notes).
    items: list[ProfileListItem]
    total: int
    page: int
    page_size: int
    total_pages: int


class DocumentUploadResult(BaseModel):
    """Response for ``POST /api/v1/profiles/{id}/documents``."""
    document: ProfileDocumentOut
    profile_id: UUID
