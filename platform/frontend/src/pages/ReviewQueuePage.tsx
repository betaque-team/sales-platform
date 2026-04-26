import { useState, useEffect, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  XCircle,
  SkipForward,
  Send,
  ExternalLink,
  ChevronLeft,
  ChevronRight,
  ClipboardCheck,
  Globe,
  MapPin,
  Building2,
} from "lucide-react";
import { Card } from "@/components/Card";
import { Button } from "@/components/Button";
import { Badge } from "@/components/Badge";
import { StatusBadge } from "@/components/StatusBadge";
import { ScoreBar } from "@/components/ScoreBar";
import { getReviewQueue, submitReview, applyFromReview } from "@/lib/api";
import type { Job, ReviewPayload } from "@/lib/types";
import { QueryBoundary } from "@/components/QueryBoundary";

const REJECTION_TAGS = [
  { value: "location_mismatch", label: "Location" },
  { value: "seniority_mismatch", label: "Seniority" },
  { value: "not_relevant", label: "Not Relevant" },
  { value: "salary_low", label: "Salary" },
  { value: "company_concern", label: "Company" },
  { value: "duplicate", label: "Duplicate" },
];

export function ReviewQueuePage() {
  const queryClient = useQueryClient();
  const [currentIndex, setCurrentIndex] = useState(0);
  const [comment, setComment] = useState("");
  const [selectedTags, setSelectedTags] = useState<string[]>([]);

  // F222: destructure the full query so a /review/queue 500 surfaces an
  // error card with Retry instead of an indefinite "Queue is empty" state.
  const queueQ = useQuery({
    queryKey: ["review", "queue"],
    queryFn: getReviewQueue,
  });
  const { data: queueData } = queueQ;
  const queue: Job[] = queueData?.items ?? [];
  const stats = queueData?.stats;

  const reviewMutation = useMutation({
    mutationFn: ({ jobId, payload, decision: _d }: { jobId: string; payload: ReviewPayload; decision: string }) =>
      submitReview(jobId, payload),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ["review", "queue"] });
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      setComment("");
      setSelectedTags([]);

      const { decision } = variables;
      if (decision === "skip") {
        // Job stays in queue — advance index to show next, wrap around at end
        setCurrentIndex((idx) => (idx + 1 >= queue.length ? 0 : idx + 1));
      } else {
        // Job removed from queue — list shrinks by 1. Stay at same index
        // (which becomes the next job), but clamp to new length.
        setCurrentIndex((idx) => Math.min(idx, Math.max(0, queue.length - 2)));
      }
    },
  });

  // Feature C — Applied action. Calls POST /reviews/apply which
  // atomically creates the Application + Review + Pipeline rows and
  // flips Job.status to accepted. On success we drop out of the queue
  // (same clamp logic as Accept) and invalidate the applications list
  // so the Applications page shows the new row without a hard refresh.
  const applyMutation = useMutation({
    mutationFn: (jobId: string) => applyFromReview(jobId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["review", "queue"] });
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      queryClient.invalidateQueries({ queryKey: ["applications"] });
      setComment("");
      setSelectedTags([]);
      setCurrentIndex((idx) => Math.min(idx, Math.max(0, queue.length - 2)));
    },
  });

  const currentJob = queue[currentIndex] ?? queue[0];

  const handleReview = useCallback(
    (decision: "accept" | "reject" | "skip") => {
      if (!currentJob) return;
      // Regression finding 73: only send rejection tags when the decision
      // is "reject". Previously the payload shipped selectedTags regardless
      // of decision, and the backend persisted them blindly — "accepted"
      // jobs ended up with rejection-reason tags attached.
      const tags = decision === "reject" ? selectedTags : [];
      reviewMutation.mutate({
        jobId: currentJob.id,
        payload: { decision, comment, tags },
        decision,
      });
    },
    [currentJob, selectedTags, comment, reviewMutation],
  );

  const handleApplied = useCallback(() => {
    if (!currentJob) return;
    applyMutation.mutate(currentJob.id);
  }, [currentJob, applyMutation]);

  // Regression finding 51: keyboard shortcuts for the review-queue-of-one
  // workflow. Guarded when focus is inside an input/textarea so typing a
  // comment doesn't accidentally fire an action.
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;

      switch (e.key.toLowerCase()) {
        case "a":
          handleReview("accept");
          break;
        case "p":
          // Feature C — Applied shortcut. "A" is taken by Accept, so
          // Applied gets the next best letter (P for aPplied).
          handleApplied();
          break;
        case "r":
          handleReview("reject");
          break;
        case "s":
          handleReview("skip");
          break;
        case "j":
        case "arrowright":
          if (currentIndex < queue.length - 1) {
            setCurrentIndex(currentIndex + 1);
            setComment("");
            setSelectedTags([]);
          }
          break;
        case "k":
        case "arrowleft":
          if (currentIndex > 0) {
            setCurrentIndex(currentIndex - 1);
            setComment("");
            setSelectedTags([]);
          }
          break;
      }
    },
    [currentIndex, queue.length, handleReview, handleApplied],
  );

  useEffect(() => {
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [handleKeyDown]);

  // F222: loading AND error both routed through the shared boundary.
  if (queueQ.isLoading || queueQ.isError) {
    return (
      <div className="mx-auto max-w-2xl pt-10">
        <QueryBoundary query={queueQ}>
          <></>
        </QueryBoundary>
      </div>
    );
  }

  if (queue.length === 0) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Review Queue</h1>
          <p className="mt-1 text-sm text-gray-500">Review and triage incoming jobs</p>
        </div>
        <div className="py-20 text-center">
          <ClipboardCheck className="mx-auto h-12 w-12 text-gray-300" />
          <p className="mt-4 text-lg font-medium text-gray-900">
            Queue is empty
          </p>
          <p className="mt-1 text-sm text-gray-500">
            All jobs have been reviewed. Check back later for new entries.
          </p>
        </div>
      </div>
    );
  }

  const progress = queue.length > 0 ? ((currentIndex + 1) / queue.length) * 100 : 0;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Review Queue</h1>
          <p className="mt-1 text-sm text-gray-500">
            {queue.length} jobs awaiting review
            <span className="ml-2 text-xs text-gray-400">
              Keys: A accept · P applied · R reject · S skip · J/K navigate
            </span>
          </p>
          {stats && (stats.total ?? 0) > 0 && (
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              <span className="rounded-full bg-primary-50 px-2.5 py-0.5 text-xs font-medium text-primary-700 ring-1 ring-primary-200">
                {stats.today} today
              </span>
              <span className="rounded-full bg-gray-100 px-2.5 py-0.5 text-xs font-medium text-gray-700">
                {stats.yesterday} yesterday
              </span>
              <span className="rounded-full bg-gray-50 px-2.5 py-0.5 text-xs font-medium text-gray-500 ring-1 ring-gray-200">
                {stats.older} older
              </span>
              <span className="ml-1 text-xs text-gray-400">
                ordered by recency · team-wide best resume fit · relevance
              </span>
            </div>
          )}
        </div>
        <div className="flex items-center gap-2 text-sm text-gray-500">
          <span>
            {currentIndex + 1} of {queue.length}
          </span>
        </div>
      </div>

      <div className="h-1.5 w-full overflow-hidden rounded-full bg-gray-200">
        <div
          className="h-full rounded-full bg-primary-600 transition-all duration-300"
          style={{ width: `${progress}%` }}
        />
      </div>

      <div className="mx-auto max-w-3xl">
        <Card>
          <div className="flex items-start justify-between mb-4">
            <div>
              <h2 className="text-xl font-bold text-gray-900">
                {currentJob.title}
              </h2>
              <div className="mt-1 flex items-center gap-2 text-sm text-gray-500">
                <Building2 className="h-4 w-4" />
                <span>{currentJob.company_name}</span>
                <span>&middot;</span>
                <span>{currentJob.source_platform}</span>
              </div>
            </div>
            <StatusBadge status={currentJob.status} />
          </div>

          <div className="grid grid-cols-2 gap-4 rounded-lg bg-gray-50 p-4 mb-4">
            <div className="flex items-center gap-2">
              <Globe className="h-4 w-4 text-gray-400" />
              <div>
                <p className="text-xs text-gray-500">Remote Scope</p>
                <p className="text-sm font-medium text-gray-900">
                  {currentJob.remote_scope}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <MapPin className="h-4 w-4 text-gray-400" />
              <div>
                <p className="text-xs text-gray-500">Location</p>
                <p className="text-sm font-medium text-gray-900">
                  {currentJob.location_restriction || "None"}
                </p>
              </div>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3 mb-4">
            <div className="flex items-center gap-2">
              <span className="text-xs text-gray-500">Relevance:</span>
              <ScoreBar score={currentJob.relevance_score} />
            </div>
            {typeof (currentJob.your_resume_score ?? currentJob.max_resume_score) === "number" && (
              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-500">Your resume fit:</span>
                <ScoreBar score={(currentJob.your_resume_score ?? currentJob.max_resume_score) as number} />
              </div>
            )}
            {currentJob.role_cluster && <Badge variant="primary">{currentJob.role_cluster}</Badge>}
            {currentJob.geography_bucket && (
              <Badge variant="info">
                {currentJob.geography_bucket.replace(/_/g, " ")}
              </Badge>
            )}
            {currentJob.employment_type && (
              <Badge variant="gray">{currentJob.employment_type}</Badge>
            )}
            {currentJob.salary_range && (
              <Badge variant="success">{currentJob.salary_range}</Badge>
            )}
          </div>

          <div className="flex items-center gap-2 mb-6">
            <a
              href={currentJob.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 text-sm font-medium text-primary-600 hover:text-primary-700"
            >
              View Original Listing
              <ExternalLink className="h-3.5 w-3.5" />
            </a>
          </div>

          <div className="border-t border-gray-200 pt-4">
            <div className="mb-3">
              {/* Regression finding 74: rejection tag pills are radio-like toggles.
                  Wrap in role="group" and expose aria-pressed so assistive tech
                  can announce which reasons are currently selected. */}
              <label id="rejection-tags-label" className="label mb-1.5">
                Rejection Tags (optional)
              </label>
              <div
                role="group"
                aria-labelledby="rejection-tags-label"
                className="flex flex-wrap gap-1.5"
              >
                {REJECTION_TAGS.map((tag) => {
                  const active = selectedTags.includes(tag.value);
                  return (
                    <button
                      key={tag.value}
                      type="button"
                      aria-pressed={active}
                      onClick={() =>
                        setSelectedTags((prev) =>
                          active ? prev.filter((t) => t !== tag.value) : [...prev, tag.value]
                        )
                      }
                      className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
                        active
                          ? "bg-red-100 text-red-700 ring-1 ring-red-300"
                          : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                      }`}
                    >
                      {tag.label}
                    </button>
                  );
                })}
              </div>
            </div>

            <label htmlFor="review-comment" className="label">
              Comment (optional)
            </label>
            <textarea
              id="review-comment"
              className="input min-h-[60px] resize-y mb-4"
              placeholder="Add a note about this job..."
              value={comment}
              onChange={(e) => setComment(e.target.value)}
            />

            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                {/* Regression finding 72: selectedTags and comment were
                    persisting across prev/next navigation, so rejection
                    tags selected for job #N got silently attached to the
                    submit for job #N+1. Clear both on every index change.
                    Also added aria-labels (finding 74). */}
                <button
                  onClick={() => {
                    setCurrentIndex(Math.max(0, currentIndex - 1));
                    setComment("");
                    setSelectedTags([]);
                  }}
                  disabled={currentIndex === 0}
                  className="rounded-lg p-2 text-gray-400 hover:bg-gray-100 hover:text-gray-600 disabled:opacity-50 disabled:pointer-events-none transition-colors"
                  aria-label="Previous job"
                >
                  <ChevronLeft className="h-5 w-5" />
                </button>
                <button
                  onClick={() => {
                    setCurrentIndex(Math.min(queue.length - 1, currentIndex + 1));
                    setComment("");
                    setSelectedTags([]);
                  }}
                  disabled={currentIndex >= queue.length - 1}
                  className="rounded-lg p-2 text-gray-400 hover:bg-gray-100 hover:text-gray-600 disabled:opacity-50 disabled:pointer-events-none transition-colors"
                  aria-label="Next job"
                >
                  <ChevronRight className="h-5 w-5" />
                </button>
              </div>

              <div className="flex items-center gap-2">
                <Button
                  variant="secondary"
                  size="md"
                  onClick={() => handleReview("skip")}
                  loading={reviewMutation.isPending}
                >
                  <SkipForward className="h-4 w-4" />
                  Skip
                </Button>
                <Button
                  variant="danger"
                  size="md"
                  onClick={() => handleReview("reject")}
                  loading={reviewMutation.isPending}
                >
                  <XCircle className="h-4 w-4" />
                  Reject
                </Button>
                <Button
                  variant="primary"
                  size="md"
                  onClick={() => handleReview("accept")}
                  loading={reviewMutation.isPending}
                >
                  <CheckCircle2 className="h-4 w-4" />
                  Accept
                </Button>
                {/* Feature C — Applied implies Accept + creates an
                    Application row with apply-time snapshot. Placed
                    as the rightmost action since it's the most
                    committed step in the review workflow. */}
                <Button
                  variant="primary"
                  size="md"
                  onClick={handleApplied}
                  loading={applyMutation.isPending}
                >
                  <Send className="h-4 w-4" />
                  Applied
                </Button>
              </div>
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}
