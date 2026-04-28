/**
 * Admin-only profile detail page.
 *
 * Three responsibilities:
 *   1. Display + edit the profile's text fields (name, email, dob,
 *      father info, UAN, PF, notes).
 *   2. List uploaded documents with filename / size / type / uploaded
 *      timestamp + a download button.
 *   3. Upload new documents — one doc_type slot per row in the
 *      canonical list, plus a free-form "other" slot.
 *
 * Security notes mirrored from the backend:
 *   - Every read of this page triggers a `profile.read` audit row.
 *   - Downloads are 0600 on disk; the browser downloads rather than
 *     previews (backend sends `Content-Disposition: attachment`).
 *   - "Hard delete" uses `?hard=true` — reserved for GDPR / DPDP
 *     erasure requests. The UI requires a second-click confirm so
 *     nobody accidentally unlinks KYC bytes.
 */
import { useState, useMemo } from "react";
import { Link, useParams, useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
// `useQueryClient` is referenced by several sub-components below
// (they need to invalidate the cached profile after mutations).
// Import lives at the top-level so the hooks rule doesn't complain.
import {
  ArrowLeft,
  Upload,
  Download,
  Trash2,
  Archive,
  Lock,
  ShieldAlert,
  Check,
  X,
  Save,
  FileText,
  Edit3,
} from "lucide-react";

import { Card } from "@/components/Card";
import { Button } from "@/components/Button";
import {
  getProfile,
  updateProfile,
  archiveProfile,
  uploadProfileDocument,
  profileDocumentDownloadUrl,
  archiveProfileDocument,
} from "@/lib/api";
import type {
  ProfileDetail,
  ProfileDocType,
  ProfileDocument,
  ProfileUpdatePayload,
} from "@/lib/types";

// Canonical doc-type labels. Source of truth for label strings —
// keep in sync with backend/app/schemas/profile.py::DocType. Order
// here dictates the order of upload slots in the UI.
const DOC_TYPE_LABELS: Record<ProfileDocType, string> = {
  aadhaar: "Aadhaar",
  pan: "PAN",
  "12th_marksheet": "12th marksheet",
  college_marksheet: "College marksheet",
  cancelled_cheque: "Cancelled cheque",
  bank_statement: "Bank statement",
  passbook: "Passbook",
  epfo_nominee_proof: "EPFO nominee proof",
  father_aadhaar: "Father's Aadhaar",
  father_pan: "Father's PAN",
  address_proof: "Address proof",
  other: "Other",
};

const DOC_TYPE_ORDER: ProfileDocType[] = [
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
];

// 20 MB — matches `MAX_DOC_BYTES` in
// backend/app/utils/profile_doc_storage.py. Frontend-side check
// short-circuits the request before the 20 MB body hits the wire.
const MAX_DOC_BYTES = 20 * 1024 * 1024;

// Browsers populate `accept` from this list. Backend still runs the
// magic-byte check as the ground truth — this is pure UX hinting.
const ACCEPT_ATTR =
  "application/pdf,image/jpeg,image/png,image/heic,application/vnd.openxmlformats-officedocument.wordprocessingml.document";

export function ProfileDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const [editing, setEditing] = useState(false);

  const {
    data: profile,
    isLoading,
    error,
  } = useQuery({
    queryKey: ["profile", id],
    queryFn: () => getProfile(id!, { include_archived: true }),
    enabled: !!id,
    retry: (failureCount, err: any) => {
      if (err?.status === 403 || err?.status === 404) return false;
      return failureCount < 3;
    },
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="spinner h-8 w-8" />
      </div>
    );
  }

  if (error && (error as any).status === 403) {
    return <PermissionDenied />;
  }

  if (error && (error as any).status === 404) {
    return (
      <EmptyState
        title="Profile not found"
        body="This profile may have been deleted or never existed."
      />
    );
  }

  if (error || !profile) {
    return (
      <EmptyState
        title="Failed to load profile"
        body={(error as Error | undefined)?.message || "Unknown error"}
      />
    );
  }

  return (
    <div className="space-y-6">
      {/* Back link */}
      <div>
        <Link
          to="/profiles"
          className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700"
        >
          <ArrowLeft className="h-4 w-4" /> Back to profiles
        </Link>
      </div>

      <ProfileHeader
        profile={profile}
        editing={editing}
        onToggleEdit={() => setEditing((v) => !v)}
        onArchived={() => navigate("/profiles")}
      />

      <ProfileFields
        profile={profile}
        editing={editing}
        onSaved={() => setEditing(false)}
      />

      <DocumentsSection profile={profile} />

      <UploadSection profileId={profile.id} archived={!!profile.archived_at} />

      {/* Footer invariant: hint to the admin that every action on this
          page is auditable. Mirrors the banner on the list page. */}
      <p className="text-xs text-gray-400 flex items-center gap-1.5">
        <ShieldAlert className="h-3 w-3" />
        All reads, uploads, and downloads on this profile are recorded
        in the audit log.
      </p>
    </div>
  );
}

