import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Sparkles,
  AlertTriangle,
  Lightbulb,
  CheckCircle,
  XCircle,
  RefreshCcw,
  ShieldCheck,
} from "lucide-react";

import { Card } from "@/components/Card";
import { Button } from "@/components/Button";
import { BackendErrorBanner } from "@/components/BackendErrorBanner";
import {
  getMyInsights,
  getProductInsights,
  actionProductInsight,
  triggerInsightsRun,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { InsightItem } from "@/lib/types";

/**
 * F237: AI Intelligence — user-facing insights bundle + admin product
 * insights queue, gated by role.
 *
 * Layout:
 *   - Top section: "Your insights" — every authenticated user sees
 *     their latest bundle from the most recent Mon/Thu beat run.
 *     Empty state when no run has produced insights for this user
 *     yet (new account, no recent activity).
 *   - Admin section: "Product insights" — only visible to admin /
 *     super_admin. Shows the pending queue with Action / Dismiss
 *     controls. The "Manual run" button forces a fresh generation
 *     for both user + product (useful after shipping a fix mentioned
 *     in last week's product insights).
 */
export function InsightsPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin" || user?.role === "super_admin";

  const myQ = useQuery({
    queryKey: ["insights-me"],
    queryFn: () => getMyInsights(),
    staleTime: 5 * 60_000,
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
          <Sparkles className="h-6 w-6 text-primary-600" />
          AI Insights
        </h1>
        <p className="mt-1 text-sm text-gray-500">
          Personalized observations from your recent activity. Updated every
          Monday and Thursday at 04:00 UTC.
        </p>
      </div>

      <BackendErrorBanner queries={[myQ]} />

      {/* User insights bundle */}
      <UserInsightsCard />

      {/* Admin section */}
      {isAdmin && <ProductInsightsCard />}
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────────

function UserInsightsCard() {
  const myQ = useQuery({
    queryKey: ["insights-me"],
    queryFn: () => getMyInsights(),
  });

  if (myQ.isLoading) {
    return (
      <Card>
        <div className="flex items-center justify-center py-10 text-sm text-gray-500">
          <div className="spinner h-5 w-5 mr-2" /> Loading your insights…
        </div>
      </Card>
    );
  }

  const latest = myQ.data?.latest;

  if (!latest) {
    return (
      <Card>
        <div className="py-10 text-center">
          <Lightbulb className="mx-auto h-10 w-10 text-gray-300" />
          <p className="mt-3 text-sm font-medium text-gray-900">
            No insights yet
          </p>
          <p className="mt-1 text-sm text-gray-500 max-w-md mx-auto">
            Insights appear after the next scheduled run (every Monday and
            Thursday at 04:00 UTC). You'll see them once you've had at least
            one job review in the last 30 days.
          </p>
        </div>
      </Card>
    );
  }

  return (
    <Card>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-base font-semibold text-gray-900">
          Your insights
        </h2>
        <span
          className="text-xs text-gray-400"
          title={`Generation ${latest.generation_id}, ${latest.prompt_version}`}
        >
          Generated {formatRelative(latest.generated_at)}
        </span>
      </div>
      <div className="space-y-3">
        {latest.insights.length === 0 ? (
          <p className="text-sm text-gray-500 italic">
            The insights generator returned no items this run. Try again after
            the next scheduled run.
          </p>
        ) : (
          latest.insights.map((it, i) => <InsightRow key={i} item={it} />)
        )}
      </div>
    </Card>
  );
}

// ──────────────────────────────────────────────────────────────────────────

function ProductInsightsCard() {
  const queryClient = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<"pending" | "actioned" | "dismissed" | "all">(
    "pending",
  );

  const productQ = useQuery({
    queryKey: ["insights-product", statusFilter],
    queryFn: () => getProductInsights(statusFilter, 1),
  });

  const runMutation = useMutation({
    mutationFn: triggerInsightsRun,
    onSuccess: () => {
      // Don't invalidate immediately — the Celery task takes ~30s to
      // complete; surface a "queued" notice and let the user refresh.
    },
  });

  const actionMutation = useMutation({
    mutationFn: ({
      id,
      status,
      note,
    }: {
      id: string;
      status: "actioned" | "dismissed" | "duplicate";
      note?: string;
    }) => actionProductInsight(id, status, note),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["insights-product"] });
    },
  });

  return (
    <Card>
      <div className="flex items-center justify-between mb-3">
        <div>
          <h2 className="text-base font-semibold text-gray-900 flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-purple-600" />
            Product insights
            <span className="text-xs font-normal text-gray-400">(admin)</span>
          </h2>
          <p className="mt-0.5 text-xs text-gray-500">
            AI-suggested platform improvements based on the last 7 days of
            usage. Action them to feed the next run with "did this help?" context.
          </p>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => runMutation.mutate()}
          loading={runMutation.isPending}
          title="Force a fresh insight run now (instead of waiting for the next Mon/Thu 04:00 UTC scheduled run)."
        >
          <RefreshCcw className="h-3.5 w-3.5 mr-1" />
          Run now
        </Button>
      </div>
      {runMutation.data && (
        <div className="rounded-md bg-blue-50 border border-blue-200 px-3 py-2 mb-3 text-xs text-blue-700">
          Generation queued (task {runMutation.data.task_id.slice(0, 8)}…).
          Refresh in ~30s to see the new insights.
        </div>
      )}

      <div className="flex gap-1 mb-3">
        {(["pending", "actioned", "dismissed", "all"] as const).map((s) => (
          <button
            key={s}
            onClick={() => setStatusFilter(s)}
            className={`text-xs px-2.5 py-1 rounded ${
              statusFilter === s
                ? "bg-primary-100 text-primary-700 font-medium"
                : "bg-gray-100 text-gray-600 hover:bg-gray-200"
            }`}
          >
            {s.charAt(0).toUpperCase() + s.slice(1)}
          </button>
        ))}
      </div>

      <BackendErrorBanner queries={[productQ]} />

      {productQ.isLoading ? (
        <div className="flex items-center justify-center py-6 text-sm text-gray-500">
          <div className="spinner h-4 w-4 mr-2" /> Loading…
        </div>
      ) : (productQ.data?.items?.length ?? 0) === 0 ? (
        <p className="py-6 text-center text-sm text-gray-500 italic">
          No {statusFilter} insights right now.
        </p>
      ) : (
        <div className="space-y-3">
          {productQ.data!.items.map((item) => (
            <ProductInsightRow
              key={item.id}
              item={item}
              onAction={(status, note) =>
                actionMutation.mutate({ id: item.id, status, note })
              }
              busy={actionMutation.isPending}
            />
          ))}
        </div>
      )}
    </Card>
  );
}

