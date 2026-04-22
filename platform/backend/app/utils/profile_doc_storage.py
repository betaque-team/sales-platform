"""Filesystem storage for profile KYC documents.

Layout
------
All profile docs live under a single root directory (env-configurable
via ``PROFILE_DOC_ROOT``, default ``/var/lib/sales-platform/profile-docs``):

    <root>/
      <profile_id>/
        <doc_id>.<ext>
        <doc_id>.<ext>
      <profile_id>/
        ...

* Filenames on disk are ``{doc_id}.{ext}`` (UUID + canonical ext).
  Never any user-supplied path segment — prevents traversal attacks.
* Per-profile subdirectory lets an operator ``rm -rf <profile_id>/``
  during a GDPR/DPDP erasure request without a SQL join.
* Mode ``0600`` on every file, ``0700`` on every directory. Backend
  container runs as an unprivileged user; filesystem perms are the
  last defence against a co-tenant process on the VM.

Security invariants this module is responsible for
--------------------------------------------------
1. **No path traversal.** Callers pass ``(profile_id, doc_id, ext)``
   as separate parameters; we never concatenate user-controlled
   strings into the path.
2. **MIME + magic-byte validation** before write. A ``.pdf``-renamed
   binary must get rejected — we look at the actual bytes, not the
   Content-Type header.
3. **Size cap enforced** (``MAX_DOC_BYTES``) before the buffer even
   reaches disk. The FastAPI endpoint reads the body; we re-verify
   here as defence-in-depth.
4. **Atomic writes.** Write to a ``.tmp`` sibling then ``os.replace()``
   — a crash mid-write can never leave a half-written file at the
   canonical path that a later read would consume.

Encryption note
---------------
This module stores the bytes as-is. At-rest encryption is an ops
concern (full-disk / LUKS on the VM) or a phase-2 app-level add.
If app-level AES lands, wrap the ``file_bytes`` param through a
cipher before ``open(..., "wb")`` and invert on read. Schema
(``storage_path``) does not change.
"""
from __future__ import annotations

import hashlib
import logging
import os
import pathlib
import uuid
from typing import Optional

logger = logging.getLogger(__name__)


# Default root — override via env var. The production deploy mounts a
# persistent volume at this path (docker-compose.prod.yml bind) so
# restarts don't lose the vault.
_DEFAULT_ROOT = "/var/lib/sales-platform/profile-docs"

# Upper bound per file. 20 MB covers a typical scanned PDF multi-page
# Aadhaar + passport-quality JPEGs, with headroom for bank-statement
# PDFs. Anything larger is usually a high-DPI scan that could be
# resized first — we'd rather nudge the admin than accept a 200 MB
# upload.
MAX_DOC_BYTES = 20 * 1024 * 1024


# MIME -> canonical extension. Keys must match the Content-Type the
# browser sends; the magic-byte check below is what actually enforces
# the file really is what it claims.
_MIME_TO_EXT: dict[str, str] = {
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/heic": "heic",
    "image/heif": "heic",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
}


class DocValidationError(ValueError):
    """Raised when an uploaded file fails size / MIME / magic-byte checks.

    Carries a short user-facing message; the FastAPI handler converts
    this to a ``400 Bad Request`` with the message in ``detail``. No
    internal path / config details in the message — it gets shown to
    an admin directly.
    """