// ── Header: title + archive / edit buttons ─────────────────────────────────

function ProfileHeader({
  profile,
  editing,
  onToggleEdit,
  onArchived,
}: {
  profile: ProfileDetail;
  editing: boolean;
  onToggleEdit: () => void;
  onArchived: () => void;
}) {
  const queryClient = useQueryClient();
  const [confirmArchive, setConfirmArchive] = useState(false);
  // F260 (feedback "Profile Vault delete — UI button missing"): a soft
  // archive sets archived_at but leaves the row + on-disk files in
  // place, which doesn't satisfy DPDP/GDPR erasure requests. We add a
  // separate "Delete permanently" path that mirrors the F238(d)
  // document-level pattern: typed-email second factor + cascade.
  const [hardMode, setHardMode] = useState(false);
  const [typedEmail, setTypedEmail] = useState("");
  const [hardErr, setHardErr] = useState<string | null>(null);

  const archiveMutation = useMutation({
    mutationFn: () => archiveProfile(profile.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["profiles"] });
      onArchived();
    },
  });

  const hardDeleteMutation = useMutation({
    mutationFn: () =>
      archiveProfile(profile.id, { hard: true, confirm: typedEmail }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["profiles"] });
      onArchived();
    },
    onError: (e: any) => setHardErr(e?.message || "Permanent delete failed"),
  });

  // The backend does its own case-insensitive equality check, but we
  // mirror it client-side so the "Delete permanently" button stays
  // disabled until the operator has typed the exact profile email —
  // small friction so the action is never accidental.
  const emailMatches =
    typedEmail.trim().toLowerCase() === profile.email.toLowerCase();

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">{profile.name}</h1>
          <p className="mt-1 text-sm text-gray-500">{profile.email}</p>
          {profile.archived_at && (
            <span className="mt-2 inline-flex items-center gap-1 rounded bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600">
              <Archive className="h-3 w-3" /> Archived{" "}
              {new Date(profile.archived_at).toLocaleDateString()}
            </span>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="secondary" onClick={onToggleEdit}>
            <Edit3 className="mr-1.5 h-4 w-4" />
            {editing ? "Cancel edit" : "Edit fields"}
          </Button>
          {!profile.archived_at &&
            (confirmArchive ? (
              <>
                <Button
                  variant="danger"
                  onClick={() => archiveMutation.mutate()}
                  loading={archiveMutation.isPending}
                >
                  Confirm archive
                </Button>
                <Button
                  variant="secondary"
                  onClick={() => setConfirmArchive(false)}
                >
                  Cancel
                </Button>
              </>
            ) : (
              <Button
                variant="secondary"
                onClick={() => setConfirmArchive(true)}
              >
                <Archive className="mr-1.5 h-4 w-4" /> Archive profile
              </Button>
            ))}
          {/* Hard delete is always available — even on already-archived
              profiles — because erasure requests can come in for soft-
              archived rows too. Distinguishing the two buttons with
              different copy + the typed-email gate avoids the "I clicked
              archive thinking it would purge" failure mode. */}
          {!hardMode ? (
            <Button
              variant="danger"
              onClick={() => {
                setHardMode(true);
                setHardErr(null);
                setTypedEmail("");
              }}
            >
              <Trash2 className="mr-1.5 h-4 w-4" /> Delete permanently
            </Button>
          ) : null}
        </div>
      </div>

      {hardMode && (
        <div className="rounded-md border border-red-200 bg-red-50 p-4 text-sm">
          <p className="font-semibold text-red-800">
            Permanently delete this profile?
          </p>
          <p className="mt-1 text-red-700">
            This will remove the row and unlink every uploaded document
            file from disk. This cannot be undone — soft-archive
            (above) is the reversible path. Reserved for DPDP / GDPR
            erasure requests.
          </p>
          <p className="mt-3 text-red-700">
            Type{" "}
            <code className="rounded bg-white px-1.5 py-0.5 font-mono text-xs text-red-900">
              {profile.email}
            </code>{" "}
            to confirm:
          </p>
          <input
            type="text"
            autoFocus
            className="input mt-2 w-full max-w-md"
            placeholder={profile.email}
            value={typedEmail}
            onChange={(e) => setTypedEmail(e.target.value)}
          />
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Button
              variant="danger"
              onClick={() => hardDeleteMutation.mutate()}
              loading={hardDeleteMutation.isPending}
              disabled={!emailMatches || hardDeleteMutation.isPending}
            >
              <Trash2 className="mr-1.5 h-4 w-4" /> Confirm permanent delete
            </Button>
            <Button
              variant="secondary"
              onClick={() => {
                setHardMode(false);
                setTypedEmail("");
                setHardErr(null);
              }}
              disabled={hardDeleteMutation.isPending}
            >
              Cancel
            </Button>
            {hardErr && (
              <p className="text-sm font-medium text-red-700">{hardErr}</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Field display / edit form ───────────────────────────────────────────────

function ProfileFields({
  profile,
  editing,
  onSaved,
}: {
  profile: ProfileDetail;
  editing: boolean;
  onSaved: () => void;
}) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<ProfileUpdatePayload>({
    name: profile.name,
    email: profile.email,
    dob: profile.dob,
    father_name: profile.father_name,
    uan_number: profile.uan_number,
    pf_number: profile.pf_number,
    notes: profile.notes,
  });
  const [err, setErr] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: async () => {
      // Normalise empty strings to null / "" per backend expectations.
      const payload: ProfileUpdatePayload = {
        name: form.name?.trim() || undefined,
        email: form.email?.trim() || undefined,
        dob: form.dob || null,
        father_name: form.father_name?.trim() || null,
        uan_number: form.uan_number?.trim() || null,
        pf_number: form.pf_number?.trim() || null,
        notes: form.notes ?? "",
      };
      return updateProfile(profile.id, payload);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["profile", profile.id] });
      queryClient.invalidateQueries({ queryKey: ["profiles"] });
      onSaved();
      setErr(null);
    },
    onError: (e: any) => setErr(e?.message || "Save failed"),
  });

  if (!editing) {
    return (
      <Card>
        <div className="grid grid-cols-1 gap-x-6 gap-y-4 sm:grid-cols-2">
          <ReadOnlyField label="Name" value={profile.name} />
          <ReadOnlyField label="Email" value={profile.email} />
          <ReadOnlyField
            label="Date of birth"
            value={profile.dob || "—"}
          />
          <ReadOnlyField
            label="Father's name"
            value={profile.father_name || "—"}
          />
          <ReadOnlyField
            label="UAN number"
            value={profile.uan_number || "—"}
          />
          <ReadOnlyField
            label="PF number"
            value={profile.pf_number || "—"}
          />
          <div className="sm:col-span-2">
            <ReadOnlyField
              label="Notes"
              value={profile.notes || "—"}
              multiline
            />
          </div>
        </div>
      </Card>
    );
  }

  return (
    <Card>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
        className="grid grid-cols-1 gap-4 sm:grid-cols-2"
      >
        <EditField label="Name">
          <input
            className="input w-full"
            value={form.name ?? ""}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
        </EditField>
        <EditField label="Email">
          <input
            type="email"
            className="input w-full"
            value={form.email ?? ""}
            onChange={(e) => setForm({ ...form, email: e.target.value })}
          />
        </EditField>
        <EditField label="Date of birth">
          <input
            type="date"
            className="input w-full"
            value={form.dob || ""}
            onChange={(e) => setForm({ ...form, dob: e.target.value })}
          />
        </EditField>
        <EditField label="Father's name">
          <input
            className="input w-full"
            value={form.father_name ?? ""}
            onChange={(e) =>
              setForm({ ...form, father_name: e.target.value })
            }
          />
        </EditField>
        <EditField label="UAN number">
          <input
            className="input w-full"
            value={form.uan_number ?? ""}
            onChange={(e) =>
              setForm({ ...form, uan_number: e.target.value })
            }
          />
        </EditField>
        <EditField label="PF number">
          <input
            className="input w-full"
            value={form.pf_number ?? ""}
            onChange={(e) => setForm({ ...form, pf_number: e.target.value })}
          />
        </EditField>
        <div className="sm:col-span-2">
          <EditField label="Notes">
            <textarea
              rows={4}
              className="input w-full"
              value={form.notes ?? ""}
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
            />
          </EditField>
        </div>
        <div className="sm:col-span-2 flex items-center gap-3">
          <Button type="submit" variant="primary" loading={save.isPending}>
            <Save className="mr-1.5 h-4 w-4" /> Save changes
          </Button>
          {err && <p className="text-sm text-red-600">{err}</p>}
        </div>
      </form>
    </Card>
  );
}

function ReadOnlyField({
  label,
  value,
  multiline,
}: {
  label: string;
  value: string;
  multiline?: boolean;
}) {
  return (
    <div>
      <p className="text-xs uppercase text-gray-500">{label}</p>
      <p
        className={
          "mt-1 text-sm text-gray-900 " +
          (multiline ? "whitespace-pre-wrap" : "")
        }
      >
        {value}
      </p>
    </div>
  );
}

function EditField({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-1">
        {label}
      </label>
      {children}
    </div>
  );
}

// ── Documents list + archive / hard-delete controls ────────────────────────

function DocumentsSection({ profile }: { profile: ProfileDetail }) {
  // Group docs by type for a cleaner display. Archived docs come at
  // the end regardless of type.
  const groups = useMemo(() => {
    const active: Record<string, ProfileDocument[]> = {};
    const archived: ProfileDocument[] = [];
    for (const d of profile.documents) {
      if (d.archived_at) archived.push(d);
      else {
        (active[d.doc_type] = active[d.doc_type] || []).push(d);
      }
    }
    return { active, archived };
  }, [profile.documents]);

  const activeCount = Object.values(groups.active).reduce(
    (sum, arr) => sum + arr.length,
    0
  );

  return (
    <Card>
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-900">
          Documents ({activeCount} active
          {groups.archived.length > 0
            ? `, ${groups.archived.length} archived`
            : ""}
          )
        </h2>
      </div>

      {profile.documents.length === 0 ? (
        <p className="py-8 text-center text-sm text-gray-500">
          No documents uploaded yet. Use the form below to add Aadhaar, PAN,
          or any other KYC document.
        </p>
      ) : (
        <div className="space-y-2">
          {DOC_TYPE_ORDER.map((t) => {
            const docs = groups.active[t] || [];
            if (docs.length === 0) return null;
            return (
              <div key={t}>
                <p className="mb-1 text-xs font-semibold uppercase text-gray-500">
                  {DOC_TYPE_LABELS[t]}
                </p>
                <div className="space-y-1">
                  {docs.map((d) => (
                    <DocRow key={d.id} doc={d} profileId={profile.id} />
                  ))}
                </div>
              </div>
            );
          })}
          {groups.archived.length > 0 && (
            <div className="pt-4 border-t border-gray-100">
              <p className="mb-1 text-xs font-semibold uppercase text-gray-400">
                Archived
              </p>
              <div className="space-y-1">
                {groups.archived.map((d) => (
                  <DocRow
                    key={d.id}
                    doc={d}
                    profileId={profile.id}
                    archived
                  />
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

function DocRow({
  doc,
  profileId,
  archived,
}: {
  doc: ProfileDocument;
  profileId: string;
  archived?: boolean;
}) {
  const queryClient = useQueryClient();
  const [confirmHard, setConfirmHard] = useState(false);

  const softArchive = useMutation({
    mutationFn: () => archiveProfileDocument(profileId, doc.id),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["profile", profileId] }),
  });

  const hardDelete = useMutation({
    mutationFn: () => archiveProfileDocument(profileId, doc.id, { hard: true }),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["profile", profileId] }),
  });

  const sizeKb = (doc.size_bytes / 1024).toFixed(1);
  const downloadUrl = profileDocumentDownloadUrl(profileId, doc.id);

  return (
    <div
      className={
        "flex items-center justify-between rounded border border-gray-100 bg-gray-50/50 px-3 py-2 text-sm " +
        (archived ? "opacity-60" : "")
      }
    >
      <div className="flex min-w-0 items-center gap-3">
        <FileText className="h-4 w-4 flex-shrink-0 text-gray-400" />
        <div className="min-w-0">
          <p className="truncate font-medium text-gray-900">
            {doc.doc_label || doc.filename}
          </p>
          <p className="text-xs text-gray-500">
            {doc.filename} · {doc.file_type.toUpperCase()} · {sizeKb} KB
            {" · "}
            {new Date(doc.uploaded_at).toLocaleDateString()}
          </p>
        </div>
      </div>
      <div className="flex flex-shrink-0 items-center gap-1">
        {/* Anchor download — browser handles the stream + save. */}
        <a
          href={downloadUrl}
          className="rounded p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
          title="Download"
        >
          <Download className="h-4 w-4" />
        </a>
        {!archived && (
          <button
            onClick={() => softArchive.mutate()}
            className="rounded p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
            title="Archive (soft delete)"
            disabled={softArchive.isPending}
          >
            <Archive className="h-4 w-4" />
          </button>
        )}
        {confirmHard ? (
          <div className="flex items-center gap-1">
            <button
              onClick={() => hardDelete.mutate()}
              className="rounded p-1.5 text-red-600 hover:bg-red-50"
              title="Confirm permanent delete (GDPR erasure)"
            >
              <Check className="h-4 w-4" />
            </button>
            <button
              onClick={() => setConfirmHard(false)}
              className="rounded p-1.5 text-gray-400 hover:bg-gray-100"
              title="Cancel"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        ) : (
          <button
            onClick={() => setConfirmHard(true)}
            className="rounded p-1.5 text-gray-400 hover:bg-red-50 hover:text-red-600"
            title="Hard delete (erase file + row)"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        )}
      </div>
    </div>
  );
}

// ── Upload form ─────────────────────────────────────────────────────────────

function UploadSection({
  profileId,
  archived,
}: {
  profileId: string;
  archived: boolean;
}) {
  const queryClient = useQueryClient();
  const [docType, setDocType] = useState<ProfileDocType>("aadhaar");
  const [docLabel, setDocLabel] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const upload = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error("Pick a file first.");
      if (file.size > MAX_DOC_BYTES) {
        throw new Error(
          `File is too large (${(file.size / 1024 / 1024).toFixed(
            1
          )} MB). Limit is 20 MB.`
        );
      }
      if (docType === "other" && !docLabel.trim()) {
        throw new Error(
          'The "Other" type needs a label so you can identify the file later.'
        );
      }
      return uploadProfileDocument(profileId, file, docType, docLabel);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["profile", profileId] });
      setFile(null);
      setDocLabel("");
      setErr(null);
    },
    onError: (e: any) => setErr(e?.message || "Upload failed"),
  });

  if (archived) {
    return null;
  }

  return (
    <Card>
      <h2 className="mb-4 text-lg font-semibold text-gray-900">
        Upload document
      </h2>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          upload.mutate();
        }}
        className="grid grid-cols-1 gap-4 sm:grid-cols-2"
      >
        <EditField label="Document type">
          <select
            className="input w-full"
            value={docType}
            onChange={(e) => setDocType(e.target.value as ProfileDocType)}
          >
            {DOC_TYPE_ORDER.map((t) => (
              <option key={t} value={t}>
                {DOC_TYPE_LABELS[t]}
              </option>
            ))}
          </select>
        </EditField>
        <EditField
          label={
            docType === "other"
              ? "Label (required for Other)"
              : "Label (optional)"
          }
        >
          <input
            className="input w-full"
            placeholder="e.g. Aadhaar front + back"
            value={docLabel}
            onChange={(e) => setDocLabel(e.target.value)}
          />
        </EditField>
        <div className="sm:col-span-2">
          <EditField label="File (PDF, JPG, PNG, HEIC, or DOCX — max 20 MB)">
            <input
              type="file"
              accept={ACCEPT_ATTR}
              onChange={(e) => setFile(e.target.files?.[0] || null)}
              className="block w-full text-sm text-gray-700 file:mr-3 file:rounded file:border-0 file:bg-primary-50 file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-primary-700 hover:file:bg-primary-100"
            />
          </EditField>
        </div>
        <div className="sm:col-span-2 flex items-center gap-3">
          <Button
            type="submit"
            variant="primary"
            loading={upload.isPending}
            disabled={!file}
          >
            <Upload className="mr-1.5 h-4 w-4" /> Upload
          </Button>
          {file && (
            <span className="text-xs text-gray-500">
              Selected: {file.name} · {(file.size / 1024).toFixed(1)} KB
            </span>
          )}
          {err && <p className="text-sm text-red-600">{err}</p>}
        </div>
      </form>
    </Card>
  );
}

// ── Shared empty / permission-denied states ────────────────────────────────

function PermissionDenied() {
  return (
    <EmptyState
      Icon={Lock}
      title="Permission denied"
      body="The profile docs vault is restricted to admins and super admins."
    />
  );
}

function EmptyState({
  title,
  body,
  Icon = Lock,
}: {
  title: string;
  body: string;
  Icon?: React.ElementType;
}) {
  return (
    <div className="space-y-6">
      <div>
        <Link
          to="/profiles"
          className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700"
        >
          <ArrowLeft className="h-4 w-4" /> Back to profiles
        </Link>
      </div>
      <Card>
        <div className="flex flex-col items-center py-16 text-center">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-amber-100">
            <Icon className="h-6 w-6 text-amber-600" />
          </div>
          <p className="mt-4 text-base font-semibold text-gray-900">{title}</p>
          <p className="mt-1 max-w-md text-sm text-gray-500">{body}</p>
        </div>
      </Card>
    </div>
  );
}
