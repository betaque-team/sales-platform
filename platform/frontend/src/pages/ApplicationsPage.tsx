import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getApplications, getApplicationStats, updateApplication, deleteApplication, getApplication } from "@/lib/api";
import { Send, Briefcase, Clock, Trophy, Trash2, ExternalLink, ChevronLeft, ChevronRight, FileCheck, Mail, XCircle, LogOut, FileText } from "lucide-react";
import { BackendErrorBanner } from "@/components/BackendErrorBanner";
import type { ApplicationDetail } from "@/lib/types";

const STATUS_TABS: { label: string; value: string }[] = [
  { label: "All", value: "" },
  { label: "Prepared", value: "prepared" },
  { label: "Submitted", value: "submitted" },
  { label: "Applied", value: "applied" },
  { label: "Interview", value: "interview" },
  { label: "Offer", value: "offer" },
  { label: "Rejected", value: "rejected" },
  { label: "Withdrawn", value: "withdrawn" },
];

const STATUS_COLORS: Record<string, string> = {
  prepared: "bg-gray-100 text-gray-700",
  submitted: "bg-blue-100 text-blue-700",
  applied: "bg-indigo-100 text-indigo-700",
  interview: "bg-yellow-100 text-yellow-700",
  offer: "bg-green-100 text-green-700",
  rejected: "bg-red-100 text-red-700",
  withdrawn: "bg-gray-100 text-gray-500",
};

const VALID_TRANSITIONS: Record<string, string[]> = {
  prepared: ["applied", "withdrawn"],
  submitted: ["applied", "withdrawn"],
  applied: ["interview", "rejected", "withdrawn"],
  interview: ["offer", "rejected", "withdrawn"],
  offer: ["rejected", "withdrawn"],
  rejected: [],
  withdrawn: [],
};

