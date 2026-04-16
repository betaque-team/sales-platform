import { AlertTriangle, Inbox } from "lucide-react";
import type { ReactNode } from "react";
import type { UseQueryResult } from "@tanstack/react-query";

/**
 * Regression finding 222: 56 `useQuery` call sites across 19 pages only
 * destructured `data` — ignoring `isError`/`error` — so any non-401 failure
 * (500, 502, 504, network timeout, abort) silently rendered blank UI with
 * no way for the user to know something went wrong, let alone retry.
 *
 * `<QueryBoundary>` is the shared primitive that replaces the ad-hoc
 *   if (isLoading) return <Spinner/>;
 *   if (!data) return null;
 * branches scattered across pages. It renders exactly one of four states:
 *   - loading:   default spinner (override via `loadingFallback`)
 *   - error:     alert card with the error message + optional retry button
 *   - empty:     friendly "no data" card when `isEmpty` is true
 *   - children:  normal content
 *
 * For pages with a single primary query (ReviewQueue, CompaniesPage,
 * Applications), wrap the whole body in `<QueryBoundary query={q}>...`.
 * For multi-query pages (Dashboard 11, Analytics 7), prefer the
 * `<BackendErrorBanner>` companion which surfaces errors without forcing
 * all-or-nothing rendering.
 */

type QueryLike = Pick<
  UseQueryResult<unknown, unknown>,
  "isLoading" | "isError" | "error" | "refetch"
>;

interface QueryBoundaryProps {
  /** Preferred: pass the full useQuery result. */
  query?: QueryLike;
  /** Or pass the individual flags (useful when you've already destructured). */
  isLoading?: boolean;
  isError?: boolean;
  error?: unknown;
  /** Render an empty state instead of children when true. */
  isEmpty?: boolean;
  emptyText?: string;
  emptyIcon?: ReactNode;
  /** Override the default loading spinner. */
  loadingFallback?: ReactNode;
  /** Called when the user clicks Retry; falls back to query.refetch() if omitted. */
  onRetry?: () => void;
  /** Controls the visual footprint — `inline` is a small row, `block` fills a card. */
  variant?: "inline" | "block";
  children: ReactNode;
}

function extractErrorMessage(err: unknown): string {
  if (err instanceof Error) return err.message || "Something went wrong";
  if (typeof err === "string") return err;
  if (err && typeof err === "object" && "message" in err) {
    const m = (err as { message?: unknown }).message;
    if (typeof m === "string") return m;
  }
  return "Something went wrong";
}

export function QueryBoundary({
  query,
  isLoading,
  isError,
  error,
  isEmpty,
  emptyText = "No data to show",
  emptyIcon,
  loadingFallback,
  onRetry,
  variant = "block",
  children,
}: QueryBoundaryProps) {
  const loading = isLoading ?? query?.isLoading ?? false;
  const errored = isError ?? query?.isError ?? false;
  const errVal = error ?? query?.error;
  const retry = onRetry ?? (query?.refetch ? () => void query.refetch() : undefined);

  if (loading) {
    if (loadingFallback !== undefined) return <>{loadingFallback}</>;
    return (
      <div
        className={
          variant === "inline"
            ? "flex items-center gap-2 py-4 text-sm text-gray-400"
            : "flex items-center justify-center py-16"
        }
        role="status"
        aria-live="polite"
      >
        <div className="spinner h-6 w-6" />
        {variant === "inline" && <span>Loading…</span>}
      </div>
    );
  }

  if (errored) {
    const msg = extractErrorMessage(errVal);
    return (
      <div
        className={
          variant === "inline"
            ? "flex items-center gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
            : "flex flex-col items-center gap-3 rounded-xl border border-red-200 bg-red-50 px-6 py-10 text-center"
        }
        role="alert"
      >
        <div className="flex items-center gap-2 text-red-700">
          <AlertTriangle className="h-5 w-5 shrink-0" />
          <span className="font-medium">Failed to load</span>
        </div>
        <p className="text-sm text-red-800 max-w-md break-words">{msg}</p>
        {retry && (
          <button
            type="button"
            onClick={retry}
            className="mt-1 rounded-md bg-red-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-500 focus-visible:ring-offset-2"
          >
            Try again
          </button>
        )}
      </div>
    );
  }

  if (isEmpty) {
    return (
      <div
        className={
          variant === "inline"
            ? "flex items-center gap-2 py-6 text-sm text-gray-400"
            : "flex flex-col items-center gap-2 rounded-xl border border-dashed border-gray-200 bg-gray-50 px-6 py-10 text-center"
        }
      >
        {emptyIcon ?? <Inbox className="h-6 w-6 text-gray-300" />}
        <p className="text-sm text-gray-500">{emptyText}</p>
      </div>
    );
  }

  return <>{children}</>;
}
