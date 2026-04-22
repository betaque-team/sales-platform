import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getRequiredCoverage,
  seedRequiredAnswers,
  updateAnswer,
} from "@/lib/api";
import type { RequiredCoverageEntry } from "@/lib/types";
import { CheckCircle2, Circle, Lock, Save, Sparkles } from "lucide-react";
import { BackendErrorBanner } from "@/components/BackendErrorBanner";

/**
 * Claude Routine Apply — required answer-book setup.
 *
 * The routine refuses to run until every row here is filled. This page
 * is the one-stop setup: it seeds the 16 canonical entries (salary
 * minima by geography, notice period, work auth, EEO demographics) on
 * first visit and lets the user fill each one inline.
 *
 * The seed POST is idempotent — opening this page twice does not create
 * duplicates. The backend lock enforcement (is_locked=True) means the
 * user can only edit the answer on these rows; attempts to delete or
 * change the question text are rejected server-side.
 */

// Human-readable grouping for the coverage list. The backend seeds
// three categories; we render them in a consistent order so refilling
// a row doesn't re-order the list under the user's cursor.
const CATEGORY_ORDER = ["preferences", "work_auth", "personal_info"] as const;

const CATEGORY_LABELS: Record<string, string> = {
  preferences: "Compensation & Work Terms",
  work_auth: "Work Authorization",
  personal_info: "Identity & EEO",
};