export function ApplicationsPage() {
  const navigate = useNavigate();
  const [statusFilter, setStatusFilter] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  // Feature C — id of the application whose apply-time snapshot is
  // currently displayed in the modal. null = modal closed.
  const [snapshotOpenFor, setSnapshotOpenFor] = useState<string | null>(null);
  const queryClient = useQueryClient();

  // F222: destructure full query objects for banner-backed error surfacing.
  const statsQ = useQuery({
    queryKey: ["application-stats"],
    queryFn: getApplicationStats,
  });
  const stats = statsQ.data;

  const applicationsQ = useQuery({
    queryKey: ["applications", statusFilter, search, page],
    queryFn: () => getApplications({ status: statusFilter || undefined, search: search || undefined, page, page_size: 25 }),
  });
  const { data, isLoading } = applicationsQ;

  const updateMutation = useMutation({
    mutationFn: ({ id, ...data }: { id: string; status?: string; notes?: string }) => updateApplication(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["applications"] });
      queryClient.invalidateQueries({ queryKey: ["application-stats"] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deleteApplication,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["applications"] });
      queryClient.invalidateQueries({ queryKey: ["application-stats"] });
    },
  });

  // Regression finding 55: stat cards now cover all 8 application statuses
  // instead of only Total/Applied/Interview/Offer.
  const statCards = [
    { label: "Total", value: stats?.total ?? 0, icon: Briefcase, color: "text-gray-700 bg-gray-100" },
    { label: "Prepared", value: stats?.prepared ?? 0, icon: FileCheck, color: "text-gray-600 bg-gray-100" },
    { label: "Submitted", value: stats?.submitted ?? 0, icon: Mail, color: "text-blue-700 bg-blue-100" },
    { label: "Applied", value: stats?.applied ?? 0, icon: Send, color: "text-indigo-700 bg-indigo-100" },
    { label: "Interview", value: stats?.interview ?? 0, icon: Clock, color: "text-yellow-700 bg-yellow-100" },
    { label: "Offer", value: stats?.offer ?? 0, icon: Trophy, color: "text-green-700 bg-green-100" },
    { label: "Rejected", value: stats?.rejected ?? 0, icon: XCircle, color: "text-red-700 bg-red-100" },
    { label: "Withdrawn", value: stats?.withdrawn ?? 0, icon: LogOut, color: "text-gray-500 bg-gray-100" },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Applications</h1>
        <p className="text-sm text-gray-500 mt-1">Track your job applications</p>
      </div>

      {/* F222: surfaces stats/list failures. */}
      <BackendErrorBanner queries={[statsQ, applicationsQ]} />

      {/* Stats */}
      <div className="grid grid-cols-4 gap-3 lg:grid-cols-8">
        {statCards.map((s) => (
          <div key={s.label} className="rounded-lg border border-gray-200 bg-white p-3">
            <div className="flex items-center gap-2">
              <div className={`rounded-lg p-1.5 ${s.color}`}>
                <s.icon className="h-4 w-4" />
              </div>
              <div>
                <p className="text-lg font-bold text-gray-900">{s.value}</p>
                <p className="text-xs text-gray-500">{s.label}</p>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Filters */}
      <div className="flex items-center gap-4">
        <div className="flex gap-1 rounded-lg border border-gray-200 bg-white p-1">
          {STATUS_TABS.map((tab) => (
            <button
              key={tab.value}
              onClick={() => { setStatusFilter(tab.value); setPage(1); }}
              className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                statusFilter === tab.value
                  ? "bg-primary-100 text-primary-700"
                  : "text-gray-600 hover:bg-gray-50"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
        <input
          type="text"
          placeholder="Search by job title or company..."
          value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(1); }}
          className="w-64 rounded-lg border border-gray-200 px-3 py-1.5 text-sm"
        />
      </div>

      {/* Table */}
      <div className="rounded-lg border border-gray-200 bg-white">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100">
              <th className="px-4 py-3 text-left font-medium text-gray-500">Job</th>
              <th className="px-4 py-3 text-left font-medium text-gray-500">Company</th>
              <th className="px-4 py-3 text-left font-medium text-gray-500">Platform</th>
              <th className="px-4 py-3 text-left font-medium text-gray-500">Resume</th>
              <th className="px-4 py-3 text-left font-medium text-gray-500">Source</th>
              <th className="px-4 py-3 text-left font-medium text-gray-500">Status</th>
              <th className="px-4 py-3 text-left font-medium text-gray-500">Date</th>
              <th className="px-4 py-3 text-left font-medium text-gray-500">Actions</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr><td colSpan={8} className="px-4 py-8 text-center text-gray-400">Loading...</td></tr>
            ) : data?.items.length === 0 ? (
              <tr><td colSpan={8} className="px-4 py-12 text-center">
                {/* Regression finding 54: instructional empty-state with links */}
                <Briefcase className="mx-auto h-10 w-10 text-gray-300" />
                <p className="mt-3 text-sm font-medium text-gray-900">No applications yet</p>
                <p className="mt-1 text-sm text-gray-500">
                  Browse the{" "}
                  <Link to="/review" className="font-medium text-primary-600 hover:text-primary-700 underline">Review Queue</Link>
                  {" "}to accept jobs, or visit{" "}
                  <Link to="/jobs?role_cluster=relevant" className="font-medium text-primary-600 hover:text-primary-700 underline">Relevant Jobs</Link>
                  {" "}and click Apply to get started.
                </p>
              </td></tr>
            ) : (
              data?.items.map((app) => (
                <tr key={app.id} className="border-b border-gray-50 hover:bg-gray-50">
                  <td className="px-4 py-3">
                    <button
                      onClick={() => navigate(`/jobs/${app.job_id}`)}
                      className="font-medium text-gray-900 hover:text-primary-600 text-left"
                    >
                      {app.job_title}
                    </button>
                  </td>
                  <td className="px-4 py-3 text-gray-600">{app.company_name}</td>
                  <td className="px-4 py-3">
                    <span className="rounded bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600">
                      {app.platform}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-600">{app.resume_label || "—"}</td>
                  <td className="px-4 py-3">
                    {/* Feature C — provenance badge. `review_queue` =
                        created via the Applied button in the Review
                        Queue (carries an apply-time resume snapshot);
                        `manual_prepare` = classic /applications/prepare
                        flow. Legacy rows with no submission_source
                        render as `manual_prepare` by DB default. */}
                    {app.submission_source === "review_queue" ? (
                      <span className="rounded-full bg-indigo-50 px-2 py-0.5 text-[11px] font-medium text-indigo-700 ring-1 ring-indigo-200">
                        Review queue
                        {typeof app.applied_resume_score_overall === "number" && (
                          <span className="ml-1 opacity-75">
                            · {app.applied_resume_score_overall}
                          </span>
                        )}
                      </span>
                    ) : (
                      <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-600">
                        Manual
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {(VALID_TRANSITIONS[app.status]?.length ?? 0) > 0 ? (
                      <select
                        value={app.status}
                        onChange={(e) => updateMutation.mutate({ id: app.id, status: e.target.value })}
                        className={`rounded-full px-2.5 py-0.5 text-xs font-medium border-0 cursor-pointer ${STATUS_COLORS[app.status] || ""}`}
                      >
                        <option value={app.status}>
                          {STATUS_TABS.find((t) => t.value === app.status)?.label || app.status}
                        </option>
                        {(VALID_TRANSITIONS[app.status] || []).map((s) => (
                          <option key={s} value={s}>
                            {STATUS_TABS.find((t) => t.value === s)?.label || s}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${STATUS_COLORS[app.status] || ""}`}>
                        {STATUS_TABS.find((t) => t.value === app.status)?.label || app.status}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-gray-500 text-xs">
                    {app.applied_at
                      ? new Date(app.applied_at).toLocaleDateString()
                      : new Date(app.created_at).toLocaleDateString()}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => navigate(`/jobs/${app.job_id}`)}
                        className="rounded p-1 text-gray-400 hover:bg-primary-50 hover:text-primary-600"
                        title="View job details & apply"
                      >
                        <Send className="h-4 w-4" />
                      </button>
                      {app.job_url && (
                        <a href={app.job_url} target="_blank" rel="noopener noreferrer"
                          className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600" title="Open ATS page">
                          <ExternalLink className="h-4 w-4" />
                        </a>
                      )}
                      {/* Feature C — "What we sent" modal trigger. Only
                          shown for rows that have a snapshot (review_queue
                          origin), since manual_prepare rows don't carry
                          the resume text + score snapshot. */}
                      {app.submission_source === "review_queue" && (
                        <button
                          onClick={() => setSnapshotOpenFor(app.id)}
                          className="rounded p-1 text-gray-400 hover:bg-primary-50 hover:text-primary-600"
                          title="What we sent"
                        >
                          <FileText className="h-4 w-4" />
                        </button>
                      )}
                      {app.status === "prepared" && (
                        <button
                          onClick={() => deleteMutation.mutate(app.id)}
                          className="rounded p-1 text-gray-400 hover:bg-red-50 hover:text-red-600" title="Delete">
                          <Trash2 className="h-4 w-4" />
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>

        {/* Pagination */}
        {data && data.total_pages > 1 && (
          <div className="flex items-center justify-between border-t border-gray-100 px-4 py-3">
            <span className="text-sm text-gray-500">
              Page {data.page} of {data.total_pages} ({data.total} total)
            </span>
            <div className="flex gap-1">
              <button
                onClick={() => setPage(Math.max(1, page - 1))}
                disabled={page <= 1}
                className="rounded p-1 text-gray-400 hover:bg-gray-100 disabled:opacity-30"
              >
                <ChevronLeft className="h-5 w-5" />
              </button>
              <button
                onClick={() => setPage(Math.min(data.total_pages, page + 1))}
                disabled={page >= data.total_pages}
                className="rounded p-1 text-gray-400 hover:bg-gray-100 disabled:opacity-30"
              >
                <ChevronRight className="h-5 w-5" />
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Feature C — apply-time snapshot modal. Fetches the full detail
          payload on demand (the list endpoint doesn't ship the resume
          text). Shows which resume + score + exact resume body were
          submitted, so an edit to the underlying resume later can't
          obscure what the application actually contained. */}
      {snapshotOpenFor && (
        <ApplySnapshotModal
          applicationId={snapshotOpenFor}
          onClose={() => setSnapshotOpenFor(null)}
        />
      )}
    </div>
  );
}


function ApplySnapshotModal({ applicationId, onClose }: { applicationId: string; onClose: () => void }) {
  // Dedicated query key so a closed-then-reopened modal refetches (users
  // expect "what we sent" to reflect any subsequent status transitions).
  const detailQ = useQuery<ApplicationDetail>({
    queryKey: ["application", applicationId],
    queryFn: () => getApplication(applicationId) as Promise<ApplicationDetail>,
  });

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      <div
        className="flex max-h-[85vh] w-full max-w-2xl flex-col rounded-xl bg-white shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between border-b border-gray-200 px-5 py-4">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">What we sent</h2>
            <p className="mt-0.5 text-xs text-gray-500">
              Snapshot of the resume + score used when this application was submitted.
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
            aria-label="Close"
          >
            <XCircle className="h-5 w-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
          {detailQ.isLoading && (
            <p className="text-sm text-gray-500">Loading snapshot…</p>
          )}
          {detailQ.isError && (
            <p className="text-sm text-red-600">Could not load snapshot.</p>
          )}
          {detailQ.data && (() => {
            const d = detailQ.data;
            const snap = d.applied_resume_score_snapshot;
            return (
              <>
                <div className="rounded-md bg-gray-50 px-4 py-3 text-sm">
                  <div className="font-medium text-gray-900">{d.job.title}</div>
                  <div className="text-xs text-gray-500">{d.job.company_name} · {d.job.platform}</div>
                  <div className="mt-2 text-xs text-gray-600">
                    Resume used: <span className="font-medium">{d.resume.label}</span>
                  </div>
                  {d.applied_at && (
                    <div className="text-xs text-gray-600">
                      Submitted: {new Date(d.applied_at).toLocaleString()}
                    </div>
                  )}
                </div>

                {snap && (
                  <div>
                    <p className="mb-2 text-xs font-medium uppercase tracking-wide text-gray-500">
                      Score at submit-time
                    </p>
                    <div className="grid grid-cols-4 gap-2 text-sm">
                      <ScoreTile label="Overall" value={snap.overall} />
                      <ScoreTile label="Keyword" value={snap.keyword} />
                      <ScoreTile label="Role match" value={snap.role_match} />
                      <ScoreTile label="Format" value={snap.format} />
                    </div>
                  </div>
                )}

                <div>
                  <p className="mb-2 text-xs font-medium uppercase tracking-wide text-gray-500">
                    Resume body sent
                  </p>
                  {d.applied_resume_text ? (
                    <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-md bg-gray-50 p-3 text-xs text-gray-700 ring-1 ring-gray-200">
                      {d.applied_resume_text}
                    </pre>
                  ) : (
                    <p className="text-xs italic text-gray-400">
                      No resume text snapshot (legacy row).
                    </p>
                  )}
                </div>

                {d.ai_customization_log_id && (
                  <p className="text-xs text-gray-500">
                    ✨ AI-customized resume (log id {d.ai_customization_log_id.slice(0, 8)}…)
                  </p>
                )}
              </>
            );
          })()}
        </div>
      </div>
    </div>
  );
}


function ScoreTile({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md bg-gray-50 px-3 py-2 text-center ring-1 ring-gray-200">
      <div className="text-lg font-semibold text-gray-900">{value}</div>
      <div className="text-[10px] uppercase tracking-wide text-gray-500">{label}</div>
    </div>
  );
}
