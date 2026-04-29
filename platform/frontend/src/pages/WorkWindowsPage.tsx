import { useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Clock,
  CheckCircle2,
  XCircle,
  Inbox,
  Save,
  ShieldCheck,
  Power,
} from "lucide-react";

import { Card } from "@/components/Card";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { BackendErrorBanner } from "@/components/BackendErrorBanner";
import {
  getUsers,
  adminGetUserWorkWindow,
  adminUpdateUserWorkWindow,
  adminSetUserOverride,
  adminListExtensionRequests,
  adminDecideExtensionRequest,
} from "@/lib/api";
import type {
  ManagedUser,
  WorkWindowState,
  WorkTimeExtensionRequest,
} from "@/lib/types";

/**
 * Admin / super_admin: per-user IST work-window configuration +
 * extension-request review queue.
 *
 * Two cards, one page:
 *
 *   1. Pending requests — table with approve/deny actions. Default
 *      filter is "pending" so the empty state on a quiet day is
 *      "no requests".
 *   2. User windows — one row per non-admin user; inline editor for
 *      enabled / start / end. Each row also surfaces the live
 *      ``within_window_now`` so the admin sees who's currently locked
 *      out at a glance.
 */
export function WorkWindowsPage() {
  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-amber-100">
          <ShieldCheck className="h-5 w-5 text-amber-700" />
        </div>
        <div>
          <h1 className="text-2xl font-bold text-neutral-900">Work-time windows</h1>
          <p className="text-sm text-neutral-500">
            Set per-user IST shifts, grant one-off overrides, and review
            extension requests.
          </p>
        </div>
      </div>

      <ExtensionRequestsCard />
      <UserWindowsCard />
    </div>
  );
}

// ─── Extension requests queue ─────────────────────────────────────

function ExtensionRequestsCard() {
  const queryClient = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<
    "pending" | "approved" | "denied" | "all"
  >("pending");

  const requestsQ = useQuery({
    queryKey: ["admin-extension-requests", statusFilter],
    queryFn: () => adminListExtensionRequests(statusFilter),
    refetchInterval: 30_000, // catch new requests fast
  });

  const decideMutation = useMutation({
    mutationFn: (vars: {
      id: string;
      decision: "approved" | "denied";
      note: string;
    }) => adminDecideExtensionRequest(vars.id, vars.decision, vars.note),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-extension-requests"] });
      // Also invalidate per-user windows — an approve bumps the
      // override and the admin may have the user's row open.
      queryClient.invalidateQueries({ queryKey: ["admin-user-window"] });
    },
  });

  return (
    <Card>
      <div className="mb-3 flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-base font-semibold text-neutral-900">
          <Inbox className="h-4 w-4 text-blue-600" />
          Extension requests
        </h2>
        <div className="flex gap-1">
          {(["pending", "approved", "denied", "all"] as const).map((s) => (
            <button
              key={s}
              onClick={() => setStatusFilter(s)}
              className={`rounded px-2.5 py-1 text-xs ${
                statusFilter === s
                  ? "bg-primary-100 font-medium text-primary-700"
                  : "bg-neutral-100 text-neutral-600 hover:bg-neutral-200"
              }`}
            >
              {s.charAt(0).toUpperCase() + s.slice(1)}
            </button>
          ))}
        </div>
      </div>

      <BackendErrorBanner queries={[requestsQ]} />

      {requestsQ.isLoading ? (
        <div className="py-6 text-center text-sm text-neutral-400">Loading…</div>
      ) : (requestsQ.data?.items.length ?? 0) === 0 ? (
        <div className="py-6 text-center text-sm text-neutral-400 italic">
          No {statusFilter} requests.
        </div>
      ) : (
        <ul className="divide-y divide-neutral-100">
          {requestsQ.data!.items.map((req) => (
            <RequestRow
              key={req.id}
              req={req}
              onDecide={(decision, note) =>
                decideMutation.mutate({ id: req.id, decision, note })
              }
              busy={decideMutation.isPending}
            />
          ))}
        </ul>
      )}
    </Card>
  );
}

