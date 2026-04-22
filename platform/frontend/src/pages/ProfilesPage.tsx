/**
 * Admin-only KYC profile docs vault — list view.
 *
 * Shows every profile stored in the platform's PII vault (Aadhaar,
 * PAN, marksheets, bank / PF proof). Backend gates the endpoint on
 * `require_role("admin")` so `reviewer` / `viewer` see a 403 that this
 * page rewrites into a permission-denied state. Clicking a row opens
 * the detail page where docs are uploaded / downloaded / archived.
 *
 * Conventions (match other admin list pages like UserManagementPage):
 *   - TanStack Query for fetching, optimistic-ish invalidation on
 *     mutation success.
 *   - Inline create form (no modal) — simpler to debug and matches
 *     AnswerBookPage.
 *   - No PII values in the audit logs on the backend; this page
 *     mirrors that by not echoing UAN / PF fragments in error
 *     messages either.
 */
import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  UserPlus,
  Search,
  Lock,
  FileText,
  Archive,
  Shield,
} from "lucide-react";

import { Card } from "@/components/Card";
import { Button } from "@/components/Button";
import {
  listProfiles,
  createProfile,
} from "@/lib/api";
import type { Profile, ProfileCreatePayload } from "@/lib/types";

const PAGE_SIZE = 25;

const EMPTY_FORM: ProfileCreatePayload = {
  name: "",
  email: "",
  dob: "",
  father_name: "",
  uan_number: "",
  pf_number: "",
  notes: "",
};