def _magic_matches_ext(data: bytes, ext: str) -> bool:
    """Sanity-check that the first bytes look like the claimed type.

    Covers the common case where an attacker (or a confused admin)
    renames ``evil.exe`` to ``evil.pdf`` and uploads it. We'd still
    store the bytes but the ``file_type`` would be wrong, and more
    importantly the browser would fail on download — catch it here.

    Not a full MIME detection library (we don't need it for this
    narrow allow-list) — just a first-bytes signature check.
    """
    if not data:
        return False
    if ext == "pdf":
        return data.startswith(b"%PDF-")
    if ext == "jpg":
        # JPEG files start with FF D8 FF. Second-byte variants cover
        # JFIF (E0), EXIF (E1), and SPIFF (E8).
        return data[:3] in (b"\xff\xd8\xff",)
    if ext == "png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if ext == "heic":
        # HEIC uses the ISO-BMFF container; bytes 4-11 contain "ftypheic"
        # or "ftypheix" or "ftyphevc" or "ftyphevx". The exact brand
        # varies across iPhone versions — just check the ftyp box header
        # position which is stable.
        return data[4:8] == b"ftyp" and b"heic" in data[:24] or b"heix" in data[:24]
    if ext == "docx":
        # DOCX is a ZIP container; ZIP files start with PK\x03\x04.
        return data.startswith(b"PK\x03\x04")
    # Unknown ext — refuse. Keeps this function total (no "maybe-valid").
    return False


def resolve_ext(content_type: str | None, fallback_filename: str | None) -> str:
    """Map a request's Content-Type to our canonical extension.

    If the browser sends something we don't recognise (e.g. a missing
    Content-Type, or ``application/octet-stream`` for a drag-n-drop),
    fall back to the filename's extension so we can still accept
    obviously-legitimate uploads. Raises ``DocValidationError`` only
    if neither source yields a known type.
    """
    ct = (content_type or "").strip().lower()
    if ct in _MIME_TO_EXT:
        return _MIME_TO_EXT[ct]
    # Filename fallback — last 5 chars, lowercase. Guards against a
    # missing Content-Type for drag-n-drop uploads that some browsers
    # send as application/octet-stream.
    if fallback_filename:
        suffix = pathlib.PurePath(fallback_filename).suffix.lstrip(".").lower()
        # Accept only if the suffix matches one of our canonical exts,
        # not "exe" or "sh" or anything arbitrary.
        if suffix in {"pdf", "jpg", "jpeg", "png", "heic", "heif", "docx"}:
            return {"jpeg": "jpg", "heif": "heic"}.get(suffix, suffix)
    raise DocValidationError(
        "Unsupported file type. Allowed: PDF, JPG, PNG, HEIC, DOCX."
    )


def validate_and_store(
    profile_id: uuid.UUID,
    doc_id: uuid.UUID,
    file_bytes: bytes,
    content_type: str | None,
    original_filename: str | None,
) -> dict:
    """Atomic-write ``file_bytes`` to the canonical storage path.

    Runs the size + MIME + magic-byte checks in order. Raises
    ``DocValidationError`` on any failure; never creates a partial
    file on disk.

    Returns a dict with ``storage_path``, ``file_type``, ``size_bytes``,
    ``checksum_sha256`` — the fields the caller persists onto the
    ``ProfileDocument`` row.

    :raises DocValidationError: size / MIME / magic-byte failure.
    :raises OSError: filesystem failure (bubbles up; the handler
        translates to 500 and audit-logs the attempt).
    """
    # 1. Size cap — catch early before any file I/O.
    if len(file_bytes) == 0:
        raise DocValidationError("Uploaded file is empty.")
    if len(file_bytes) > MAX_DOC_BYTES:
        raise DocValidationError(
            f"File exceeds {MAX_DOC_BYTES // (1024*1024)} MB limit."
        )

    # 2. MIME → canonical extension.
    ext = resolve_ext(content_type, original_filename)

    # 3. Magic-byte check — the bytes must really be what the MIME
    # claims. Prevents a renamed binary from sneaking through.
    if not _magic_matches_ext(file_bytes, ext):
        raise DocValidationError(
            f"File contents don't match the declared type ({ext})."
        )

    # 4. Compute integrity checksum before write so we can store it
    # atomically alongside the file metadata.
    checksum = hashlib.sha256(file_bytes).hexdigest()

    # 5. Resolve the canonical storage path. The root is
    # env-configurable to support per-environment mounts.
    root = pathlib.Path(os.environ.get("PROFILE_DOC_ROOT", _DEFAULT_ROOT))
    profile_dir = root / str(profile_id)
    final_path = profile_dir / f"{doc_id}.{ext}"
    tmp_path = profile_dir / f".{doc_id}.tmp"

    # 6. Ensure directory exists with restrictive perms. mkdir(mode=...)
    # is affected by the process umask on Linux — we apply chmod
    # explicitly after creation to guarantee the intended mode.
    profile_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(profile_dir, 0o700)
    except OSError as exc:
        # Non-fatal — e.g. on a mounted volume where the backend
        # container doesn't own the root. Log and move on; the file's
        # own 0600 mode still protects contents.
        logger.warning("Could not chmod %s to 0700: %s", profile_dir, exc)

    # 7. Atomic write: open tmp, write, fsync, rename. A crash between
    # write and rename leaves a ``.tmp`` file — easy to sweep in an
    # ops cleanup task, can never be consumed as a valid doc.
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(file_bytes)
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        # Best-effort cleanup of the half-written tmp file — don't
        # shadow the original exception.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    os.replace(tmp_path, final_path)

    return {
        # Store the RELATIVE path (under `root`) so moving the root in
        # an env change doesn't invalidate every row.
        "storage_path": f"{profile_id}/{doc_id}.{ext}",
        "file_type": ext,
        "size_bytes": len(file_bytes),
        "checksum_sha256": checksum,
    }