function RequestRow({
  req,
  onDecide,
  busy,
}: {
  req: WorkTimeExtensionRequest;
  onDecide: (decision: "approved" | "denied", note: string) => void;
  busy: boolean;
}) {
  const [showNote, setShowNote] = useState(false);
  const [note, setNote] = useState("");
  const isPending = req.status === "pending";

  return (
    <li className="py-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <p className="truncate text-sm font-medium text-neutral-900">
              {req.user_name}
            </p>
            <span className="text-xs text-neutral-500">{req.user_email}</span>
            {req.status === "approved" && (
              <Badge variant="success">approved</Badge>
            )}
            {req.status === "denied" && <Badge variant="danger">denied</Badge>}
            {req.status === "pending" && (
              <Badge variant="warning">pending</Badge>
            )}
          </div>
          <p className="mt-1 text-xs text-neutral-600">
            <span className="font-medium">{req.requested_minutes} min</span>
            {" · "}
            <span title={new Date(req.requested_at).toLocaleString()}>
              {timeAgo(req.requested_at)}
            </span>
            {req.reason && ` · "${req.reason}"`}
          </p>
          {req.status === "approved" && req.approved_until && (
            <p className="mt-0.5 text-xs text-emerald-700">
              Override valid until{" "}
              {new Date(req.approved_until).toLocaleString()}
            </p>
          )}
          {req.decision_note && (
            <p className="mt-0.5 text-xs italic text-neutral-500">
              Admin note: {req.decision_note}
            </p>
          )}
        </div>
        {isPending && (
          <div className="flex flex-col gap-1">
            <Button
              size="sm"
              variant="primary"
              loading={busy}
              onClick={() => onDecide("approved", note)}
            >
              <CheckCircle2 className="mr-1 h-3 w-3" /> Approve
            </Button>
            <Button
              size="sm"
              variant="ghost"
              loading={busy}
              onClick={() => onDecide("denied", note)}
            >
              <XCircle className="mr-1 h-3 w-3" /> Deny
            </Button>
            <button
              onClick={() => setShowNote(!showNote)}
              className="text-[10px] text-neutral-500 underline hover:text-neutral-700"
            >
              {showNote ? "Hide" : "Add"} note
            </button>
          </div>
        )}
      </div>
      {showNote && isPending && (
        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value.slice(0, 500))}
          placeholder="Optional note that the requester sees…"
          rows={2}
          className="mt-2 w-full rounded border border-neutral-200 p-2 text-xs"
        />
      )}
    </li>
  );
}

// ─── Per-user window editor ───────────────────────────────────────

function UserWindowsCard() {
  const usersQ = useQuery({ queryKey: ["users"], queryFn: getUsers });

  // Only show non-admins — admins are exempt at the backend, listing
  // them here would be misleading. Keep super_admin/admin out of the
  // editable surface.
  const targets = useMemo<ManagedUser[]>(
    () =>
      (usersQ.data?.items ?? []).filter(
        (u) => u.role !== "admin" && u.role !== "super_admin",
      ),
    [usersQ.data],
  );

  return (
    <Card>
      <h2 className="mb-3 flex items-center gap-2 text-base font-semibold text-neutral-900">
        <Clock className="h-4 w-4 text-primary-600" />
        User shifts
      </h2>
      <BackendErrorBanner queries={[usersQ]} />
      {usersQ.isLoading ? (
        <div className="py-6 text-center text-sm text-neutral-400">Loading…</div>
      ) : targets.length === 0 ? (
        <p className="py-6 text-center text-sm text-neutral-400 italic">
          No reviewer / viewer accounts to configure.
        </p>
      ) : (
        <ul className="divide-y divide-neutral-100">
          {targets.map((u) => (
            <UserWindowRow key={u.id} user={u} />
          ))}
        </ul>
      )}
    </Card>
  );
}

