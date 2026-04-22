"""Live integration smoke tests for the KYC profile docs vault.

Script-mode test harness — follows the same shape as `test_api.py`.
Run against a reachable backend (local docker-compose or prod):

    # Local (after `docker compose up`):
    python -m platform.backend.tests.test_profile_vault_live \\
        --url http://localhost:8000/api/v1 \\
        --email admin@jobplatform.io --password admin123

    # Prod:
    python -m platform.backend.tests.test_profile_vault_live \\
        --url https://salesplatform.reventlabs.com/api/v1 \\
        --email <admin-email> --password <admin-pw>

Not collected by pytest (conftest.py's `collect_ignore_glob` already
excludes files that take a positional `client` arg; this file uses
the same pattern so it's script-only by the same mechanism).

What this covers that the unit tests don't:
  * The HTTP wire: multipart/form-data upload, audit-log write path,
    download headers (Content-Disposition + Cache-Control), 204 on
    archive, 410 on missing-bytes — none of which the in-process
    helper tests exercise.
  * RBAC against a real JWT: if a non-admin credential is provided
    via --viewer-email/--viewer-password, the script asserts 403 on
    every profile endpoint.
  * End-to-end artefact persistence: create profile → upload doc →
    download the exact bytes back → SHA-256 matches what was sent.

What this intentionally does NOT cover (out of scope for a smoke
test; handled by the unit tests in test_profile_docs_vault.py):
  * Path-traversal rejection (filesystem-only concern).
  * Magic-byte discrimination for every MIME variant.
  * Exact error-string content for validation failures.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import sys
import time
import uuid

import httpx


BASE_URL = "http://localhost:8000/api/v1"
EMAIL = "admin@jobplatform.io"
PASSWORD = "admin123"

# Minimal valid artefacts — same fixtures as the unit-test file.
VALID_PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n%%EOF\n"
VALID_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00"
    b"\x90\x77\x53\xde"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)

_PASS = "\033[92m\u2713\033[0m"
_FAIL = "\033[91m\u2717\033[0m"
_results: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> bool:
    symbol = _PASS if condition else _FAIL
    print(f"  {symbol} {name}" + (f"  [{detail}]" if detail else ""))
    _results.append((name, condition, detail))
    return condition


def section(title: str) -> None:
    bar = "\u2500" * 60
    print(f"\n{bar}\n  {title}\n{bar}")


def login(client: httpx.Client, base_url: str, email: str, password: str) -> dict:
    resp = client.post(f"{base_url}/auth/login", json={"email": email, "password": password})
    if resp.status_code != 200:
        raise RuntimeError(f"Login failed for {email}: {resp.status_code} {resp.text}")
    data = resp.json()
    # Mirror the frontend: JWT lives in the `session` cookie for subsequent calls.
    # The login endpoint already sets Set-Cookie, but httpx.Client picks it up
    # only if we use the same Client instance — which we do.
    return data


def _unique_email() -> str:
    """A throwaway email so repeated runs don't 409 each other.
    Using a uuid4 tail keeps the local-part under 64 chars."""
    return f"vault-test-{uuid.uuid4().hex[:8]}@example.invalid"


# ── Test: happy-path lifecycle ────────────────────────────────────────────


def test_profile_lifecycle(client: httpx.Client, base_url: str) -> str | None:
    """Create → list → get → upload (PDF + PNG) → download (verify
    SHA-256) → archive one doc → hard-delete another → archive the
    profile. Returns the created profile_id on success (for cleanup)
    or None on early failure."""
    section("Profile lifecycle — create / upload / download / archive")

    email = _unique_email()
    # 1. Create
    resp = client.post(
        f"{base_url}/profiles",
        json={
            "name": "Vault Smoke Test",
            "email": email,
            "dob": "1990-01-01",
            "father_name": "Smoke Sr.",
            "uan_number": "100000000000",
            "pf_number": "DL/MUM/99999/000/0000001",
            "notes": "automated smoke test — safe to delete",
        },
    )
    if not check("POST /profiles 201", resp.status_code == 201, f"got {resp.status_code}: {resp.text[:200]}"):
        return None
    profile = resp.json()
    profile_id = profile["id"]
    check("Response has uuid-shaped id", isinstance(profile_id, str) and len(profile_id) == 36)
    check("document_count starts at 0", profile.get("document_count") == 0)

    # 2. Duplicate email → 409
    dupe = client.post(f"{base_url}/profiles", json={"name": "Dupe", "email": email})
    check("Duplicate email → 409", dupe.status_code == 409, f"got {dupe.status_code}")

    # 3. List includes the new profile
    listing = client.get(f"{base_url}/profiles?search={email}")
    check("GET /profiles search works", listing.status_code == 200)
    items = listing.json().get("items", [])
    check("New profile appears in search", any(p["id"] == profile_id for p in items))

    # 4. Get detail — no docs yet
    detail = client.get(f"{base_url}/profiles/{profile_id}")
    check("GET /profiles/{id} 200", detail.status_code == 200)
    check("Documents list is empty", detail.json().get("documents") == [])

    # 5. PATCH the notes field
    patched = client.patch(f"{base_url}/profiles/{profile_id}", json={"notes": "updated note"})
    check("PATCH /profiles/{id} 200", patched.status_code == 200)
    check("Patched notes visible", patched.json().get("notes") == "updated note")

    # 6. Upload PDF
    pdf_resp = client.post(
        f"{base_url}/profiles/{profile_id}/documents",
        files={"file": ("aadhaar.pdf", VALID_PDF, "application/pdf")},
        data={"doc_type": "aadhaar"},
    )
    if not check("POST document (PDF) 201", pdf_resp.status_code == 201, f"got {pdf_resp.status_code}: {pdf_resp.text[:200]}"):
        # Cleanup even if upload failed — profile still exists.
        client.delete(f"{base_url}/profiles/{profile_id}")
        return profile_id
    pdf_doc = pdf_resp.json()["document"]
    pdf_doc_id = pdf_doc["id"]
    check("PDF doc_type = aadhaar", pdf_doc.get("doc_type") == "aadhaar")
    check("PDF file_type = pdf", pdf_doc.get("file_type") == "pdf")
    check("PDF size_bytes matches", pdf_doc.get("size_bytes") == len(VALID_PDF))

    # 7. Upload PNG (covers the second magic-byte branch)
    png_resp = client.post(
        f"{base_url}/profiles/{profile_id}/documents",
        files={"file": ("pan-card.png", VALID_PNG, "image/png")},
        data={"doc_type": "pan"},
    )
    check("POST document (PNG) 201", png_resp.status_code == 201, f"got {png_resp.status_code}: {png_resp.text[:200]}")
    png_doc_id = png_resp.json()["document"]["id"] if png_resp.status_code == 201 else None

    # 8. Upload "other" without a label → 400
    bad_other = client.post(
        f"{base_url}/profiles/{profile_id}/documents",
        files={"file": ("misc.pdf", VALID_PDF, "application/pdf")},
        data={"doc_type": "other"},
    )
    check(
        'doc_type="other" without label → 400',
        bad_other.status_code == 400 and "doc_label" in bad_other.text,
        f"got {bad_other.status_code}",
    )

    # 9. Upload "other" WITH label → 201
    good_other = client.post(
        f"{base_url}/profiles/{profile_id}/documents",
        files={"file": ("misc.pdf", VALID_PDF, "application/pdf")},
        data={"doc_type": "other", "doc_label": "Appointment letter"},
    )
    check('doc_type="other" with label → 201', good_other.status_code == 201)
    other_doc_id = good_other.json()["document"]["id"] if good_other.status_code == 201 else None

    # 10. Download the PDF — bytes must round-trip exactly
    dl = client.get(f"{base_url}/profiles/{profile_id}/documents/{pdf_doc_id}/download")
    check("GET document download 200", dl.status_code == 200)
    check(
        "Content-Disposition = attachment",
        "attachment" in dl.headers.get("content-disposition", "").lower(),
    )
    check(
        "Cache-Control forbids caching",
        "no-store" in dl.headers.get("cache-control", ""),
    )
    check(
        "Content-Type = application/pdf",
        dl.headers.get("content-type", "").startswith("application/pdf"),
    )
    check(
        "Downloaded bytes match uploaded bytes",
        dl.content == VALID_PDF,
        f"sha256 got {hashlib.sha256(dl.content).hexdigest()[:12]}…",
    )

    # 11. Detail now shows 3 active documents
    detail2 = client.get(f"{base_url}/profiles/{profile_id}")
    docs = detail2.json().get("documents", [])
    check(
        "Detail has 3 active documents",
        len([d for d in docs if not d.get("archived_at")]) == 3,
        f"got {len(docs)}",
    )

    # 12. Soft-archive the PNG
    if png_doc_id:
        arch = client.delete(f"{base_url}/profiles/{profile_id}/documents/{png_doc_id}")
        check("DELETE (soft) document → 204", arch.status_code == 204)
        # Re-read — should now have archived_at set
        d3 = client.get(f"{base_url}/profiles/{profile_id}?include_archived=true").json()
        png_row = next((d for d in d3["documents"] if d["id"] == png_doc_id), None)
        check("Archived PNG has archived_at", png_row is not None and png_row.get("archived_at"))

    # 13. Hard-delete the "other" doc
    if other_doc_id:
        hard = client.delete(f"{base_url}/profiles/{profile_id}/documents/{other_doc_id}?hard=true")
        check("DELETE (hard) document → 204", hard.status_code == 204)
        # Download it — should now 404 (row gone)
        gone = client.get(f"{base_url}/profiles/{profile_id}/documents/{other_doc_id}/download")
        check("Hard-deleted doc → 404 on download", gone.status_code == 404)

    # 14. Archive the profile itself
    ap = client.delete(f"{base_url}/profiles/{profile_id}")
    check("DELETE /profiles/{id} → 204", ap.status_code == 204)
    # Default list no longer includes it
    listing2 = client.get(f"{base_url}/profiles?search={email}")
    check(
        "Archived profile hidden from default list",
        not any(p["id"] == profile_id for p in listing2.json().get("items", [])),
    )
    # include_archived=true brings it back
    listing3 = client.get(f"{base_url}/profiles?search={email}&include_archived=true")
    check(
        "Archived profile visible with include_archived=true",
        any(p["id"] == profile_id for p in listing3.json().get("items", [])),
    )

    return profile_id


# ── Test: upload validation ───────────────────────────────────────────────


def test_upload_validation(client: httpx.Client, base_url: str) -> None:
    """Defense-in-depth: renamed binary rejected, oversized rejected,
    empty rejected, unsupported MIME rejected. Creates a disposable
    profile so the rejections can't pollute an existing one."""
    section("Upload validation — magic bytes / size / MIME")

    p = client.post(
        f"{base_url}/profiles",
        json={"name": "Upload Rejects", "email": _unique_email()},
    )
    if not check("Create disposable profile 201", p.status_code == 201):
        return
    pid = p.json()["id"]

    # Renamed binary — claims to be a PDF but isn't.
    rb = client.post(
        f"{base_url}/profiles/{pid}/documents",
        files={"file": ("fake.pdf", b"This is plain text, not a PDF.", "application/pdf")},
        data={"doc_type": "aadhaar"},
    )
    check(
        "Renamed binary rejected → 400",
        rb.status_code == 400 and "declared type" in rb.text,
        f"got {rb.status_code}: {rb.text[:120]}",
    )

    # Oversize (21 MB) — use valid PDF header + padding so size check trips
    # ahead of the magic-byte check.
    big = VALID_PDF + b"\x00" * (20 * 1024 * 1024 + 1)
    os_resp = client.post(
        f"{base_url}/profiles/{pid}/documents",
        files={"file": ("huge.pdf", big, "application/pdf")},
        data={"doc_type": "aadhaar"},
    )
    check(
        "Oversize upload rejected → 400 or 413",
        os_resp.status_code in (400, 413),
        f"got {os_resp.status_code}",
    )

    # Empty body
    empty = client.post(
        f"{base_url}/profiles/{pid}/documents",
        files={"file": ("blank.pdf", b"", "application/pdf")},
        data={"doc_type": "aadhaar"},
    )
    check(
        "Empty upload rejected → 400 or 422",
        empty.status_code in (400, 422),
        f"got {empty.status_code}",
    )

    # Unsupported MIME
    sh = client.post(
        f"{base_url}/profiles/{pid}/documents",
        files={"file": ("x.sh", b"#!/bin/sh\necho pwn\n", "application/x-sh")},
        data={"doc_type": "other", "doc_label": "bad"},
    )
    check(
        "Executable MIME rejected → 400",
        sh.status_code == 400 and "Unsupported" in sh.text,
        f"got {sh.status_code}: {sh.text[:120]}",
    )

    # Unknown doc_type → 422 (Pydantic Literal rejects at parse time)
    bad_type = client.post(
        f"{base_url}/profiles/{pid}/documents",
        files={"file": ("x.pdf", VALID_PDF, "application/pdf")},
        data={"doc_type": "NOT_A_REAL_TYPE"},
    )
    check("Unknown doc_type → 422", bad_type.status_code == 422, f"got {bad_type.status_code}")

    # Cleanup
    client.delete(f"{base_url}/profiles/{pid}")


