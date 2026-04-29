import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Lock,
  Clock,
  Send,
  CheckCircle2,
  XCircle,
  AlertCircle,
} from "lucide-react";

import { useAuth } from "@/lib/auth";
import {
  getMyWorkWindow,
  createMyExtensionRequest,
  listMyExtensionRequests,
} from "@/lib/api";

/**
 * Work-time enforcement at the layout level.
 *
 * Behaviour:
 *   - Polls ``/work-window/me`` every 60s for non-admin users so the
 *     UI flips to the lock-out screen at the moment the window
 *     closes (or re-opens after admin extends/approves a request)
 *     without a manual refresh.
 *   - When ``within_window_now === false``, replaces the entire
 *     children subtree with a full-page lock screen carrying:
 *       * the user's window times,
 *       * a live countdown to next opening,
 *       * a "request extension" form,
 *       * the user's most recent decision (so a denied request shows
 *         its note instead of letting them re-submit blindly).
 *   - Admins / super_admins are exempt — backend already short-
 *     circuits, but the frontend short-circuits too so we don't
 *     spam ``/work-window/me`` requests for them.
 *
 * The component is mounted inside ``ProtectedLayout`` so anonymous
 * traffic and the login page are unaffected.
 */
export function WorkWindowGate({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin" || user?.role === "super_admin";

  // Skip the query entirely for admins — they're exempt at the
  // backend, polling would just burn cycles.
  const stateQ = useQuery({
    queryKey: ["my-work-window"],
    queryFn: getMyWorkWindow,
    enabled: !!user && !isAdmin,
    // 60s poll. When the user is locked out we want to know quickly
    // when admin grants a re-entry; when they're working we want to
    // catch the close-time without needing a tab focus event.
    refetchInterval: 60_000,
    // Refetch on window focus so a user returning to the tab after
    // a coffee break sees the right state immediately.
    refetchOnWindowFocus: true,
    staleTime: 30_000,
  });

  // While the very first ``/work-window/me`` is in flight on app
  // load, render children (don't flash a lock screen) — the backend
  // will 423 any request that's actually outside the window, and
  // TanStack Query will catch up within a tick. Avoids a flicker on
  // every refresh for users inside their window.
  if (!user || isAdmin || stateQ.isLoading || !stateQ.data) {
    return <>{children}</>;
  }

  if (stateQ.data.within_window_now) {
    return <>{children}</>;
  }

  return <LockedOutScreen />;
}

// ─── Lock-out screen ──────────────────────────────────────────────

function LockedOutScreen() {
  const queryClient = useQueryClient();
  const stateQ = useQuery({
    queryKey: ["my-work-window"],
    queryFn: getMyWorkWindow,
  });
  const requestsQ = useQuery({
    queryKey: ["my-extension-requests"],
    // Limit to the most recent — we just want to surface "your last
    // request was {pending|approved|denied}". Page 1 of 5 is plenty.
    queryFn: () => listMyExtensionRequests(1, 5),
  });

  const [minutes, setMinutes] = useState(30);
  const [reason, setReason] = useState("");
  const [submitError, setSubmitError] = useState<string | null>(null);

  const requestMutation = useMutation({
    mutationFn: () =>
      createMyExtensionRequest({
        requested_minutes: minutes,
        reason: reason.trim(),
      }),
    onSuccess: () => {
      setSubmitError(null);
      setReason("");
      // Refetch both — the new pending request should show up in
      // the history list, and the window state may flip if the
      // admin auto-approves at policy level later.
      queryClient.invalidateQueries({ queryKey: ["my-extension-requests"] });
      queryClient.invalidateQueries({ queryKey: ["my-work-window"] });
    },
    onError: (e: unknown) => {
      // 409 = already pending — backend's anti-spam guard. Surface
      // the message rather than swallowing it.
      const msg =
        e instanceof Error
          ? e.message
          : "Could not submit your request. Try again in a moment.";
      setSubmitError(msg);
    },
  });

  // Live "minutes until window opens" ticker. Uses the server clock
  // (``server_now_utc``) anchored at the last fetch and ticks
  // forward locally so we don't hammer ``/work-window/me`` every
  // second. The 60s parent poll re-anchors automatically.
  const tick = useTick(stateQ.data?.server_now_utc);

  if (stateQ.isLoading || !stateQ.data) {
    return (
      <div className="flex h-screen items-center justify-center text-sm text-gray-500">
        Loading…
      </div>
    );
  }

  const state = stateQ.data;
  const pendingRequest = requestsQ.data?.items.find(
    (r) => r.status === "pending",
  );
  const lastDecided = requestsQ.data?.items.find(
    (r) => r.status !== "pending",
  );

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-slate-50 to-slate-100 p-6">
      <div className="w-full max-w-xl rounded-xl bg-white p-8 shadow-lg ring-1 ring-slate-200">
        <div className="flex items-center gap-3">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-amber-100">
            <Lock className="h-6 w-6 text-amber-700" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-slate-900">
              Outside your work window
            </h1>
            <p className="text-sm text-slate-500">
              Your shift is set by an admin. Come back during the window
              below, or request an extension.
            </p>
          </div>
        </div>

        {/* Window summary */}
        <div className="mt-6 rounded-lg border border-slate-200 bg-slate-50 p-4">
          <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-slate-500">
            <Clock className="h-3.5 w-3.5" />
            Your shift (IST)
          </div>
          <div className="mt-1 text-lg font-semibold text-slate-900">
            {state.start_ist} — {state.end_ist}
          </div>
          <p className="mt-2 text-xs text-slate-500">
            Server time: {new Date(tick).toUTCString()}
          </p>
          {state.override_until && (
            <p className="mt-1 text-xs text-emerald-700">
              Active extension until{" "}
              {new Date(state.override_until).toLocaleString()}
            </p>
          )}
        </div>

        {/* Last decided request — close the loop on what admin said */}
        {lastDecided && (
          <div
            className={`mt-4 rounded-lg border p-3 text-xs ${
              lastDecided.status === "approved"
                ? "border-emerald-200 bg-emerald-50 text-emerald-800"
                : "border-red-200 bg-red-50 text-red-800"
            }`}
          >
            <div className="flex items-center gap-1.5 font-medium">
              {lastDecided.status === "approved" ? (
                <CheckCircle2 className="h-3.5 w-3.5" />
              ) : (
                <XCircle className="h-3.5 w-3.5" />
              )}
              Your last request was {lastDecided.status}
              {lastDecided.status === "approved" &&
                lastDecided.approved_until &&
                ` until ${new Date(lastDecided.approved_until).toLocaleTimeString()}`}
              .
            </div>
            {lastDecided.decision_note && (
              <p className="mt-1">Note from admin: {lastDecided.decision_note}</p>
            )}
          </div>
        )}

        {/* Pending request — show but don't allow another */}
        {pendingRequest ? (
          <div className="mt-4 rounded-lg border border-blue-200 bg-blue-50 p-3 text-xs text-blue-800">
            <div className="flex items-center gap-1.5 font-medium">
              <AlertCircle className="h-3.5 w-3.5" />
              Request pending — {pendingRequest.requested_minutes} min
            </div>
            <p className="mt-1 text-blue-700/80">
              Submitted{" "}
              {new Date(pendingRequest.requested_at).toLocaleString()}.
              Wait for an admin to approve or deny.
            </p>
          </div>
        ) : (
          <ExtensionRequestForm
            minutes={minutes}
            setMinutes={setMinutes}
            reason={reason}
            setReason={setReason}
            submitting={requestMutation.isPending}
            error={submitError}
            onSubmit={() => {
              setSubmitError(null);
              requestMutation.mutate();
            }}
          />
        )}

        <div className="mt-6 flex items-center justify-between text-xs text-slate-400">
          <span>Logged in as {/* user name from auth */}</span>
          <a
            href="/api/v1/auth/logout"
            className="hover:text-slate-600 underline"
            onClick={(e) => {
              e.preventDefault();
              // Hard-nav to the login page; backend logout endpoint is
              // POST so we use a fetch then redirect. Cheap to inline
              // here rather than wire through useAuth.
              fetch("/api/v1/auth/logout", {
                method: "POST",
                credentials: "include",
              }).finally(() => {
                window.location.assign("/login");
              });
            }}
          >
            Sign out
          </a>
        </div>
      </div>
    </div>
  );
}