export function ProfilesPage() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [includeArchived, setIncludeArchived] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState<ProfileCreatePayload>(EMPTY_FORM);
  const [createError, setCreateError] = useState<string | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["profiles", { search, page, includeArchived }],
    queryFn: () =>
      listProfiles({
        search: search.trim() || undefined,
        page,
        page_size: PAGE_SIZE,
        include_archived: includeArchived || undefined,
      }),
    retry: (failureCount, err: any) => {
      // 403 is a role issue — retrying won't fix it.
      if (err?.status === 403) return false;
      return failureCount < 3;
    },
  });

  const createMutation = useMutation({
    mutationFn: async (payload: ProfileCreatePayload) => {
      // Backend rejects empty-string dob ("Input should be a valid date").
      // Normalise before send so the form can keep a controlled-input
      // empty string without poking the API contract.
      const clean: ProfileCreatePayload = {
        name: payload.name.trim(),
        email: payload.email.trim(),
        dob: payload.dob || null,
        father_name: payload.father_name?.trim() || null,
        uan_number: payload.uan_number?.trim() || null,
        pf_number: payload.pf_number?.trim() || null,
        notes: payload.notes?.trim() || "",
      };
      return createProfile(clean);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["profiles"] });
      setShowCreate(false);
      setForm(EMPTY_FORM);
      setCreateError(null);
    },
    onError: (err: any) => {
      setCreateError(err?.message || "Failed to create profile");
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

  if (error) {
    return (
      <div className="space-y-6">
        <PageHeader />
        <Card>
          <div className="py-16 text-center">
            <p className="text-sm font-medium text-red-600">
              Failed to load profiles
            </p>
            <p className="mt-1 text-xs text-gray-500">
              {(error as Error).message}
            </p>
          </div>
        </Card>
      </div>
    );
  }

  const profiles = data?.items ?? [];
  const total = data?.total ?? 0;
  const totalPages = data?.total_pages ?? 1;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <PageHeader />
        <Button variant="primary" onClick={() => setShowCreate((v) => !v)}>
          <UserPlus className="mr-2 h-4 w-4" />
          {showCreate ? "Close form" : "New profile"}
        </Button>
      </div>

      {/* KYC / compliance banner — this data is regulated. Unlike the
          rest of the platform, every read here is audit-logged. */}
      <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900 flex items-start gap-3">
        <Shield className="mt-0.5 h-5 w-5 flex-shrink-0 text-amber-600" />
        <div>
          <p className="font-medium">
            Regulated PII — every access is audit-logged
          </p>
          <p className="mt-1 text-xs text-amber-800/80">
            Profiles here contain government IDs (Aadhaar / PAN), financial
            records, and nominee proof. Access is restricted to admins &amp;
            super admins. Upload only documents you have the right to store
            and process under DPDP Act 2023 / GDPR.
          </p>
        </div>
      </div>

      {showCreate && (
        <Card>
          <h3 className="text-base font-semibold text-gray-900 mb-4">
            Create new profile
          </h3>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              createMutation.mutate(form);
            }}
            className="grid grid-cols-1 gap-4 sm:grid-cols-2"
          >
            <Field label="Name *">
              <input
                required
                maxLength={200}
                className="input w-full"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
              />
            </Field>
            <Field label="Email *">
              <input
                type="email"
                required
                className="input w-full"
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
              />
            </Field>
            <Field label="Date of birth">
              <input
                type="date"
                className="input w-full"
                value={form.dob || ""}
                onChange={(e) => setForm({ ...form, dob: e.target.value })}
              />
            </Field>
            <Field label="Father's name">
              <input
                maxLength={200}
                className="input w-full"
                value={form.father_name || ""}
                onChange={(e) => setForm({ ...form, father_name: e.target.value })}
              />
            </Field>
            <Field label="UAN number">
              <input
                maxLength={40}
                className="input w-full"
                placeholder="12-digit UAN"
                value={form.uan_number || ""}
                onChange={(e) => setForm({ ...form, uan_number: e.target.value })}
              />
            </Field>
            <Field label="PF number">
              <input
                maxLength={40}
                className="input w-full"
                value={form.pf_number || ""}
                onChange={(e) => setForm({ ...form, pf_number: e.target.value })}
              />
            </Field>
            <div className="sm:col-span-2">
              <Field label="Notes">
                <textarea
                  maxLength={5000}
                  rows={3}
                  className="input w-full"
                  value={form.notes || ""}
                  onChange={(e) => setForm({ ...form, notes: e.target.value })}
                />
              </Field>
            </div>
            <div className="sm:col-span-2 flex items-center gap-3">
              <Button
                type="submit"
                variant="primary"
                loading={createMutation.isPending}
              >
                Create profile
              </Button>
              <Button
                type="button"
                variant="secondary"
                onClick={() => {
                  setShowCreate(false);
                  setForm(EMPTY_FORM);
                  setCreateError(null);
                }}
              >
                Cancel
              </Button>
              {createError && (
                <p className="text-sm text-red-600">{createError}</p>
              )}
            </div>
          </form>
        </Card>
      )}

      {/* Search + archive toggle */}
      <Card>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="relative flex-1 max-w-md">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
            <input
              type="search"
              placeholder="Search by name or email…"
              className="input w-full pl-9"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPage(1);
              }}
            />
          </div>
          <label className="flex items-center gap-2 text-sm text-gray-700">
            <input
              type="checkbox"
              checked={includeArchived}
              onChange={(e) => {
                setIncludeArchived(e.target.checked);
                setPage(1);
              }}
            />
            Include archived
          </label>
        </div>
      </Card>

      {/* Profiles table */}
      <Card>
        {profiles.length === 0 ? (
          <div className="py-12 text-center text-sm text-gray-500">
            {search.trim()
              ? "No profiles match that search."
              : "No profiles yet. Click “New profile” to add one."}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 text-left text-xs text-gray-500 uppercase">
                  <th className="pb-3 pr-4">Name</th>
                  <th className="pb-3 pr-4">Email</th>
                  <th className="pb-3 pr-4">Docs</th>
                  <th className="pb-3 pr-4">Created</th>
                  <th className="pb-3 pr-4">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {profiles.map((p) => (
                  <ProfileRow key={p.id} profile={p} />
                ))}
              </tbody>
            </table>
          </div>
        )}

        {totalPages > 1 && (
          <div className="mt-4 flex items-center justify-between border-t border-gray-100 pt-4 text-sm">
            <p className="text-gray-500">
              {total} profile{total === 1 ? "" : "s"} · Page {page} of {totalPages}
            </p>
            <div className="flex gap-2">
              <Button
                variant="secondary"
                disabled={page <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
              >
                Previous
              </Button>
              <Button
                variant="secondary"
                disabled={page >= totalPages}
                onClick={() => setPage((p) => p + 1)}
              >
                Next
              </Button>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}

function PageHeader() {
  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900">Profile Docs Vault</h1>
      <p className="mt-1 text-sm text-gray-500">
        Store and manage regulated HR documents (Aadhaar, PAN, marksheets,
        bank &amp; PF). Admin &amp; super admin only.
      </p>
    </div>
  );
}

function PermissionDenied() {
  return (
    <div className="space-y-6">
      <PageHeader />
      <Card>
        <div className="flex flex-col items-center py-16 text-center">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-amber-100">
            <Lock className="h-6 w-6 text-amber-600" />
          </div>
          <p className="mt-4 text-base font-semibold text-gray-900">
            Permission denied
          </p>
          <p className="mt-1 max-w-md text-sm text-gray-500">
            The profile docs vault is restricted to admins and super admins.
            Contact your admin if you need access to KYC records.
          </p>
        </div>
      </Card>
    </div>
  );
}

function Field({
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

function ProfileRow({ profile }: { profile: Profile }) {
  const archived = !!profile.archived_at;
  return (
    <tr className={archived ? "opacity-60" : ""}>
      <td className="py-3 pr-4">
        <Link
          to={`/profiles/${profile.id}`}
          className="font-medium text-gray-900 hover:text-primary-600"
        >
          {profile.name}
        </Link>
        {profile.father_name && (
          <p className="text-xs text-gray-500">
            s/o {profile.father_name}
          </p>
        )}
      </td>
      <td className="py-3 pr-4 text-gray-700">{profile.email}</td>
      <td className="py-3 pr-4">
        <span className="inline-flex items-center gap-1 text-gray-600">
          <FileText className="h-4 w-4 text-gray-400" />
          {profile.document_count}
        </span>
      </td>
      <td className="py-3 pr-4 text-xs text-gray-500">
        {new Date(profile.created_at).toLocaleDateString("en-US", {
          month: "short",
          day: "numeric",
          year: "numeric",
        })}
      </td>
      <td className="py-3 pr-4">
        {archived ? (
          <span className="inline-flex items-center gap-1 rounded bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600">
            <Archive className="h-3 w-3" /> Archived
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 rounded bg-green-50 px-2 py-0.5 text-xs font-medium text-green-700">
            Active
          </span>
        )}
      </td>
    </tr>
  );
}