# ── Test: RBAC (requires a second, non-admin account) ─────────────────────


def test_rbac(base_url: str, non_admin_email: str, non_admin_pw: str) -> None:
    """Every profile endpoint must 403 for a reviewer/viewer token.
    Skipped if no non-admin credentials were supplied."""
    section("RBAC — non-admin must get 403")

    if not non_admin_email or not non_admin_pw:
        print("  (skipped — no --viewer-email / --viewer-password supplied)")
        return

    with httpx.Client(timeout=30, follow_redirects=True) as c:
        try:
            login(c, base_url, non_admin_email, non_admin_pw)
        except Exception as exc:
            check(f"Login as non-admin {non_admin_email}", False, str(exc))
            return

        # A bogus UUID — the RBAC gate fires before lookup, so the
        # profile not existing is irrelevant.
        bogus = uuid.uuid4()

        cases: list[tuple[str, httpx.Response]] = [
            ("GET /profiles", c.get(f"{base_url}/profiles")),
            ("GET /profiles/{id}", c.get(f"{base_url}/profiles/{bogus}")),
            ("POST /profiles", c.post(f"{base_url}/profiles", json={"name": "x", "email": "x@x.com"})),
            ("PATCH /profiles/{id}", c.patch(f"{base_url}/profiles/{bogus}", json={"notes": "x"})),
            ("DELETE /profiles/{id}", c.delete(f"{base_url}/profiles/{bogus}")),
            (
                "POST /profiles/{id}/documents",
                c.post(
                    f"{base_url}/profiles/{bogus}/documents",
                    files={"file": ("x.pdf", VALID_PDF, "application/pdf")},
                    data={"doc_type": "aadhaar"},
                ),
            ),
            (
                "GET /profiles/{id}/documents/{doc_id}/download",
                c.get(f"{base_url}/profiles/{bogus}/documents/{bogus}/download"),
            ),
            (
                "DELETE /profiles/{id}/documents/{doc_id}",
                c.delete(f"{base_url}/profiles/{bogus}/documents/{bogus}"),
            ),
        ]
        for name, resp in cases:
            check(
                f"{name} for non-admin → 403",
                resp.status_code == 403,
                f"got {resp.status_code}: {resp.text[:80]}",
            )
            # F185 invariant: no role-name leak in the body.
            check(
                f"{name} body hides required role",
                "admin" not in resp.text.lower() and "super_admin" not in resp.text.lower(),
                resp.text[:80],
            )