function ExtensionRequestForm({
  minutes,
  setMinutes,
  reason,
  setReason,
  submitting,
  error,
  onSubmit,
}: {
  minutes: number;
  setMinutes: (n: number) => void;
  reason: string;
  setReason: (s: string) => void;
  submitting: boolean;
  error: string | null;
  onSubmit: () => void;
}) {
  return (
    <form
      className="mt-5 space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
    >
      <div>
        <label className="block text-xs font-medium text-slate-700">
          How much extra time do you need?
        </label>
        <div className="mt-1 flex items-center gap-2">
          {[15, 30, 60, 120].map((n) => (
            <button
              key={n}
              type="button"
              onClick={() => setMinutes(n)}
              className={`rounded-md border px-2.5 py-1 text-xs font-medium ${
                minutes === n
                  ? "border-primary-500 bg-primary-50 text-primary-700"
                  : "border-slate-200 text-slate-600 hover:bg-slate-50"
              }`}
            >
              {n} min
            </button>
          ))}
          <input
            type="number"
            min={15}
            max={240}
            value={minutes}
            onChange={(e) =>
              setMinutes(
                Math.max(15, Math.min(240, Number(e.target.value) || 30)),
              )
            }
            className="w-20 rounded-md border border-slate-200 px-2 py-1 text-xs"
          />
          <span className="text-xs text-slate-400">15 – 240</span>
        </div>
      </div>
      <div>
        <label className="block text-xs font-medium text-slate-700">
          Reason (optional)
        </label>
        <textarea
          value={reason}
          onChange={(e) => setReason(e.target.value.slice(0, 500))}
          rows={2}
          placeholder="What are you finishing up?"
          className="mt-1 w-full rounded-md border border-slate-200 p-2 text-xs"
        />
      </div>
      {error && (
        <p className="rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">
          {error}
        </p>
      )}
      <button
        type="submit"
        disabled={submitting}
        className="inline-flex items-center gap-1.5 rounded-md bg-primary-600 px-3 py-2 text-sm font-medium text-white hover:bg-primary-700 disabled:opacity-50"
      >
        <Send className="h-3.5 w-3.5" />
        {submitting ? "Sending…" : "Request extension"}
      </button>
    </form>
  );
}

// ─── Helpers ──────────────────────────────────────────────────────

/**
 * Re-render every second so the on-screen "it is now …" timestamp
 * stays current without re-fetching ``/work-window/me``. Anchored on
 * ``server_now_utc`` so client clock skew doesn't mislead the user.
 */
function useTick(serverNowUtc: string | undefined): number {
  const [now, setNow] = useState<number>(() =>
    serverNowUtc ? new Date(serverNowUtc).getTime() : Date.now(),
  );
  useEffect(() => {
    if (serverNowUtc) {
      setNow(new Date(serverNowUtc).getTime());
    }
    const id = setInterval(() => setNow((t) => t + 1000), 1000);
    return () => clearInterval(id);
  }, [serverNowUtc]);
  return now;
}
