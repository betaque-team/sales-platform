import { useState, useRef, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "../lib/auth";
import {
  createFeedback,
  getFeedbackList,
  updateFeedback,
  getFeedbackStats,
  uploadFeedbackAttachment,
  deleteFeedbackAttachment,
} from "../lib/api";
import type {
  FeedbackCategory,
  FeedbackPriority,
  FeedbackStatus,
  Feedback,
  FeedbackCreate,
  FeedbackAttachment,
} from "../lib/types";

const CATEGORY_CONFIG: Record<
  FeedbackCategory,
  { label: string; color: string; emoji: string; description: string }
> = {
  bug: {
    label: "Bug Report",
    color: "bg-red-100 text-red-800",
    emoji: "\uD83D\uDC1B",
    description: "Something isn't working correctly",
  },
  feature_request: {
    label: "New Feature",
    color: "bg-purple-100 text-purple-800",
    emoji: "\u2728",
    description: "Suggest a new capability",
  },
  improvement: {
    label: "Improvement",
    color: "bg-blue-100 text-blue-800",
    emoji: "\uD83D\uDD27",
    description: "Enhance an existing feature",
  },
  question: {
    label: "Question",
    color: "bg-yellow-100 text-yellow-800",
    emoji: "\u2753",
    description: "Ask about how something works",
  },
};

const PRIORITY_CONFIG: Record<FeedbackPriority, { label: string; color: string }> = {
  critical: { label: "Critical", color: "bg-red-600 text-white" },
  high: { label: "High", color: "bg-orange-100 text-orange-800" },
  medium: { label: "Medium", color: "bg-yellow-100 text-yellow-800" },
  low: { label: "Low", color: "bg-gray-100 text-gray-600" },
};

const STATUS_CONFIG: Record<FeedbackStatus, { label: string; color: string }> = {
  open: { label: "Open", color: "bg-blue-100 text-blue-800" },
  in_progress: { label: "In Progress", color: "bg-purple-100 text-purple-800" },
  resolved: { label: "Resolved", color: "bg-green-100 text-green-800" },
  closed: { label: "Closed", color: "bg-gray-100 text-gray-600" },
};

function Badge({ className, children }: { className: string; children: React.ReactNode }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${className}`}>
      {children}
    </span>
  );
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function isImageType(contentType: string): boolean {
  return contentType.startsWith("image/");
}

// ---- File Drop Zone ----
function FileDropZone({
  feedbackId,
  attachments,
  onUploaded,
}: {
  feedbackId: string;
  attachments: FeedbackAttachment[];
  onUploaded: () => void;
}) {
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const handleFiles = useCallback(
    async (files: FileList | File[]) => {
      setError("");
      setUploading(true);
      for (const file of Array.from(files)) {
        try {
          await uploadFeedbackAttachment(feedbackId, file);
        } catch (err: any) {
          setError(err.message || "Upload failed");
        }
      }
      setUploading(false);
      onUploaded();
    },
    [feedbackId, onUploaded]
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      if (e.dataTransfer.files.length) handleFiles(e.dataTransfer.files);
    },
    [handleFiles]
  );

  return (
    <div className="space-y-3">
      {/* Drop area */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        onClick={() => fileRef.current?.click()}
        className={`flex flex-col items-center justify-center rounded-lg border-2 border-dashed p-6 cursor-pointer transition ${
          dragging
            ? "border-primary-400 bg-primary-50"
            : "border-gray-300 hover:border-gray-400 hover:bg-gray-50"
        }`}
      >
        <input
          ref={fileRef}
          type="file"
          multiple
          className="hidden"
          accept="image/*,.pdf,.txt,.csv,.xlsx,.docx"
          onChange={(e) => e.target.files && handleFiles(e.target.files)}
        />
        {uploading ? (
          <div className="flex items-center gap-2 text-sm text-gray-500">
            <div className="spinner h-4 w-4" />
            Uploading...
          </div>
        ) : (
          <>
            <svg className="h-8 w-8 text-gray-400 mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 16V4m0 0l-4 4m4-4l4 4M4 20h16" />
            </svg>
            <p className="text-sm text-gray-600">
              Drop files here or <span className="text-primary-600 font-medium">browse</span>
            </p>
            <p className="text-xs text-gray-400 mt-1">Images, PDF, DOCX, CSV up to 10 MB</p>
          </>
        )}
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}

      {/* Attachment list */}
      {attachments.length > 0 && (
        <div className="space-y-2">
          {attachments.map((att) => (
            <AttachmentItem key={att.filename} attachment={att} feedbackId={feedbackId} onDeleted={onUploaded} />
          ))}
        </div>
      )}
    </div>
  );
}

function AttachmentItem({
  attachment,
  feedbackId,
  onDeleted,
  readOnly,
}: {
  attachment: FeedbackAttachment;
  feedbackId: string;
  onDeleted?: () => void;
  readOnly?: boolean;
}) {
  const [deleting, setDeleting] = useState(false);

  const handleDelete = async () => {
    setDeleting(true);
    try {
      await deleteFeedbackAttachment(feedbackId, attachment.filename);
      onDeleted?.();
    } catch {
      setDeleting(false);
    }
  };

  const url = `/api/v1/feedback/attachments/${attachment.filename}`;
  const isImage = isImageType(attachment.content_type);

  return (
    <div className="flex items-center gap-3 rounded-lg border bg-gray-50 p-2.5">
      {isImage ? (
        <a href={url} target="_blank" rel="noopener noreferrer" className="flex-shrink-0">
          <img src={url} alt={attachment.original_name} className="h-10 w-10 rounded object-cover" />
        </a>
      ) : (
        <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded bg-gray-200 text-gray-500 text-xs font-bold">
          {attachment.original_name.split(".").pop()?.toUpperCase() || "?"}
        </div>
      )}
      <div className="flex-1 min-w-0">
        <a href={url} target="_blank" rel="noopener noreferrer" className="text-sm font-medium text-gray-700 hover:text-primary-600 truncate block">
          {attachment.original_name}
        </a>
        <p className="text-xs text-gray-400">{formatFileSize(attachment.size)}</p>
      </div>
      {!readOnly && (
        <button
          onClick={handleDelete}
          disabled={deleting}
          className="text-gray-400 hover:text-red-500 transition p-1"
          title="Remove"
        >
          {deleting ? <div className="spinner h-4 w-4" /> : (
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          )}
        </button>
      )}
    </div>
  );
}

// ---- Submit Form ----
function SubmitFeedbackForm({ onSuccess }: { onSuccess: (id: string) => void }) {
  const [category, setCategory] = useState<FeedbackCategory | "">("");
  const [priority, setPriority] = useState<FeedbackPriority>("medium");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [stepsToReproduce, setStepsToReproduce] = useState("");
  const [expectedBehavior, setExpectedBehavior] = useState("");
  const [actualBehavior, setActualBehavior] = useState("");
  const [useCase, setUseCase] = useState("");
  const [proposedSolution, setProposedSolution] = useState("");
  const [impact, setImpact] = useState("");
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const fileRef = useRef<HTMLInputElement>(null);

  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: async (data: FeedbackCreate) => {
      // Create ticket first
      const fb = await createFeedback(data);
      // Upload pending files
      for (const file of pendingFiles) {
        try {
          await uploadFeedbackAttachment(fb.id, file);
        } catch {
          // Non-blocking: ticket created, attachment failed
        }
      }
      return fb;
    },
    onSuccess: (fb) => {
      queryClient.invalidateQueries({ queryKey: ["feedback"] });
      setCategory("");
      setTitle("");
      setDescription("");
      setStepsToReproduce("");
      setExpectedBehavior("");
      setActualBehavior("");
      setUseCase("");
      setProposedSolution("");
      setImpact("");
      setPendingFiles([]);
      onSuccess(fb.id);
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!category) return;
    const data: FeedbackCreate = {
      category,
      priority,
      title,
      description,
      ...(stepsToReproduce && { steps_to_reproduce: stepsToReproduce }),
      ...(expectedBehavior && { expected_behavior: expectedBehavior }),
      ...(actualBehavior && { actual_behavior: actualBehavior }),
      ...(useCase && { use_case: useCase }),
      ...(proposedSolution && { proposed_solution: proposedSolution }),
      ...(impact && { impact }),
    };
    mutation.mutate(data);
  };

  const addFiles = (files: FileList | null) => {
    if (!files) return;
    setPendingFiles((prev) => [...prev, ...Array.from(files)]);
  };

  const removeFile = (idx: number) => {
    setPendingFiles((prev) => prev.filter((_, i) => i !== idx));
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      {!category ? (
        <div>
          <h3 id="feedback-category-label" className="text-sm font-medium text-gray-700 mb-3">What type of feedback?</h3>
          <div className="grid grid-cols-2 gap-3" role="radiogroup" aria-labelledby="feedback-category-label">
            {(Object.entries(CATEGORY_CONFIG) as [FeedbackCategory, typeof CATEGORY_CONFIG.bug][]).map(
              ([key, cfg]) => (
                <button
                  key={key}
                  type="button"
                  role="radio"
                  aria-checked={false}
                  onClick={() => setCategory(key)}
                  className="flex flex-col items-start rounded-lg border-2 border-gray-200 p-4 text-left transition hover:border-primary-500 hover:bg-primary-50"
                >
                  <span className="text-2xl mb-1">{cfg.emoji}</span>
                  <span className="text-sm font-semibold text-gray-900">{cfg.label}</span>
                  <span className="text-xs text-gray-500">{cfg.description}</span>
                </button>
              )
            )}
          </div>
        </div>
      ) : (
        <>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-xl">{CATEGORY_CONFIG[category].emoji}</span>
              <h3 className="text-lg font-semibold">{CATEGORY_CONFIG[category].label}</h3>
            </div>
            <button type="button" onClick={() => setCategory("")} className="text-sm text-gray-500 hover:text-gray-700">
              Change type
            </button>
          </div>

          <div>
            <label htmlFor="feedback-title" className="block text-sm font-medium text-gray-700 mb-1">
              Title <span className="text-red-500">*</span>
            </label>
            <input
              id="feedback-title"
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={
                category === "bug"
                  ? "e.g., Search filter resets when switching pages"
                  : category === "feature_request"
                  ? "e.g., Add bulk export for pipeline contacts"
                  : "Brief summary of your feedback"
              }
              className="input w-full"
              required
              minLength={5}
              maxLength={200}
            />
          </div>

          <div>
            <label id="feedback-priority-label" className="block text-sm font-medium text-gray-700 mb-1">Priority</label>
            <div className="flex gap-2" role="radiogroup" aria-labelledby="feedback-priority-label">
              {(Object.entries(PRIORITY_CONFIG) as [FeedbackPriority, typeof PRIORITY_CONFIG.low][]).map(
                ([key, cfg]) => (
                  <button
                    key={key}
                    type="button"
                    role="radio"
                    aria-checked={priority === key}
                    onClick={() => setPriority(key)}
                    className={`rounded-full px-3 py-1 text-xs font-medium transition ${
                      priority === key ? cfg.color + " ring-2 ring-offset-1 ring-gray-400" : "bg-gray-50 text-gray-500 hover:bg-gray-100"
                    }`}
                  >
                    {cfg.label}
                  </button>
                )
              )}
            </div>
          </div>

          <div>
            <label htmlFor="feedback-description" className="block text-sm font-medium text-gray-700 mb-1">
              Description <span className="text-red-500">*</span>
            </label>
            <textarea
              id="feedback-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={4}
              placeholder="Provide a detailed description..."
              className="input w-full"
              required
              minLength={20}
            />
          </div>

          {category === "bug" && (
            <>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Steps to Reproduce <span className="text-red-500">*</span>
                </label>
                <textarea
                  value={stepsToReproduce}
                  onChange={(e) => setStepsToReproduce(e.target.value)}
                  rows={4}
                  placeholder={"1. Go to the Jobs page\n2. Apply a filter for 'Infrastructure'\n3. Navigate to page 2\n4. Observe the filter resets to 'All'"}
                  className="input w-full font-mono text-sm"
                  required
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Expected Behavior <span className="text-red-500">*</span>
                  </label>
                  <textarea
                    value={expectedBehavior}
                    onChange={(e) => setExpectedBehavior(e.target.value)}
                    rows={3}
                    placeholder="What should happen?"
                    className="input w-full"
                    required
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Actual Behavior <span className="text-red-500">*</span>
                  </label>
                  <textarea
                    value={actualBehavior}
                    onChange={(e) => setActualBehavior(e.target.value)}
                    rows={3}
                    placeholder="What actually happens?"
                    className="input w-full"
                    required
                  />
                </div>
              </div>
            </>
          )}

          {category === "feature_request" && (
            <>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Use Case <span className="text-red-500">*</span>
                </label>
                <textarea
                  value={useCase}
                  onChange={(e) => setUseCase(e.target.value)}
                  rows={3}
                  placeholder="Describe the scenario where you need this feature."
                  className="input w-full"
                  required
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Expected Impact <span className="text-red-500">*</span>
                </label>
                <textarea
                  value={impact}
                  onChange={(e) => setImpact(e.target.value)}
                  rows={2}
                  placeholder="How would this impact your workflow?"
                  className="input w-full"
                  required
                />
              </div>
            </>
          )}

          {category === "improvement" && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Expected Impact</label>
              <textarea
                value={impact}
                onChange={(e) => setImpact(e.target.value)}
                rows={2}
                placeholder="How would this improvement help you?"
                className="input w-full"
              />
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Proposed Solution <span className="text-gray-400">(optional)</span>
            </label>
            <textarea
              value={proposedSolution}
              onChange={(e) => setProposedSolution(e.target.value)}
              rows={2}
              placeholder="If you have a suggestion for how to solve this..."
              className="input w-full"
            />
          </div>

          {/* File attachments */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Attachments <span className="text-gray-400">(optional)</span>
            </label>
            <div
              onClick={() => fileRef.current?.click()}
              className="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-gray-300 p-4 cursor-pointer transition hover:border-gray-400 hover:bg-gray-50"
            >
              <input
                ref={fileRef}
                type="file"
                multiple
                className="hidden"
                accept="image/*,.pdf,.txt,.csv,.xlsx,.docx"
                onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }}
              />
              <p className="text-sm text-gray-600">
                Click to attach files <span className="text-xs text-gray-400">(images, PDF, DOCX, CSV up to 10 MB)</span>
              </p>
            </div>
            {pendingFiles.length > 0 && (
              <div className="mt-2 space-y-1.5">
                {pendingFiles.map((f, i) => (
                  <div key={i} className="flex items-center gap-3 rounded-lg border bg-gray-50 p-2.5">
                    <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded bg-gray-200 text-gray-500 text-xs font-bold">
                      {f.name.split(".").pop()?.toUpperCase() || "?"}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-gray-700 truncate">{f.name}</p>
                      <p className="text-xs text-gray-400">{formatFileSize(f.size)}</p>
                    </div>
                    <button
                      type="button"
                      onClick={() => removeFile(i)}
                      className="text-gray-400 hover:text-red-500 transition p-1"
                    >
                      <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="flex justify-end gap-3 pt-2">
            <button type="button" onClick={() => setCategory("")} className="btn btn-secondary">
              Cancel
            </button>
            <button type="submit" disabled={mutation.isPending} className="btn btn-primary">
              {mutation.isPending ? "Submitting..." : "Submit Ticket"}
            </button>
          </div>

          {mutation.isError && (
            <p className="text-sm text-red-600">
              {(mutation.error as any)?.message || "Failed to submit. Please try again."}
            </p>
          )}
        </>
      )}
    </form>
  );
}

// ---- Detail Modal ----
function FeedbackDetail({
  item,
  isAdmin,
  onClose,
}: {
  item: Feedback;
  isAdmin: boolean;
  onClose: () => void;
}) {
  const [adminNotes, setAdminNotes] = useState(item.admin_notes || "");
  const [status, setStatus] = useState(item.status);
  const [savedFlash, setSavedFlash] = useState(false);
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: (data: { status?: string; admin_notes?: string }) =>
      updateFeedback(item.id, data),
    onSuccess: (updated) => {
      // Update local state from the server response so the badge + form reflect
      // the persisted value before the modal closes.
      if (updated?.status) setStatus(updated.status as FeedbackStatus);
      if (typeof updated?.admin_notes === "string") setAdminNotes(updated.admin_notes);
      queryClient.invalidateQueries({ queryKey: ["feedback"] });
      setSavedFlash(true);
      // Keep the modal open for 900ms so the user sees the confirmation, then close.
      setTimeout(() => {
        setSavedFlash(false);
        onClose();
      }, 900);
    },
  });

  const refetch = () => queryClient.invalidateQueries({ queryKey: ["feedback"] });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div className="mx-4 max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-xl bg-white p-6 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between mb-4">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <Badge className={CATEGORY_CONFIG[item.category]?.color || "bg-gray-100"}>
                {CATEGORY_CONFIG[item.category]?.emoji} {CATEGORY_CONFIG[item.category]?.label}
              </Badge>
              <Badge className={PRIORITY_CONFIG[item.priority]?.color || "bg-gray-100"}>{PRIORITY_CONFIG[item.priority]?.label}</Badge>
              <Badge className={STATUS_CONFIG[item.status]?.color || "bg-gray-100"}>{STATUS_CONFIG[item.status]?.label}</Badge>
            </div>
            <h2 className="text-lg font-semibold text-gray-900">{item.title}</h2>
            <p className="text-sm text-gray-500">
              by {item.user?.name || item.user?.email} on{" "}
              {new Date(item.created_at).toLocaleDateString()}
            </p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl">&times;</button>
        </div>

        <div className="space-y-4 text-sm">
          <div>
            <h4 className="font-medium text-gray-700">Description</h4>
            <p className="mt-1 whitespace-pre-wrap text-gray-600">{item.description}</p>
          </div>

          {item.steps_to_reproduce && (
            <div>
              <h4 className="font-medium text-gray-700">Steps to Reproduce</h4>
              <pre className="mt-1 whitespace-pre-wrap rounded bg-gray-50 p-3 text-gray-600 font-mono text-xs">
                {item.steps_to_reproduce}
              </pre>
            </div>
          )}

          {item.expected_behavior && (
            <div className="grid grid-cols-2 gap-4">
              <div>
                <h4 className="font-medium text-gray-700">Expected</h4>
                <p className="mt-1 text-gray-600">{item.expected_behavior}</p>
              </div>
              <div>
                <h4 className="font-medium text-gray-700">Actual</h4>
                <p className="mt-1 text-gray-600">{item.actual_behavior}</p>
              </div>
            </div>
          )}

          {item.use_case && (
            <div>
              <h4 className="font-medium text-gray-700">Use Case</h4>
              <p className="mt-1 text-gray-600">{item.use_case}</p>
            </div>
          )}

          {item.impact && (
            <div>
              <h4 className="font-medium text-gray-700">Impact</h4>
              <p className="mt-1 text-gray-600">{item.impact}</p>
            </div>
          )}

          {item.proposed_solution && (
            <div>
              <h4 className="font-medium text-gray-700">Proposed Solution</h4>
              <p className="mt-1 text-gray-600">{item.proposed_solution}</p>
            </div>
          )}

          {/* Attachments */}
          {item.attachments && item.attachments.length > 0 && (
            <div>
              <h4 className="font-medium text-gray-700 mb-2">Attachments</h4>
              <div className="space-y-2">
                {item.attachments.map((att) => (
                  <AttachmentItem key={att.filename} attachment={att} feedbackId={item.id} readOnly={!isAdmin} onDeleted={refetch} />
                ))}
              </div>
            </div>
          )}

          {/* Upload more (for admin or author) */}
          {isAdmin && (
            <div>
              <h4 className="font-medium text-gray-700 mb-2">Add Attachment</h4>
              <FileDropZone feedbackId={item.id} attachments={[]} onUploaded={refetch} />
            </div>
          )}

          {item.admin_notes && !isAdmin && (
            <div className="rounded-lg bg-blue-50 p-3">
              <h4 className="font-medium text-blue-800">Admin Response</h4>
              <p className="mt-1 text-blue-700">{item.admin_notes}</p>
            </div>
          )}

          {/* Admin controls */}
          {isAdmin && (
            <div className="border-t pt-4 space-y-3">
              <h4 className="font-semibold text-gray-800">Manage Ticket</h4>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Status</label>
                  <select
                    value={status}
                    onChange={(e) => setStatus(e.target.value as FeedbackStatus)}
                    className="input w-full"
                  >
                    {Object.entries(STATUS_CONFIG).map(([k, v]) => (
                      <option key={k} value={k}>{v.label}</option>
                    ))}
                  </select>
                </div>
                <div className="flex items-end">
                  <button
                    onClick={() => mutation.mutate({ status, admin_notes: adminNotes })}
                    disabled={mutation.isPending}
                    className="btn btn-primary w-full"
                  >
                    {mutation.isPending ? "Saving..." : "Update Ticket"}
                  </button>
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Admin Notes</label>
                <textarea
                  value={adminNotes}
                  onChange={(e) => setAdminNotes(e.target.value)}
                  rows={3}
                  placeholder="Response or internal notes..."
                  className="input w-full"
                />
              </div>
              {savedFlash && (
                <div className="rounded-md bg-green-50 border border-green-200 px-3 py-2 text-sm text-green-700">
                  Saved! Status is now <span className="font-semibold">{STATUS_CONFIG[status]?.label || status}</span>.
                </div>
              )}
              {mutation.isError && (
                <div className="rounded-md bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700">
                  {(mutation.error as Error)?.message || "Failed to update ticket. Please try again."}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ---- Main Page ----
export function FeedbackPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin" || user?.role === "super_admin";
  const [view, setView] = useState<"list" | "submit">("list");
  const [selectedItem, setSelectedItem] = useState<Feedback | null>(null);
  const [filterCategory, setFilterCategory] = useState("");
  const [filterStatus, setFilterStatus] = useState("");
  const [page, setPage] = useState(1);

  const { data, isLoading } = useQuery({
    queryKey: ["feedback", filterCategory, filterStatus, page],
    queryFn: () =>
      getFeedbackList({
        category: filterCategory || undefined,
        status: filterStatus || undefined,
        page,
        page_size: 20,
      }),
  });

  const { data: stats } = useQuery({
    queryKey: ["feedback", "stats"],
    queryFn: getFeedbackStats,
    enabled: isAdmin,
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Tickets</h1>
          <p className="text-sm text-gray-500">
            {isAdmin
              ? "Manage tickets from the team"
              : "Report bugs, request features, or suggest improvements"}
          </p>
        </div>
        <button
          onClick={() => setView(view === "list" ? "submit" : "list")}
          className="btn btn-primary"
        >
          {view === "list" ? "+ New Ticket" : "View All Tickets"}
        </button>
      </div>

      {/* Stats */}
      {isAdmin && stats && (
        <div className="grid grid-cols-4 gap-4">
          {[
            { label: "Total", value: stats.total, color: "text-gray-900" },
            { label: "Open", value: stats.by_status?.open || 0, color: "text-blue-600" },
            { label: "In Progress", value: stats.by_status?.in_progress || 0, color: "text-purple-600" },
            { label: "Resolved", value: stats.by_status?.resolved || 0, color: "text-green-600" },
          ].map((s) => (
            <div key={s.label} className="rounded-lg bg-white border p-4">
              <p className="text-sm text-gray-500">{s.label}</p>
              <p className={`text-2xl font-bold ${s.color}`}>{s.value}</p>
            </div>
          ))}
        </div>
      )}

      {view === "submit" ? (
        <div className="mx-auto max-w-2xl rounded-xl bg-white border p-6">
          <SubmitFeedbackForm onSuccess={() => setView("list")} />
        </div>
      ) : (
        <>
          <div className="flex gap-3">
            <select
              value={filterCategory}
              onChange={(e) => { setFilterCategory(e.target.value); setPage(1); }}
              className="input"
            >
              <option value="">All Categories</option>
              {Object.entries(CATEGORY_CONFIG).map(([k, v]) => (
                <option key={k} value={k}>{v.emoji} {v.label}</option>
              ))}
            </select>
            <select
              value={filterStatus}
              onChange={(e) => { setFilterStatus(e.target.value); setPage(1); }}
              className="input"
            >
              <option value="">All Statuses</option>
              {Object.entries(STATUS_CONFIG).map(([k, v]) => (
                <option key={k} value={k}>{v.label}</option>
              ))}
            </select>
          </div>

          {isLoading ? (
            <div className="flex justify-center py-12">
              <div className="spinner h-8 w-8" />
            </div>
          ) : !data?.items?.length ? (
            <div className="rounded-lg border bg-white p-12 text-center">
              <p className="text-gray-500">No tickets yet.</p>
              <button onClick={() => setView("submit")} className="btn btn-primary mt-4">
                Create the first one
              </button>
            </div>
          ) : (
            <div className="space-y-3">
              {data.items.map((item: Feedback) => (
                <div
                  key={item.id}
                  onClick={() => setSelectedItem(item)}
                  className="flex items-center justify-between rounded-lg border bg-white p-4 cursor-pointer transition hover:shadow-md"
                >
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <Badge className={CATEGORY_CONFIG[item.category]?.color || "bg-gray-100"}>
                        {CATEGORY_CONFIG[item.category]?.emoji} {CATEGORY_CONFIG[item.category]?.label}
                      </Badge>
                      <Badge className={PRIORITY_CONFIG[item.priority]?.color || "bg-gray-100"}>
                        {PRIORITY_CONFIG[item.priority]?.label}
                      </Badge>
                      <Badge className={STATUS_CONFIG[item.status]?.color || "bg-gray-100"}>
                        {STATUS_CONFIG[item.status]?.label}
                      </Badge>
                      {item.attachments && item.attachments.length > 0 && (
                        <span className="text-xs text-gray-400" title={`${item.attachments.length} attachment(s)`}>
                          <svg className="inline h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
                          </svg>
                          {item.attachments.length}
                        </span>
                      )}
                    </div>
                    <h3 className="text-sm font-semibold text-gray-900 truncate">{item.title}</h3>
                    <p className="text-xs text-gray-500 truncate">{item.description}</p>
                  </div>
                  <div className="ml-4 text-right flex-shrink-0">
                    <p className="text-xs text-gray-500">{item.user?.name}</p>
                    <p className="text-xs text-gray-400">
                      {new Date(item.created_at).toLocaleDateString()}
                    </p>
                  </div>
                </div>
              ))}

              {data.total_pages > 1 && (
                <div className="flex justify-center gap-2 pt-4">
                  <button disabled={page === 1} onClick={() => setPage(page - 1)} className="btn btn-secondary text-sm">
                    Previous
                  </button>
                  <span className="flex items-center px-3 text-sm text-gray-500">
                    {page} / {data.total_pages}
                  </span>
                  <button disabled={page >= data.total_pages} onClick={() => setPage(page + 1)} className="btn btn-secondary text-sm">
                    Next
                  </button>
                </div>
              )}
            </div>
          )}
        </>
      )}

      {selectedItem && (
        <FeedbackDetail
          item={selectedItem}
          isAdmin={isAdmin}
          onClose={() => setSelectedItem(null)}
        />
      )}
    </div>
  );
}