# ── Runner ────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description="Profile vault live smoke tests")
    parser.add_argument("--url", default=BASE_URL, help="Base API URL (including /api/v1)")
    parser.add_argument("--email", default=EMAIL, help="Admin email")
    parser.add_argument("--password", default=PASSWORD, help="Admin password")
    parser.add_argument("--viewer-email", default="", help="Optional: non-admin email for RBAC test")
    parser.add_argument("--viewer-password", default="", help="Optional: non-admin password")
    args = parser.parse_args()

    bar = "\u2550" * 60
    print(f"\n{bar}\n  Profile vault live smoke tests\n  Target: {args.url}\n{bar}")
    start = time.time()

    with httpx.Client(timeout=30, follow_redirects=True) as client:
        try:
            login(client, args.url, args.email, args.password)
            print(f"\n  Logged in as {args.email}")
        except Exception as exc:
            print(f"\n  FATAL: {exc}")
            return 2

        created = test_profile_lifecycle(client, args.url)
        test_upload_validation(client, args.url)

    test_rbac(args.url, args.viewer_email, args.viewer_password)

    elapsed = time.time() - start
    passed = sum(1 for _, ok, _ in _results if ok)
    failed = sum(1 for _, ok, _ in _results if not ok)
    total = len(_results)
    print(f"\n{bar}\n  Results: {passed}/{total} passed  ({elapsed:.1f}s)")
    if failed:
        print("\n  Failed:")
        for name, ok, detail in _results:
            if not ok:
                print(f"    \u2717 {name}" + (f"  [{detail}]" if detail else ""))
    print(bar)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
