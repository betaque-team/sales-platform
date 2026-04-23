import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getRoutineTopToApply,
  getKillSwitch,
  setKillSwitch,
  listRoutineRuns,
} from "@/lib/api";
import type { RoutineRun } from "@/lib/types";
import {
  ShieldAlert,
  ShieldCheck,
  Bot,
  CheckCircle2,
  XCircle,
  Clock,
  ExternalLink,
  AlertTriangle,
} from "lucide-react";
import { BackendErrorBanner } from "@/components/BackendErrorBanner";

/**
 * Claude Routine Apply — operator control panel.
 *
 * Three panels on one page:
 *   1. Pre-flight card (kill-switch + daily-cap + answer-book readiness)
 *   2. Top-to-apply — the jobs the routine would target next
 *   3. Recent runs — history with drill-down to run detail
 *
 * No "Run now" button: the routine runs as an MCP-Chrome browser
 * session driven by Claude, not as a backend task. This page just
 * tells the operator what state the routine will see when it polls.
 */

export function RoutinePage() {
  const queryClient = useQueryClient();
  const [killReason, setKillReason] = useState("");

  // Operator panel poll cadence — all three queries refresh on the same
  // 30s tick so the pre-flight card, top-to-apply list, and recent-runs
  // counters stay in sync. Previously only top-to-apply polled, which
  // left the runs list stale for minutes while a live run ticked its
  // counters forward via PATCH /routine/runs/{id}.
  const POLL_MS = 30_000;

  const topToApplyQ = useQuery({
    queryKey: ["routine-top-to-apply"],
    queryFn: () => getRoutineTopToApply(10),
    refetchInterval: POLL_MS,
  });

  const killSwitchQ = useQuery({
    queryKey: ["routine-kill-switch"],
    queryFn: getKillSwitch,
    refetchInterval: POLL_MS,
  });

  const runsQ = useQuery({
    queryKey: ["routine-runs"],
    queryFn: () => listRoutineRuns(10),
    refetchInterval: POLL_MS,
  });

  const killSwitchMutation = useMutation({
    mutationFn: (payload: { disabled: boolean; reason?: string | null }) =>
      setKillSwitch(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["routine-kill-switch"] });
      queryClient.invalidateQueries({ queryKey: ["routine-top-to-apply"] });
      setKillReason("");
    },
  });

  const topToApply = topToApplyQ.data;
  const killSwitch = killSwitchQ.data;
  const runs = runsQ.data ?? [];

  const anyError =
    topToApplyQ.isError || killSwitchQ.isError || runsQ.isError;

  // Daily-cap is amber at ≤2 remaining — "1 left" is effectively
  // exhausted for operator planning. Green at 3+, amber 1-2, amber
  // (with the "cap hit" copy) at 0.
  const dailyRemaining = topToApply?.daily_cap_remaining ?? 0;
  const dailyGood = dailyRemaining > 2;

  if (topToApplyQ.isLoading || killSwitchQ.isLoading) {
    return (
      <div className="p-8 text-sm text-neutral-500">
        Loading routine state…
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary-100">
          <Bot className="h-5 w-5 text-primary-700" />
        </div>
        <div>
          <h1 className="text-2xl font-bold text-neutral-900">
            Apply Routine
          </h1>
          <p className="text-sm text-neutral-500">
            Operator panel for the MCP-Chrome routine.
          </p>
        </div>
      </div>

      {anyError && (
        <BackendErrorBanner queries={[topToApplyQ, killSwitchQ, runsQ]} />
      )}

      {/* ── Pre-flight card ───────────────────────────────────────── */}
      <div className="rounded-lg border border-neutral-200 bg-white shadow-sm">
        <div className="border-b border-neutral-100 px-6 py-4">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-neutral-500">
            Pre-flight
          </h2>
        </div>
        <div className="grid gap-4 p-6 md:grid-cols-3">
          <PreflightCell
            label="Kill-switch"
            value={
              killSwitch?.disabled
                ? "Routine disabled"
                : "Routine active"
            }
            good={!killSwitch?.disabled}
            icon={killSwitch?.disabled ? ShieldAlert : ShieldCheck}
            detail={
              killSwitch?.disabled && killSwitch?.reason
                ? `Reason: ${killSwitch.reason}`
                : undefined
            }
          />
          <PreflightCell
            label="Answer book"
            value={
              topToApply?.answer_book_ready
                ? "Ready"
                : "Setup incomplete"
            }
            good={Boolean(topToApply?.answer_book_ready)}
            icon={
              topToApply?.answer_book_ready ? CheckCircle2 : AlertTriangle
            }
            detail={
              !topToApply?.answer_book_ready
                ? undefined
                : "All required entries filled"
            }
          >
            {!topToApply?.answer_book_ready && (
              <Link
                to="/answer-book/required-setup"
                className="text-xs font-medium text-primary-600 hover:text-primary-700 underline"
              >
                Finish setup →
              </Link>
            )}
          </PreflightCell>
          <PreflightCell
            label="Daily cap"
            value={`${dailyRemaining} / 10`}
            good={dailyGood}
            icon={Clock}
            detail={
              dailyRemaining === 0
                ? "Cap hit — live runs blocked until rollover"
                : dailyRemaining <= 2
                  ? "Almost exhausted (rolling 24h)"
                  : "Rolling 24-hour window"
            }
          />
        </div>

        {/* Kill-switch toggle */}
        <div className="border-t border-neutral-100 bg-neutral-50 px-6 py-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex-1">
              <p className="text-sm font-medium text-neutral-900">
                {killSwitch?.disabled
                  ? "Re-enable the routine"
                  : "Stop the routine immediately"}
              </p>
              <p className="text-xs text-neutral-500">
                {killSwitch?.disabled
                  ? "Clears the disabled flag and lets new runs start."
                  : "Locks the routine from starting new runs; in-flight runs abort within ~60 seconds."}
              </p>
            </div>
            <div className="flex gap-2">
              {!killSwitch?.disabled && (
                <input
                  type="text"
                  placeholder="Reason (optional)"
                  value={killReason}
                  onChange={(e) => setKillReason(e.target.value)}
                  className="w-48 rounded-md border border-neutral-300 px-3 py-1.5 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
                />
              )}
              <button
                type="button"
                onClick={() => {
                  // Re-enable flow sends reason=null; wipe local input
                  // state too so a stale "deploying new version" string
                  // doesn't sit in the textbox after the toggle flips.
                  if (killSwitch?.disabled) setKillReason("");
                  killSwitchMutation.mutate({
                    disabled: !killSwitch?.disabled,
                    reason: killSwitch?.disabled ? null : killReason || null,
                  });
                }}
                disabled={killSwitchMutation.isPending}
                className={`inline-flex items-center gap-2 rounded-md px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50 ${
                  killSwitch?.disabled
                    ? "bg-emerald-600 hover:bg-emerald-700"
                    : "bg-red-600 hover:bg-red-700"
                }`}
              >
                {killSwitch?.disabled ? (
                  <>
                    <ShieldCheck className="h-4 w-4" /> Re-enable
                  </>
                ) : (
                  <>
                    <ShieldAlert className="h-4 w-4" /> Disable routine
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* ── Top to apply ──────────────────────────────────────────── */}
      <div className="rounded-lg border border-neutral-200 bg-white shadow-sm">
        <div className="flex items-center justify-between border-b border-neutral-100 px-6 py-4">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-neutral-500">
            Next {topToApply?.jobs.length ?? 0} targets
          </h2>
          <p className="text-xs text-neutral-500">
            Ordered by relevance · Excludes LinkedIn ·{" "}
            <span className="text-neutral-700">
              30-day company cooldown applied
            </span>
          </p>
        </div>
        {!topToApply?.jobs.length ? (
          <div className="p-6 text-sm text-neutral-500">
            No jobs currently match the routine's filters. Try lowering
            the relevance cutoff in role clusters, or wait for fresh
            scrapes.
          </div>
        ) : (
          <ul className="divide-y divide-neutral-100">
            {topToApply.jobs.map((job) => (
              <li
                key={job.job_id}
                className="flex items-center justify-between px-6 py-3 hover:bg-neutral-50"
              >
                <div className="min-w-0 flex-1">
                  <Link
                    to={`/jobs/${job.job_id}`}
                    className="truncate text-sm font-medium text-neutral-900 hover:text-primary-700"
                  >
                    {job.title}
                  </Link>
                  <div className="mt-0.5 text-xs text-neutral-500">
                    <span>{job.company_name}</span>
                    <span className="mx-1.5">·</span>
                    <span>{job.platform}</span>
                    {job.geography_bucket && (
                      <>
                        <span className="mx-1.5">·</span>
                        <span>{job.geography_bucket}</span>
                      </>
                    )}
                    {job.role_cluster && (
                      <>
                        <span className="mx-1.5">·</span>
                        <span>{job.role_cluster}</span>
                      </>
                    )}
                  </div>
                </div>
                <div className="ml-4 flex-shrink-0 rounded-md bg-primary-50 px-2 py-1 text-xs font-semibold text-primary-700">
                  {Math.round(job.relevance_score)}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* ── Recent runs ───────────────────────────────────────────── */}
      <div className="rounded-lg border border-neutral-200 bg-white shadow-sm">
        <div className="border-b border-neutral-100 px-6 py-4">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-neutral-500">
            Recent runs
          </h2>
        </div>
        {!runs.length ? (
          <div className="p-6 text-sm text-neutral-500">
            No routine runs yet.
          </div>
        ) : (
          <ul className="divide-y divide-neutral-100">
            {runs.map((run) => (
              <RunListItem key={run.id} run={run} />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function PreflightCell({
  label,
  value,
  good,
  icon: Icon,
  detail,
  children,
}: {
  label: string;
  value: string;
  good: boolean;
  icon: React.ComponentType<{ className?: string }>;
  detail?: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-neutral-100 p-4">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium uppercase tracking-wide text-neutral-500">
          {label}
        </span>
        <Icon
          className={`h-4 w-4 ${
            good ? "text-emerald-500" : "text-amber-500"
          }`}
        />
      </div>
      <p
        className={`mt-1 text-lg font-semibold ${
          good ? "text-neutral-900" : "text-amber-700"
        }`}
      >
        {value}
      </p>
      {detail && <p className="mt-1 text-xs text-neutral-500">{detail}</p>}
      {children && <div className="mt-2">{children}</div>}
    </div>
  );
}

function RunListItem({ run }: { run: RoutineRun }) {
  const statusColor =
    run.status === "complete"
      ? "bg-emerald-100 text-emerald-700"
      : run.status === "aborted"
        ? "bg-red-100 text-red-700"
        : "bg-blue-100 text-blue-700";
  return (
    <li className="px-6 py-4">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span
              className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${statusColor}`}
            >
              {run.status}
            </span>
            <span className="text-xs font-medium uppercase tracking-wide text-neutral-500">
              {run.mode}
            </span>
            {run.kill_switch_triggered && (
              <span className="inline-flex items-center gap-1 rounded-full bg-red-50 px-2 py-0.5 text-xs text-red-700">
                <XCircle className="h-3 w-3" /> killed
              </span>
            )}
          </div>
          <p className="mt-1 text-sm text-neutral-900">
            {run.applications_submitted} submitted ·{" "}
            {run.applications_attempted} attempted ·{" "}
            {run.applications_skipped.length} skipped
          </p>
          <p className="mt-0.5 text-xs text-neutral-500">
            Started {new Date(run.started_at).toLocaleString()}
            {run.ended_at && (
              <>
                <span className="mx-1.5">·</span>
                Ended {new Date(run.ended_at).toLocaleString()}
              </>
            )}
          </p>
        </div>
        <Link
          to={`/routine/runs/${run.id}`}
          className="inline-flex items-center gap-1 text-xs font-medium text-primary-600 hover:text-primary-700"
        >
          <ExternalLink className="h-3.5 w-3.5" />
          Detail
        </Link>
      </div>
    </li>
  );
}