def resolve_absolute_path(storage_path: str) -> pathlib.Path:
    """Resolve a stored ``storage_path`` to an absolute filesystem path,
    verified to sit inside the configured root.

    Defence-in-depth against a tampered DB row carrying
    ``../../etc/passwd`` or an absolute ``/etc/passwd``. Two
    independent checks:

    1. Reject any storage_path containing a ``..`` segment or starting
       with ``/`` — these are never legitimate outputs of
       :func:`validate_and_store`, so their presence in the DB means
       either tampering or a bug somewhere upstream. Fail loud.
    2. Normalise the joined path with ``os.path.normpath`` (which
       collapses ``..``) and assert it sits under the root.
       ``.absolute()`` alone does NOT normalise ``..`` — a bug the
       tests caught.

    :raises DocValidationError: path contains traversal or escapes root.
    """
    # (1) Reject obvious traversal patterns at the string level. Our
    # own `validate_and_store` only ever produces ``{uuid}/{uuid}.ext``,
    # so any `..` or leading `/` is foreign and suspect.
    if ".." in storage_path.split("/") or storage_path.startswith("/"):
        raise DocValidationError("Document path escapes storage root.")

    root = pathlib.Path(os.environ.get("PROFILE_DOC_ROOT", _DEFAULT_ROOT))
    root_norm = pathlib.Path(os.path.normpath(root.absolute()))

    # (2) normpath collapses `..` and `.` segments. After joining +
    # normalising, the candidate's string representation must start
    # with the root's + a separator. Using `+ os.sep` (not prefix-
    # match on the bare root) so a ``<root>-evil`` sibling directory
    # can't masquerade as the root.
    joined = os.path.normpath(str(root_norm) + os.sep + storage_path)
    if not (joined == str(root_norm) or joined.startswith(str(root_norm) + os.sep)):
        raise DocValidationError("Document path escapes storage root.")
    return pathlib.Path(joined)


def read_bytes(storage_path: str) -> bytes:
    """Read a stored document's bytes. Caller is responsible for
    authentication + audit logging before calling.
    """
    p = resolve_absolute_path(storage_path)
    if not p.is_file():
        raise FileNotFoundError(f"Document file missing: {storage_path}")
    with open(p, "rb") as f:
        return f.read()


def unlink_if_exists(storage_path: str) -> bool:
    """Remove the underlying file during a hard-delete / retention
    purge. Silent no-op if the file is already gone. Returns True if
    a file was actually unlinked, False otherwise.

    Soft delete (``archived_at`` on the row) does NOT call this —
    the file stays on disk until the retention sweep fires.
    """
    try:
        p = resolve_absolute_path(storage_path)
    except DocValidationError:
        return False
    try:
        p.unlink()
        return True
    except FileNotFoundError:
        return False
