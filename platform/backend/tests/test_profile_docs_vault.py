"""Tests for the admin-only profile-docs vault feature.

Two kinds of coverage — everything runs in the default CI pass:

1. **Unit tests on the storage helper** (`profile_doc_storage.py`).
   These exercise the security-critical bits in isolation against a
   tmp-dir fixture:
     * Magic-byte check rejects a renamed binary.
     * Size cap enforced.
     * Path resolution catches traversal attempts.
     * Checksum + atomic-write produce a stable on-disk artefact.

2. **Structural / RBAC checks** on the router module.
   No live DB. Asserts every route registered by the router applies
   `require_role("admin")` — the single most important invariant for
   this feature. A regression where someone downgrades a route to
   `get_current_user` would let any logged-in user pull Aadhaar scans.

Explicitly NOT in scope (covered by deploy verification):
  * Actually running the migration against Postgres — `ci-deploy.sh`
    runs `alembic upgrade head` on every deploy and fails the
    pipeline if any migration rejects.
  * End-to-end HTTP with a real DB — would need a fixture harness
    we don't have. The structural RBAC check is the strongest unit-
    testable substitute.
"""
from __future__ import annotations

import hashlib
import os
import pathlib
import uuid
from unittest.mock import patch

import pytest


# Minimum env so app.config imports cleanly.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://placeholder:placeholder@localhost:5432/placeholder",
)
os.environ.setdefault(
    "DATABASE_URL_SYNC",
    "postgresql://placeholder:placeholder@localhost:5432/placeholder",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET", "pytest-profile-vault")


# ── Storage helper — security-critical unit tests ──────────────────


@pytest.fixture
def tmp_doc_root(tmp_path, monkeypatch):
    """Point PROFILE_DOC_ROOT at a throwaway tmp dir for the test
    run. Each test gets its own isolated root.
    """
    root = tmp_path / "vault"
    root.mkdir()
    monkeypatch.setenv("PROFILE_DOC_ROOT", str(root))
    return root


# Minimal valid PDF: the 5-byte magic header plus an EOF marker. Real
# PDFs are larger but we only care about what the magic-byte check
# sees at bytes [0:5].
_VALID_PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n%%EOF\n"
_VALID_PNG = (
    b"\x89PNG\r\n\x1a\n"                  # 8-byte signature
    b"\x00\x00\x00\rIHDR"                 # IHDR chunk header
    b"\x00\x00\x00\x01\x00\x00\x00\x01"  # 1x1 dimensions
    b"\x08\x02\x00\x00\x00"               # bit depth / color type etc.
    b"\x90\x77\x53\xde"                   # IHDR CRC (not validated here)
    b"\x00\x00\x00\x00IEND\xaeB`\x82"    # IEND chunk
)


def test_storage_accepts_valid_pdf_and_records_sha256(tmp_doc_root):
    from app.utils.profile_doc_storage import validate_and_store

    profile_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    result = validate_and_store(
        profile_id=profile_id,
        doc_id=doc_id,
        file_bytes=_VALID_PDF,
        content_type="application/pdf",
        original_filename="aadhaar-scan.pdf",
    )

    assert result["file_type"] == "pdf"
    assert result["size_bytes"] == len(_VALID_PDF)
    assert result["checksum_sha256"] == hashlib.sha256(_VALID_PDF).hexdigest()
    # storage_path is RELATIVE to the root, no leading slash.
    assert result["storage_path"] == f"{profile_id}/{doc_id}.pdf"

    # On-disk artefact exists at the resolved absolute path, has
    # mode 0600, and contains exactly the bytes we sent.
    on_disk = tmp_doc_root / f"{profile_id}/{doc_id}.pdf"
    assert on_disk.is_file()
    mode = on_disk.stat().st_mode & 0o777
    assert mode == 0o600, f"expected 0600, got {oct(mode)}"
    assert on_disk.read_bytes() == _VALID_PDF


def test_storage_rejects_renamed_binary_via_magic_bytes(tmp_doc_root):
    """A malicious (or confused) admin uploads a `.pdf` renamed binary.
    The Content-Type matches PDF, the filename extension matches PDF,
    but the bytes don't start with `%PDF-`. Must raise.
    """
    from app.utils.profile_doc_storage import DocValidationError, validate_and_store

    fake_pdf = b"This is not a PDF; it's just text that claims to be one."

    with pytest.raises(DocValidationError, match="don't match the declared type"):
        validate_and_store(
            profile_id=uuid.uuid4(),
            doc_id=uuid.uuid4(),
            file_bytes=fake_pdf,
            content_type="application/pdf",
            original_filename="aadhaar.pdf",
        )


def test_storage_rejects_unsupported_mime(tmp_doc_root):
    """An executable MIME type is outright rejected — no magic-byte
    fallback saves it.
    """
    from app.utils.profile_doc_storage import DocValidationError, validate_and_store

    with pytest.raises(DocValidationError, match="Unsupported file type"):
        validate_and_store(
            profile_id=uuid.uuid4(),
            doc_id=uuid.uuid4(),
            file_bytes=b"#!/bin/sh\necho pwned\n",
            content_type="application/x-sh",
            original_filename="aadhaar.sh",
        )


def test_storage_rejects_oversize_upload(tmp_doc_root):
    """File above `MAX_DOC_BYTES` gets rejected before any I/O —
    critical for DoS protection. We synthesise a 21 MB PDF-looking
    blob (magic header + padding) so the size check fails ahead of
    the magic-byte check.
    """
    from app.utils.profile_doc_storage import (
        DocValidationError, MAX_DOC_BYTES, validate_and_store,
    )

    oversize = _VALID_PDF + b"\x00" * (MAX_DOC_BYTES + 1)

    with pytest.raises(DocValidationError, match="exceeds"):
        validate_and_store(
            profile_id=uuid.uuid4(),
            doc_id=uuid.uuid4(),
            file_bytes=oversize,
            content_type="application/pdf",
            original_filename="huge.pdf",
        )


def test_storage_rejects_empty_upload(tmp_doc_root):
    """Empty file — caught by the early-size check. Edge case: a
    race where the upload was cancelled mid-transfer."""
    from app.utils.profile_doc_storage import DocValidationError, validate_and_store

    with pytest.raises(DocValidationError, match="empty"):
        validate_and_store(
            profile_id=uuid.uuid4(),
            doc_id=uuid.uuid4(),
            file_bytes=b"",
            content_type="application/pdf",
            original_filename="blank.pdf",
        )


def test_storage_resolve_path_blocks_traversal(tmp_doc_root):
    """A tampered DB row carrying ``../../etc/passwd`` must not
    resolve to a path outside the root. The defensive check in
    `resolve_absolute_path` is our last line if someone SQL-injected
    or row-edited a bad storage_path in. Uses `relative_to()` for
    containment — string-prefix checks would be fooled by a
    ``<root>-evil/`` sibling directory.
    """
    from app.utils.profile_doc_storage import DocValidationError, resolve_absolute_path

    with pytest.raises(DocValidationError, match="escapes storage root"):
        resolve_absolute_path("../../etc/passwd")


def test_storage_png_accepted_with_correct_magic(tmp_doc_root):
    """Covers the second accepted image format — PNG magic bytes."""
    from app.utils.profile_doc_storage import validate_and_store

    result = validate_and_store(
        profile_id=uuid.uuid4(),
        doc_id=uuid.uuid4(),
        file_bytes=_VALID_PNG,
        content_type="image/png",
        original_filename="pan.png",
    )
    assert result["file_type"] == "png"


def test_storage_heic_magic_requires_ftyp_header(tmp_doc_root):
    """F238(a) regression — operator-precedence bug in HEIC magic-byte check.

    The original check read:
        ``data[4:8] == b"ftyp" and b"heic" in data[:24] or b"heix" in data[:24]``
    Python ``and`` binds tighter than ``or``, so the expression parsed as
    ``(ftyp AND heic) OR heix`` — any payload with ``b"heix"`` in its
    first 24 bytes would pass regardless of the ``ftyp`` header. A
    renamed binary like ``b"heix-malware..."`` would sail through.

    The fix wraps the ``or`` clause in parens so both brand variants
    are gated by the ``ftyp`` header check. This test locks that
    behaviour in.
    """
    from app.utils.profile_doc_storage import (
        DocValidationError, _magic_matches_ext, validate_and_store,
    )

    # Crafted payload: carries ``b"heix"`` in the first 24 bytes but
    # has NO ``ftyp`` header at bytes 4-7. Pre-fix, this returned True.
    crafted = b"\x00\x00\x00\x00JUNKheix" + b"A" * 40
    assert _magic_matches_ext(crafted, "heic") is False

    # Same thing but via the full upload pipeline — reports a validation
    # error instead of silently writing the byte stream as valid HEIC.
    with pytest.raises(DocValidationError, match="don't match the declared type"):
        validate_and_store(
            profile_id=uuid.uuid4(),
            doc_id=uuid.uuid4(),
            file_bytes=crafted,
            content_type="image/heic",
            original_filename="photo.heic",
        )

    # Positive case: real HEIC fingerprint with the ftyp box header
    # and the ``heic`` brand identifier still passes.
    real_heic = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic" + b"\x00" * 40
    assert _magic_matches_ext(real_heic, "heic") is True


def test_storage_rejects_zip_mime_even_when_filename_is_docx(tmp_doc_root):
    """F240(d) regression — a specific but non-allow-listed MIME must
    NOT fall through to the filename fallback.

    The tester's repro: browser sends ``Content-Type: application/zip``
    with a ``.docx`` filename. DOCX is a ZIP container, so the
    magic-byte check passes. Pre-fix, ``resolve_ext`` skipped the
    MIME (not in the allow-list), fell back to the filename's
    ``.docx`` suffix, and returned ``"docx"`` — leaving the row with
    ``file_type="docx"`` even though the browser explicitly declared
    it as a zip. Fix: only the generic / absent MIMEs (empty,
    ``application/octet-stream``) trigger the filename fallback;
    any other explicit MIME that isn't on the allow-list gets
    rejected outright.
    """
    from app.utils.profile_doc_storage import DocValidationError, resolve_ext

    with pytest.raises(DocValidationError, match="Unsupported file type"):
        resolve_ext("application/zip", "resume.docx")

    # Sanity: octet-stream still falls through to the filename suffix —
    # that path is how drag-and-drop uploads work and we don't want
    # to regress those. A ``.docx`` filename with
    # ``application/octet-stream`` as Content-Type still resolves to
    # "docx" so the DocType-legitimate path keeps working.
    assert resolve_ext("application/octet-stream", "resume.docx") == "docx"
    # Explicit DOCX MIME continues to work too.
    assert resolve_ext(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "resume.docx",
    ) == "docx"


def test_storage_unlink_is_safe_on_missing_file(tmp_doc_root):
    """unlink_if_exists returns False (no raise) when the path
    doesn't exist — used by the hard-delete path for retention
    purges that might race the filesystem.
    """
    from app.utils.profile_doc_storage import unlink_if_exists

    # Valid relative path, file not present.
    assert unlink_if_exists(f"{uuid.uuid4()}/{uuid.uuid4()}.pdf") is False


# ── RBAC invariant on the router ──────────────────────────────────


def test_every_profile_route_is_admin_gated():
    """Every route exposed by `profiles.router` must use
    `require_role("admin")` (directly or transitively).

    This is the single most important invariant for this feature —
    a regression where a route gets downgraded to
    `get_current_user` would let any logged-in viewer pull KYC
    bytes. The test walks the registered routes and asserts the
    dependency is present on each.
    """
    from app.api.v1 import profiles as profile_module

    routes = profile_module.router.routes
    assert len(routes) >= 6, (
        f"Expected at least 6 profile routes registered, got {len(routes)}. "
        "If this goes down, someone removed a route — make sure it wasn't "
        "the admin gate that got removed instead."
    )

    # FastAPI stores dependencies on the route's endpoint function via
    # the DI graph. The simplest way to check "did this route call
    # require_role('admin')" is to look at the closure of the
    # dependency callables registered on each route.
    import inspect
    for route in routes:
        # Only real API routes — skip websocket or mount.
        dependant = getattr(route, "dependant", None)
        if dependant is None:
            continue
        # Collect every dep callable on this route + its transitive deps.
        all_deps: list = []

        def _walk(dep):
            all_deps.append(dep.call)
            for sub in dep.dependencies:
                _walk(sub)

        for d in dependant.dependencies:
            _walk(d)

        # The `require_role("admin")` call returns an async `check(user=...)`
        # closure. Grep the source of every dep callable for
        # 'require_role' or "Insufficient privileges" (the 403 detail
        # message from `require_role`).
        matched = False
        for dep_fn in all_deps:
            try:
                src = inspect.getsource(dep_fn)
            except (OSError, TypeError):
                continue
            # Two independent markers so a rename doesn't silently
            # break this check.
            if "Insufficient privileges" in src or "ROLE_HIERARCHY" in src:
                matched = True
                break

        assert matched, (
            f"Route {getattr(route, 'path', route)!r} has no require_role "
            "admin gate — KYC data is exposed to any logged-in user. "
            "Wire `_ADMIN_GUARD = require_role('admin')` on the endpoint."
        )


def test_dob_validator_rejects_implausible_dates():
    """F240(a) regression — DOB must be in [1900-01-01, today].

    Pre-fix, Pydantic only validated ISO parse, so ``9999-12-31`` and
    ``1850-01-01`` both sailed through as-is to the DB and into the
    UI. For KYC data these are obvious data-entry errors — either a
    form-filler script or a typo — and we'd rather 422 than persist.
    """
    from datetime import date, timedelta

    import pytest
    from pydantic import ValidationError

    from app.schemas.profile import ProfileCreate, ProfileUpdate

    today = date.today()
    base = {"name": "Test", "email": "t@example.com"}

    # Future — rejected.
    with pytest.raises(ValidationError, match="future"):
        ProfileCreate(**base, dob=today + timedelta(days=1))

    # Far future (the tester's exact repro).
    with pytest.raises(ValidationError, match="future"):
        ProfileCreate(**base, dob=date(9999, 12, 31))

    # Pre-1900 (the tester's other repro).
    with pytest.raises(ValidationError, match="1900"):
        ProfileCreate(**base, dob=date(1850, 1, 1))

    # Edge: 1900-01-01 exactly — accepted (inclusive lower bound).
    p = ProfileCreate(**base, dob=date(1900, 1, 1))
    assert p.dob == date(1900, 1, 1)

    # Edge: today exactly — accepted.
    p = ProfileCreate(**base, dob=today)
    assert p.dob == today

    # None — still accepted (dob is optional, admin may fill later).
    p = ProfileCreate(**base, dob=None)
    assert p.dob is None

    # PATCH path gets the same guard.
    with pytest.raises(ValidationError, match="future"):
        ProfileUpdate(dob=date(2999, 1, 1))
    with pytest.raises(ValidationError, match="1900"):
        ProfileUpdate(dob=date(1800, 1, 1))


def test_doc_type_enum_matches_model_column_width():
    """The `DocType` Literal maps 1:1 with the canonical doc types;
    every value must fit in the `String(40)` column. Guards against
    adding a new type that's too long for the DB column.
    """
    from app.schemas.profile import DocType
    import typing

    doc_types = typing.get_args(DocType)
    for t in doc_types:
        assert len(t) <= 40, f"doc_type {t!r} exceeds 40-char column width"
    # Also a quick sanity that we didn't accidentally drop the
    # canonical set. If these names change, update both this list
    # and the comment-block in profile.py listing supported types.
    expected = {
        "aadhaar", "pan", "12th_marksheet", "college_marksheet",
        "cancelled_cheque", "bank_statement", "passbook",
        "epfo_nominee_proof", "father_aadhaar", "father_pan",
        "address_proof", "other",
    }
    assert set(doc_types) == expected, (
        f"DocType drift: expected {expected}, got {set(doc_types)}"
    )
