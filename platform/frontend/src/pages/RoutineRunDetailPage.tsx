import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { getRoutineRun } from "@/lib/api";
import {
  ArrowLeft,
  Bot,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Clock,
  ExternalLink,
  FileText,
} from "lucide-react";
import { BackendErrorBanner } from "@/components/BackendErrorBanner";
import type { SubmissionDetail } from "@/lib/types";

/**
 * Claude Routine Apply — single-run detail.
 *
 * Timeline of every submission the routine produced during the run,
 * plus the run's final counters and any detection incidents. Each row
 * links out to the matching Application so the operator can see the
 * full Q/A + cover letter modal (ApplicationsPage.RoutineSubmissionModal
 * is the canonical renderer — we don't re-implement it here, we just
 * provide the jumping-off point).
 *
 * The run poll cadence is faster (10s) than the operator panel (30s)
 * because a live run updates its counters every few seconds and the
 * operator is usually watching this page in anticipation.
 */
export function RoutineRunDetailPage() {
  const { id } = useParams<{ id: string }>();

  const runQ = useQuery({
    queryKey: ["routine-run", id],
    queryFn: () => getRoutineRun(id!),
    enabled: Boolean(id),
    // Faster refetch while running; stops flipping once terminal.
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (status === "running") return 10_000;
      return false;
    },
  });

  if (runQ.isLoading) {
    return (
      <div className="p-8 text-sm text-neutral-500">Loading run detail…</div>
    );
  }

  if (runQ.isError || !runQ.data) {
    return (
      <div className="mx-auto max-w-5xl p-6">
        <BackLink />
        <div className="mt-4">
          <BackendErrorBanner queries={[runQ]} />
        </div>
      </div>
    );
  }

  const run = runQ.data;
  const submissions = run.submissions ?? [];
  const durationMs = run.ended_at
    ? new Date(run.ended_at).getTime() - new Date(run.started_at).getTime()
    : Date.now() - new Date(run.started_at).getTime();
  const durationMin = Math.max(0, Math.round(durationMs / 60_000));

  const statusColor =
    run.status === "complete"
      ? "bg-emerald-100 text-emerald-700"
      : run.status === "aborted"
        ? "bg-red-100 text-red-700"
        : "bg-blue-100 text-blue-700";

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <BackLink />

      {/* Header */}
      <div className="rounded-lg border border-neutral-200 bg-white p-6 shadow-sm">
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary-100">
            <Bot className="h-5 w-5 text-primary-700" />
          </div>
          <div className="flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-xl font-bold text-neutral-900">
                Routine run
              </h1>
              <span className="font-mono text-xs text-neutral-400">
                {run.id}
              </span>
              <span
                className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${statusColor}`}
              >
                {run.status}
              </span>
              <span className="inline-flex items-center rounded-full bg-neutral-100 px-2 py-0.5 text-xs font-medium uppercase tracking-wide text-neutral-600">
                {run.mode}
              </span>
              {run.kill_switch_triggered && (
                <span className="inline-flex items-center gap-1 rounded-full bg-red-50 px-2 py-0.5 text-xs font-medium text-red-700">
                  <XCircle className="h-3 w-3" /> kill-switch triggered
                </span>
              )}
            </div>
            <p className="mt-1 text-sm text-neutral-600">
              Started {new Date(run.started_at).toLocaleString()}
              {run.ended_at && (
                <>
                  {" · Ended "}
                  {new Date(run.ended_at).toLocaleString()}
                </>
              )}
              {" · "}
              <span className="inline-flex items-center gap-1">
                <Clock className="h-3 w-3" /> {durationMin}m
                {run.status === "running" && " (still running)"}
              </span>
            </p>
          </div>
        </div>

        <div className="mt-4 grid gap-4 sm:grid-cols-3">
          <CounterCell
            label="Submitted"
            value={run.applications_submitted}
            tone="good"
          />
          <CounterCell
            label="Attempted"
            value={run.applications_attempted}
            tone="neutral"
          />
          <CounterCell
            label="Skipped"
            value={run.applications_skipped.length}
            tone={run.applications_skipped.length > 0 ? "warn" : "neutral"}
          />
        </div>

        {run.detection_incidents.length > 0 && (
          <div className="mt-4 rounded-md border border-amber-200 bg-amber-50 p-3">
            <div className="flex items-center gap-2 text-sm font-medium text-amber-800">
              <AlertTriangle className="h-4 w-4" />
              Detection incidents ({run.detection_incidents.length})
            </div>
            <ul className="mt-2 space-y-1 text-xs text-amber-700">
              {run.detection_incidents.map((inc, i) => (
                <li key={i}>
                  {inc.at && (
                    <span className="font-mono text-amber-600">
                      {new Date(inc.at).toLocaleTimeString()}
                    </span>
                  )}
                  {inc.at && inc.reason && " — "}
                  {inc.reason}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {/* Skipped jobs — only renders if there are any. */}
      {run.applications_skipped.length > 0 && (
        <div className="rounded-lg border border-neutral-200 bg-white shadow-sm">
          <div className="border-b border-neutral-100 px-6 py-4">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-neutral-500">
              Skipped ({run.applications_skipped.length})
            </h2>
          </div>
          <ul className="divide-y divide-neutral-100">
            {run.applications_skipped.map((s, i) => (
              <li
                key={i}
                className="flex items-center justify-between px-6 py-3 text-sm"
              >
                <span className="font-mono text-xs text-neutral-500">
                  {s.job_id ? s.job_id.slice(0, 8) : "unknown"}
                </span>
                <span className="text-neutral-700">
                  {s.reason ?? "—"}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Submissions timeline */}
      <div className="rounded-lg border border-neutral-200 bg-white shadow-sm">
        <div className="border-b border-neutral-100 px-6 py-4">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-neutral-500">
            Submissions ({submissions.length})
          </h2>
        </div>
        {submissions.length === 0 ? (
          <div className="p-6 text-sm text-neutral-500">
            No submissions recorded yet.
            {run.status === "running" && " The routine may still be in progress."}
          </div>
        ) : (
          <ul className="divide-y divide-neutral-100">
            {submissions.map((s) => (
              <SubmissionRow key={s.id} submission={s} />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function BackLink() {
  return (
    <Link
      to="/routine"
      className="inline-flex items-center gap-1 text-sm text-neutral-600 hover:text-neutral-900"
    >
      <ArrowLeft className="h-4 w-4" />
      Back to routine panel
    </Link>
  );
}

function CounterCell({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "good" | "neutral" | "warn";
}) {
  const color =
    tone === "good"
      ? "text-emerald-700"
      : tone === "warn"
        ? "text-amber-700"
        : "text-neutral-900";
  return (
    <div className="rounded-lg border border-neutral-100 p-4">
      <div className="text-xs font-medium uppercase tracking-wide text-neutral-500">
        {label}
      </div>
      <div className={`mt-1 text-2xl font-bold ${color}`}>{value}</div>
    </div>
  );
}

/**
 * A single submission row. Shows the essentials inline (ATS platform,
 * confirmation presence, detected-issues count) and links to the
 * Applications page where the full RoutineSubmissionModal opens with
 * Q/A list, cover letter, screenshots, and profile snapshot — we
 * don't duplicate that modal here.
 */
function SubmissionRow({ submission }: { submission: SubmissionDetail }) {
  const hasConfirmation = Boolean(submission.confirmation_text);
  const issueCount = submission.detected_issues?.length ?? 0;
  const answerCount = submission.answers_json?.length ?? 0;

  return (
    <li className="flex items-center gap-4 px-6 py-4">
      <div className="flex-shrink-0">
        {hasConfirmation ? (
          <CheckCircle2 className="h-5 w-5 text-emerald-500" />
        ) : (
          <Clock className="h-5 w-5 text-neutral-400" />
        )}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-neutral-900">
            {submission.ats_platform}
          </span>
          <span className="text-xs text-neutral-500">
            {new Date(submission.submitted_at).toLocaleTimeString()}
          </span>
          {issueCount > 0 && (
            <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-xs text-amber-700">
              <AlertTriangle className="h-3 w-3" />
              {issueCount} issue{issueCount === 1 ? "" : "s"}
            </span>
          )}
          {answerCount > 0 && (
            <span className="inline-flex items-center gap-1 rounded-full bg-neutral-100 px-2 py-0.5 text-xs text-neutral-600">
              <FileText className="h-3 w-3" />
              {answerCount} answer{answerCount === 1 ? "" : "s"}
            </span>
          )}
        </div>
        <a
          href={submission.job_url}
          target="_blank"
          rel="noreferrer noopener"
          className="mt-0.5 inline-flex items-center gap-1 truncate text-xs text-neutral-500 hover:text-primary-700"
        >
          <ExternalLink className="h-3 w-3" />
          <span className="truncate">{submission.job_url}</span>
        </a>
      </div>
      <Link
        to={`/applications?source=routine#${submission.application_id}`}
        className="flex-shrink-0 text-xs font-medium text-primary-600 hover:text-primary-700"
        title="Open full submission detail in Applications"
      >
        View details →
      </Link>
    </li>
  );
}