function UserWindowRow({ user }: { user: ManagedUser }) {
  const queryClient = useQueryClient();
  const stateQ = useQuery({
    queryKey: ["admin-user-window", user.id],
    queryFn: () => adminGetUserWorkWindow(user.id),
    // 60s — the badge ("in window now / locked out") needs to flip
    // as time crosses the boundary.
    refetchInterval: 60_000,
  });

  const updateMutation = useMutation({
    mutationFn: (payload: {
      enabled?: boolean;
      start_ist?: string;
      end_ist?: string;
    }) => adminUpdateUserWorkWindow(user.id, payload),
    onSuccess: (data) => {
      queryClient.setQueryData(["admin-user-window", user.id], data);
    },
  });

  const overrideMutation = useMutation({
    mutationFn: (overrideUntil: string | null) =>
      adminSetUserOverride(user.id, overrideUntil),
    onSuccess: (data) => {
      queryClient.setQueryData(["admin-user-window", user.id], data);
    },
  });

  const state: WorkWindowState | undefined = stateQ.data;
  // Local edits — committed on Save, so toggling the time inputs
  // doesn't fire a PATCH on every keystroke.
  const [draftStart, setDraftStart] = useState<string | null>(null);
  const [draftEnd, setDraftEnd] = useState<string | null>(null);

  if (stateQ.isLoading || !state) {
    return (
      <li className="py-3 text-xs text-neutral-400">Loading {user.email}…</li>
    );
  }

  const startVal = draftStart ?? state.start_ist;
  const endVal = draftEnd ?? state.end_ist;
  const dirty =
    (draftStart !== null && draftStart !== state.start_ist) ||
    (draftEnd !== null && draftEnd !== state.end_ist);

  return (
    <li className="py-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <p className="truncate text-sm font-medium text-neutral-900">
              {user.name}
            </p>
            <span className="text-xs text-neutral-500">{user.email}</span>
            <Badge variant="default">{user.role}</Badge>
            {state.enabled ? (
              state.within_window_now ? (
                <Badge variant="success">in window</Badge>
              ) : (
                <Badge variant="danger">locked out</Badge>
              )
            ) : (
              <Badge variant="default">unrestricted</Badge>
            )}
          </div>

          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
            <label className="inline-flex items-center gap-1">
              <input
                type="checkbox"
                checked={state.enabled}
                onChange={(e) =>
                  updateMutation.mutate({ enabled: e.target.checked })
                }
                disabled={updateMutation.isPending}
              />
              Enforce
            </label>

            <span className="text-neutral-400">·</span>

            <label className="inline-flex items-center gap-1">
              <span className="text-neutral-500">Start (IST)</span>
              <input
                type="time"
                value={startVal}
                onChange={(e) => setDraftStart(e.target.value)}
                disabled={!state.enabled || updateMutation.isPending}
                className="rounded border border-neutral-200 px-1 py-0.5"
              />
            </label>
            <label className="inline-flex items-center gap-1">
              <span className="text-neutral-500">End (IST)</span>
              <input
                type="time"
                value={endVal}
                onChange={(e) => setDraftEnd(e.target.value)}
                disabled={!state.enabled || updateMutation.isPending}
                className="rounded border border-neutral-200 px-1 py-0.5"
              />
            </label>
            {dirty && (
              <Button
                size="sm"
                variant="primary"
                loading={updateMutation.isPending}
                onClick={() =>
                  updateMutation.mutate(
                    {
                      start_ist: startVal,
                      end_ist: endVal,
                    },
                    {
                      onSuccess: () => {
                        setDraftStart(null);
                        setDraftEnd(null);
                      },
                    },
                  )
                }
              >
                <Save className="mr-1 h-3 w-3" /> Save
              </Button>
            )}
          </div>

          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
            {state.override_until ? (
              <>
                <span className="text-emerald-700">
                  Override until{" "}
                  {new Date(state.override_until).toLocaleString()}
                </span>
                <button
                  className="text-neutral-500 underline hover:text-neutral-700"
                  onClick={() => overrideMutation.mutate(null)}
                  disabled={overrideMutation.isPending}
                >
                  Clear
                </button>
              </>
            ) : (
              <>
                <span className="text-neutral-500">Quick extend:</span>
                {[30, 60, 120].map((n) => (
                  <button
                    key={n}
                    onClick={() =>
                      overrideMutation.mutate(
                        new Date(Date.now() + n * 60_000).toISOString(),
                      )
                    }
                    disabled={overrideMutation.isPending}
                    className="rounded border border-neutral-200 px-2 py-0.5 hover:bg-neutral-50"
                  >
                    +{n} min
                  </button>
                ))}
              </>
            )}
          </div>
        </div>
        <button
          onClick={() => stateQ.refetch()}
          className="text-neutral-400 hover:text-neutral-600"
          title="Refresh state"
        >
          <Power className="h-3.5 w-3.5" />
        </button>
      </div>
    </li>
  );
}

// ─── Helpers ──────────────────────────────────────────────────────

function timeAgo(iso: string): string {
  const sec = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (sec < 60) return "just now";
  const m = Math.round(sec / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.round(h / 24)}d ago`;
}