export function RequiredSetupPage() {
  const queryClient = useQueryClient();
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [savingId, setSavingId] = useState<string | null>(null);

  const coverageQ = useQuery({
    queryKey: ["required-coverage"],
    queryFn: getRequiredCoverage,
  });

  const seedMutation = useMutation({
    mutationFn: seedRequiredAnswers,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["required-coverage"] });
    },
  });

  // PATCH the single answer field. Locked rows reject question/category
  // edits at the API boundary (400), so we only send { answer }.
  const saveMutation = useMutation({
    mutationFn: async ({ id, answer }: { id: string; answer: string }) => {
      return updateAnswer(id, { answer });
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ["required-coverage"] });
      queryClient.invalidateQueries({ queryKey: ["answer-book"] });
      setEdits((prev) => {
        const next = { ...prev };
        delete next[variables.id];
        return next;
      });
      setSavingId(null);
    },
    onError: () => setSavingId(null),
  });

  if (coverageQ.isLoading) {
    return (
      <div className="p-8 text-sm text-neutral-500">Loading required setup…</div>
    );
  }

  if (coverageQ.isError) {
    return (
      <div className="p-8">
        <BackendErrorBanner queries={[coverageQ]} />
      </div>
    );
  }

  const coverage = coverageQ.data!;
  const total = coverage.total_required;
  const filled = coverage.total_filled;
  const progress = total === 0 ? 0 : (filled / total) * 100;

  // A fresh account has 0 rows persisted — the backend returns the 16
  // entries with placeholder UUIDs and filled=false. The `id` is the
  // cheapest "is this row persisted yet?" signal: persisted rows come
  // back with their real DB id, placeholders are generated per-request
  // so they'd change on reload. We therefore lean on the simpler check
  // "are any rows filled or is any entry present in the DB" — if every
  // entry is unfilled AND every answer is empty, we prompt to seed.
  const allMissing = coverage.missing.length === total;

  // Group all 16 entries by category for display. `missing` only has
  // unfilled — for the grouped view we need everything, so we merge
  // `missing` with the "filled" entries that the response doesn't
  // include directly. The API returns unfilled rows in `missing` and
  // exposes counts, but not filled rows — so we fetch them from a
  // second slice of data computed on the server? No, actually we have
  // enough: if filled == total we render "all done" and skip the list;
  // if filled < total the missing array is what the user needs to act
  // on. Unfilled-first is the useful operator flow.

  const grouped: Record<string, RequiredCoverageEntry[]> = {};
  for (const entry of coverage.missing) {
    const cat = entry.category || "custom";
    if (!grouped[cat]) grouped[cat] = [];
    grouped[cat].push(entry);
  }

  return (
    <div className="mx-auto max-w-3xl p-6 space-y-6">
      {/* Header — progress + seed action */}
      <div className="rounded-lg border border-neutral-200 bg-white p-6 shadow-sm">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-neutral-900">
              Required answer-book setup
            </h1>
            <p className="mt-1 text-sm text-neutral-600">
              The Claude Routine Apply feature refuses to submit any
              application until every row below has an answer. These are
              the identity, compensation, and EEO questions that must
              come from you — never from the model.
            </p>
          </div>
          <div className="flex-shrink-0 rounded-lg bg-primary-50 px-3 py-2 text-center">
            <div className="text-2xl font-bold text-primary-700">
              {filled}
              <span className="text-base font-normal text-primary-500">/{total}</span>
            </div>
            <div className="text-xs text-primary-600">filled</div>
          </div>
        </div>

        <div className="mt-4 h-2 w-full overflow-hidden rounded-full bg-neutral-100">
          <div
            className={`h-full rounded-full transition-all ${
              coverage.complete ? "bg-emerald-500" : "bg-primary-500"
            }`}
            style={{ width: `${progress}%` }}
          />
        </div>

        {coverage.complete && (
          <div className="mt-3 flex items-center gap-2 rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
            <CheckCircle2 className="h-4 w-4" />
            All required answers filled. The routine is ready to run.
          </div>
        )}

        {allMissing && (
          <button
            type="button"
            onClick={() => seedMutation.mutate()}
            disabled={seedMutation.isPending}
            className="mt-4 inline-flex items-center gap-2 rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 disabled:opacity-50"
          >
            <Sparkles className="h-4 w-4" />
            {seedMutation.isPending
              ? "Seeding…"
              : "Seed required entries"}
          </button>
        )}

        {seedMutation.isSuccess && !allMissing && (
          <div className="mt-3 text-xs text-neutral-500">
            Seeded {seedMutation.data?.created} new entries ·{" "}
            {seedMutation.data?.already_present} already present.
          </div>
        )}
      </div>

      {/* Unfilled rows, grouped */}
      {CATEGORY_ORDER.map((cat) => {
        const entries = grouped[cat];
        if (!entries || entries.length === 0) return null;
        return (
          <div
            key={cat}
            className="rounded-lg border border-neutral-200 bg-white p-6 shadow-sm"
          >
            <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-neutral-500">
              {CATEGORY_LABELS[cat] ?? cat}
            </h2>
            <ul className="space-y-4">
              {entries.map((entry) => {
                const editing =
                  edits[entry.id] !== undefined ? edits[entry.id] : entry.answer;
                const hasChanges = edits[entry.id] !== undefined;
                return (
                  <li
                    key={entry.id}
                    className="flex flex-col gap-2 border-b border-neutral-100 pb-4 last:border-b-0 last:pb-0"
                  >
                    <label className="flex items-start gap-2 text-sm font-medium text-neutral-900">
                      {entry.filled ? (
                        <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-emerald-500" />
                      ) : (
                        <Circle className="mt-0.5 h-4 w-4 flex-shrink-0 text-neutral-300" />
                      )}
                      <span className="flex-1">{entry.question}</span>
                      <Lock
                        className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-neutral-400"
                        aria-label="Locked — question text cannot be edited"
                      />
                    </label>
                    <div className="flex gap-2 pl-6">
                      <input
                        type="text"
                        value={editing}
                        onChange={(e) =>
                          setEdits({ ...edits, [entry.id]: e.target.value })
                        }
                        placeholder="Your answer…"
                        className="flex-1 rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
                      />
                      <button
                        type="button"
                        onClick={() => {
                          setSavingId(entry.id);
                          saveMutation.mutate({
                            id: entry.id,
                            answer: editing,
                          });
                        }}
                        disabled={
                          !hasChanges || saveMutation.isPending
                        }
                        className="inline-flex items-center gap-1 rounded-md bg-primary-600 px-3 py-2 text-sm font-medium text-white hover:bg-primary-700 disabled:opacity-40"
                      >
                        <Save className="h-3.5 w-3.5" />
                        {savingId === entry.id && saveMutation.isPending
                          ? "Saving…"
                          : "Save"}
                      </button>
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
    </div>
  );
}
