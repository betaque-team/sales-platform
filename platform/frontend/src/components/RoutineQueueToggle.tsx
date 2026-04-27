import { useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Bot, Ban, Check, X } from "lucide-react";
import {
  getRoutineQueue,
  upsertRoutineTarget,
  deleteRoutineTarget,
} from "@/lib/api";
import type { RoutineTargetIntent } from "@/lib/types";

/**
 * F257 — per-job control surface for the Apply Routine.
 *
 * Three states for any (user, job) pair:
 *
 *   1. **none** (no row in ``routine_targets``) — the routine treats
 *      the job through the auto-picker. UI shows two outline buttons:
 *      "Queue for routine" + "Exclude".
 *
 *   2. **queued** — operator pinned this. Surfaced first on
 *      ``top-to-apply``. UI shows a green chip + an Undo X button to
 *      remove the pin.
 *
 *   3. **excluded** — operator told the routine to skip. Hidden from
 *      auto-picks. UI shows a red chip + an Undo X button.
 *
 * Source-of-truth lives in the ``routine-queue`` query — invalidated
 * after every mutation so the UI converges with the backend without
 * optimistic-update bookkeeping.
 *
 * Used on JobDetailPage's action card AND on per-row controls in the
 * Jobs list. Stateless wrt the parent — pass ``jobId`` and the
 * component handles its own lifecycle.
 */
export function RoutineQueueToggle({
  jobId,
  className = "",
  compact = false,
}: {
  jobId: string;
  /** Extra classes on the wrapper. */
  className?: string;
  /** Compact mode: icon-only, no text labels. Used on row controls
   * where horizontal space is tight. */
  compact?: boolean;
}) {
  const queryClient = useQueryClient();

  const queueQ = useQuery({
    queryKey: ["routine-queue"],
    queryFn: getRoutineQueue,
    staleTime: 30_000, // queue rarely changes — share across components
  });

  // Resolve current state for THIS job from the queue payload.
  const state = useMemo<RoutineTargetIntent | "none">(() => {
    if (!queueQ.data) return "none";
    if (queueQ.data.queued.some((t) => t.job_id === jobId)) return "queued";
    if (queueQ.data.excluded.some((t) => t.job_id === jobId)) return "excluded";
    return "none";
  }, [queueQ.data, jobId]);

  const upsertMutation = useMutation({
    mutationFn: (intent: RoutineTargetIntent) =>
      upsertRoutineTarget(jobId, { intent }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["routine-queue"] });
      queryClient.invalidateQueries({ queryKey: ["routine-top-to-apply"] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => deleteRoutineTarget(jobId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["routine-queue"] });
      queryClient.invalidateQueries({ queryKey: ["routine-top-to-apply"] });
    },
  });

  const busy = upsertMutation.isPending || deleteMutation.isPending;

  // Compact mode: single chip with tooltip + click-to-cycle through
  // the three states. Used on Jobs list rows.
  if (compact) {
    if (state === "queued") {
      return (
        <button
          className={`inline-flex items-center gap-1 rounded bg-emerald-100 px-1.5 py-0.5 text-[11px] font-medium text-emerald-800 hover:bg-emerald-200 ${className}`}
          onClick={() => deleteMutation.mutate()}
          disabled={busy}
          title="Queued for Apply Routine. Click to remove."
        >
          <Bot className="h-3 w-3" />
          Queued
        </button>
      );
    }
    if (state === "excluded") {
      return (
        <button
          className={`inline-flex items-center gap-1 rounded bg-red-100 px-1.5 py-0.5 text-[11px] font-medium text-red-800 hover:bg-red-200 ${className}`}
          onClick={() => deleteMutation.mutate()}
          disabled={busy}
          title="Excluded from Apply Routine. Click to remove."
        >
          <Ban className="h-3 w-3" />
          Skipped
        </button>
      );
    }
    return (
      <button
        className={`inline-flex items-center gap-1 rounded border border-gray-200 px-1.5 py-0.5 text-[11px] font-medium text-gray-600 hover:bg-gray-50 ${className}`}
        onClick={() => upsertMutation.mutate("queued")}
        disabled={busy}
        title="Queue this job for the Apply Routine"
      >
        <Bot className="h-3 w-3" />
        Routine
      </button>
    );
  }

  // Full mode: stacked buttons + clear status. Used on Job Detail.
  return (
    <div className={`space-y-1.5 ${className}`}>
      {state === "queued" ? (
        <div className="flex items-center justify-between rounded-md border border-emerald-200 bg-emerald-50 px-2.5 py-2 text-xs">
          <span className="flex items-center gap-1.5 font-medium text-emerald-800">
            <Check className="h-3.5 w-3.5" />
            Queued for Apply Routine
          </span>
          <button
            onClick={() => deleteMutation.mutate()}
            disabled={busy}
            className="rounded p-0.5 text-emerald-700 hover:bg-emerald-100"
            aria-label="Remove from routine queue"
            title="Remove from routine queue"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      ) : state === "excluded" ? (
        <div className="flex items-center justify-between rounded-md border border-red-200 bg-red-50 px-2.5 py-2 text-xs">
          <span className="flex items-center gap-1.5 font-medium text-red-800">
            <Ban className="h-3.5 w-3.5" />
            Excluded from Apply Routine
          </span>
          <button
            onClick={() => deleteMutation.mutate()}
            disabled={busy}
            className="rounded p-0.5 text-red-700 hover:bg-red-100"
            aria-label="Remove from exclude list"
            title="Remove from exclude list"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-1.5">
          <button
            onClick={() => upsertMutation.mutate("queued")}
            disabled={busy}
            className="inline-flex items-center justify-center gap-1 rounded-md border border-emerald-200 bg-white px-2 py-1.5 text-[11px] font-medium text-emerald-700 hover:bg-emerald-50 disabled:opacity-50"
            title="The Apply Routine will surface this job above its auto-picks"
          >
            <Bot className="h-3.5 w-3.5" />
            Queue for Routine
          </button>
          <button
            onClick={() => upsertMutation.mutate("excluded")}
            disabled={busy}
            className="inline-flex items-center justify-center gap-1 rounded-md border border-gray-200 bg-white px-2 py-1.5 text-[11px] font-medium text-gray-600 hover:bg-gray-50 disabled:opacity-50"
            title="The Apply Routine will skip this job permanently"
          >
            <Ban className="h-3.5 w-3.5" />
            Skip
          </button>
        </div>
      )}
      {(upsertMutation.isError || deleteMutation.isError) && (
        <p className="text-[11px] text-red-600">
          {((upsertMutation.error || deleteMutation.error) as Error)?.message ||
            "Failed to update routine queue"}
        </p>
      )}
    </div>
  );
}
