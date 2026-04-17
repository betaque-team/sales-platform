import { useState, useEffect, useCallback } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link as LinkIcon, X, CheckCircle2 } from "lucide-react";
import { Button } from "@/components/Button";
import { submitJobLink } from "@/lib/api";
import { ApiError } from "@/lib/api";

// Feature A — Submit Job Link modal.
//
// Sales users paste an ATS URL, we hit POST /jobs/submit-link which
// runs it through the normal scoring/classification pipeline and
// returns the upserted job. The modal surfaces two outcomes:
//   * is_new=true  → "Imported Stripe / Senior SRE — View job"
//   * is_new=false → "Already in the system — View job"
// plus any parse/fetch/rate-limit errors as inline red text so the
// user can fix the URL and retry without losing the typed value.

interface SubmitLinkModalProps {
  open: boolean;
  onClose: () => void;
  // Called with the imported job id when the user clicks "View job"
  // on the success banner. Lets the parent route them to the detail
  // page without this component owning its own navigation logic.
  onOpenJob?: (jobId: string) => void;
}

export function SubmitLinkModal({ open, onClose, onOpenJob }: SubmitLinkModalProps) {
  const queryClient = useQueryClient();
  const [url, setUrl] = useState("");
  const [successMessage, setSuccessMessage] = useState<{
    jobId: string;
    title: string;
    companyName: string;
    isNew: boolean;
  } | null>(null);

  const mutation = useMutation({
    mutationFn: (u: string) => submitJobLink(u),
    onSuccess: (res) => {
      setSuccessMessage({
        jobId: res.id,
        title: res.title,
        companyName: res.company_name,
        isNew: res.is_new,
      });
      // Refresh the jobs list + the review queue so the imported row
      // appears without a manual refresh. Only invalidate, don't await
      // — the banner shows immediately.
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      queryClient.invalidateQueries({ queryKey: ["review", "queue"] });
    },
  });

  // Reset form state every time the modal opens so a prior submission's
  // success banner / URL value don't carry over into the next session.
  useEffect(() => {
    if (open) {
      setUrl("");
      setSuccessMessage(null);
      mutation.reset();
    }
    // mutation.reset is a stable reference from TanStack; intentionally
    // not listed in the deps to keep this to an open→reset effect only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const handleSubmit = useCallback(
    (e?: React.FormEvent) => {
      e?.preventDefault();
      const trimmed = url.trim();
      if (!trimmed) return;
      mutation.mutate(trimmed);
    },
    [url, mutation],
  );

  // Esc closes. Only bind while open so we don't interfere with
  // other page-level shortcuts when the modal is hidden.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const errorDetail =
    mutation.error instanceof ApiError
      ? mutation.error.message
      : mutation.error
        ? "Could not submit link. Please try again."
        : null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      // Click-outside to close — preserves the convention used by the
      // app's other modals. Inner card stops propagation.
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-labelledby="submit-link-title"
    >
      <div
        className="w-full max-w-lg rounded-xl bg-white shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between border-b border-gray-200 px-5 py-4">
          <div>
            <h2 id="submit-link-title" className="text-lg font-semibold text-gray-900">
              Submit job link
            </h2>
            <p className="mt-0.5 text-xs text-gray-500">
              Paste a Greenhouse / Lever / Ashby / Workable / BambooHR / SmartRecruiters / Jobvite / Recruitee URL.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
            aria-label="Close"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4 px-5 py-4">
          <div>
            <label htmlFor="submit-link-url" className="label">
              Job URL
            </label>
            <div className="relative">
              <LinkIcon className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
              <input
                id="submit-link-url"
                type="url"
                autoFocus
                className="input pl-9"
                placeholder="https://boards.greenhouse.io/example/jobs/1234567"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                disabled={mutation.isPending || !!successMessage}
              />
            </div>
          </div>

          {errorDetail && !successMessage && (
            <div className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 ring-1 ring-red-200">
              {errorDetail}
            </div>
          )}

          {successMessage && (
            <div className="flex items-start gap-2 rounded-md bg-green-50 px-3 py-2 text-sm text-green-800 ring-1 ring-green-200">
              <CheckCircle2 className="mt-0.5 h-4 w-4 flex-none text-green-600" />
              <div className="flex-1">
                <p className="font-medium">
                  {successMessage.isNew ? "Imported" : "Already in the system"}
                </p>
                <p className="text-xs">
                  {successMessage.title} · {successMessage.companyName}
                </p>
                {onOpenJob && (
                  <button
                    type="button"
                    className="mt-1 text-xs font-medium underline"
                    onClick={() => {
                      onOpenJob(successMessage.jobId);
                      onClose();
                    }}
                  >
                    View job
                  </button>
                )}
              </div>
            </div>
          )}

          <div className="flex items-center justify-end gap-2 border-t border-gray-200 pt-4">
            <Button type="button" variant="secondary" size="md" onClick={onClose}>
              Close
            </Button>
            {!successMessage && (
              <Button
                type="submit"
                variant="primary"
                size="md"
                loading={mutation.isPending}
                disabled={!url.trim()}
              >
                Submit
              </Button>
            )}
          </div>
        </form>
      </div>
    </div>
  );
}