// ──────────────────────────────────────────────────────────────────────────
// Helpers

function InsightRow({ item }: { item: InsightItem }) {
  const tone = severityTone(item.severity);
  return (
    <div
      className={`rounded-lg border p-3 ${tone.border} ${tone.bg}`}
    >
      <div className="flex items-start gap-2">
        <span className="mt-0.5">{tone.icon}</span>
        <div className="flex-1">
          <p className={`text-sm font-medium ${tone.titleColor}`}>{item.title}</p>
          <p className="mt-1 text-sm text-gray-700">{item.body}</p>
          {item.action_link && (
            <a
              href={item.action_link}
              className="mt-1 inline-block text-xs text-primary-600 hover:underline"
            >
              Take action →
            </a>
          )}
          {item.category && (
            <span className="mt-1 inline-block rounded bg-white border border-gray-200 px-1.5 py-0.5 text-[10px] text-gray-500">
              {item.category}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

function ProductInsightRow({
  item,
  onAction,
  busy,
}: {
  item: import("@/lib/types").ProductInsight;
  onAction: (status: "actioned" | "dismissed" | "duplicate", note?: string) => void;
  busy: boolean;
}) {
  const [showNote, setShowNote] = useState(false);
  const [note, setNote] = useState("");
  const tone = severityTone(item.severity);
  return (
    <div className={`rounded-lg border p-3 ${tone.border} ${tone.bg}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <span>{tone.icon}</span>
            <p className={`text-sm font-medium ${tone.titleColor}`}>
              {item.title}
            </p>
          </div>
          <p className="mt-1 text-sm text-gray-700 whitespace-pre-line">
            {item.body}
          </p>
          <div className="mt-1 flex items-center gap-2">
            <span className="rounded bg-white border border-gray-200 px-1.5 py-0.5 text-[10px] text-gray-500">
              {item.category}
            </span>
            <span className="text-[10px] text-gray-400">
              {formatRelative(item.generated_at)}
            </span>
            {item.actioned_status && (
              <span
                className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                  item.actioned_status === "actioned"
                    ? "bg-green-100 text-green-700"
                    : item.actioned_status === "dismissed"
                      ? "bg-gray-200 text-gray-700"
                      : "bg-purple-100 text-purple-700"
                }`}
              >
                {item.actioned_status}
              </span>
            )}
          </div>
        </div>
        {!item.actioned_at && (
          <div className="flex flex-col gap-1">
            <Button
              variant="primary"
              size="sm"
              onClick={() => onAction("actioned", note || undefined)}
              loading={busy}
            >
              <CheckCircle className="h-3 w-3 mr-1" /> Actioned
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onAction("dismissed", note || undefined)}
              loading={busy}
            >
              <XCircle className="h-3 w-3 mr-1" /> Dismiss
            </Button>
            <button
              onClick={() => setShowNote(!showNote)}
              className="text-[10px] text-gray-500 hover:text-gray-700 underline"
            >
              {showNote ? "Hide" : "Add"} note
            </button>
          </div>
        )}
      </div>
      {showNote && !item.actioned_at && (
        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value.slice(0, 2000))}
          placeholder="Optional context for the next AI run (e.g. 'Shipped this in v1.2.3, monitoring the metric')…"
          className="mt-2 w-full rounded border border-gray-200 p-2 text-xs"
          rows={2}
        />
      )}
      {item.actioned_note && (
        <p className="mt-2 text-xs text-gray-500 italic">
          Note: {item.actioned_note}
        </p>
      )}
    </div>
  );
}

function severityTone(severity: string) {
  switch (severity) {
    case "high":
    case "warning":
      return {
        bg: "bg-red-50",
        border: "border-red-200",
        titleColor: "text-red-900",
        icon: <AlertTriangle className="h-4 w-4 text-red-600" />,
      };
    case "medium":
    case "tip":
      return {
        bg: "bg-amber-50",
        border: "border-amber-200",
        titleColor: "text-amber-900",
        icon: <Lightbulb className="h-4 w-4 text-amber-600" />,
      };
    case "low":
    case "info":
    default:
      return {
        bg: "bg-blue-50",
        border: "border-blue-100",
        titleColor: "text-blue-900",
        icon: <Sparkles className="h-4 w-4 text-blue-600" />,
      };
  }
}

function formatRelative(iso: string | null | undefined): string {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  const now = Date.now();
  const sec = Math.max(0, Math.round((now - t) / 1000));
  if (sec < 60) return "just now";
  const min = Math.round(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.round(hr / 24);
  return `${day}d ago`;
}
