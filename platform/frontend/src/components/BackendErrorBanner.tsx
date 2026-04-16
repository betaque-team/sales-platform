import { AlertTriangle, RefreshCw, X } from "lucide-react";
import { useState } from "react";
import type { UseQueryResult } from "@tanstack/react-query";

/**
 * Regression finding 222 (multi-query pages): DashboardPage has 11
 * `useQuery` calls, AnalyticsPage has 7, MonitoringPage has 2 admin-
 * critical ones. Wrapping each individual card in `<QueryBoundary>`
 * would turn a single transient `/analytics/overview` 502 into a full
 * "Failed to load" takeover of that tile while the other 10 cards
 * render fine — worse UX than the blank state it's trying to fix.
 *
 * `<BackendErrorBanner>` is the multi-query companion. It takes the
 * array of `useQuery` results that back the page, and when ANY of them
 * errors it drops a single dismissable red banner at the top of the
 * page with:
 *   - a human message ("Some data couldn't be loaded")
 *   - the first error detail (usually enough context)
 *   - a Retry-all button that refetches all failed queries in parallel
 *
 * Individual card `?? 0` / `data && data.items.length > 0 ? ...` guards
 * stay untouched — they handle the blank-cell case. The banner handles
 * the "why is it blank" question that the regression caller flagged.
 */

type QueryLike = Pick<
  UseQueryResult<unknown, unknown>,
  "isError" | "error" | "refetch"
>;

interface BackendErrorBannerProps {
  queries: QueryLike[];
  /** Optional override of the default "Some data couldn't be loaded" headline. */
  headline?: string;
  className?: string;
}

function extractErrorMessage(err: unknown): string {
  if (err instanceof Error) return err.message || "Request failed";
  if (typeof err === "string") return err;
  if (err && typeof err === "object" && "message" in err) {
    const m = (err as { message?: unknown }).message;
    if (typeof m === "string") return m;
  }
  return "Request failed";
}

export function BackendErrorBanner({
  queries,
  headline = "Some data couldn't be loaded",
  className,
}: BackendErrorBannerProps) {
  const [dismissed, setDismissed] = useState(false);
  const failed = queries.filter((q) => q.isError);
  if (failed.length === 0 || dismissed) return null;

  const firstMsg = extractErrorMessage(failed[0].error);

  const retryAll = () => {
    for (const q of failed) {
      try {
        void q.refetch();
      } catch {
        /* refetch throws synchronously on paused queries — ignore */
      }
    }
    // Optimistic: un-dismiss so if they fail again the banner returns.
    setDismissed(false);
  };

  return (
    <div
      role="alert"
      className={
        "flex items-start gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm" +
        (className ? ` ${className}` : "")
      }
    >
      <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-red-600" />
      <div className="min-w-0 flex-1">
        <p className="font-medium text-red-900">{headline}</p>
        <p className="mt-0.5 text-xs text-red-800 break-words">
          {failed.length > 1 ? `${failed.length} requests failed · ` : ""}
          {firstMsg}
        </p>
      </div>
      <button
        type="button"
        onClick={retryAll}
        className="inline-flex items-center gap-1 rounded-md bg-red-600 px-2.5 py-1.5 text-xs font-medium text-white hover:bg-red-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-500 focus-visible:ring-offset-2"
      >
        <RefreshCw className="h-3 w-3" />
        Retry
      </button>
      <button
        type="button"
        onClick={() => setDismissed(true)}
        className="rounded-md p-1 text-red-500 hover:bg-red-100 hover:text-red-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-500"
        aria-label="Dismiss"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}
