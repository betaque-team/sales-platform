import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getApplications, getApplicationStats, updateApplication, deleteApplication } from "@/lib/api";
import { Send, Briefcase, Clock, Trophy, Trash2, ExternalLink, ChevronLeft, ChevronRight } from "lucide-react";

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
  const queryClient = useQueryClient();

  const { data: stats } = useQuery({
    queryKey: ["application-stats"],
    queryFn: getApplicationStats,
  });

  const { data, isLoading } = useQuery({
    queryKey: ["applications", statusFilter, search, page],
    queryFn: () => getApplications({ status: statusFilter || undefined, search: search || undefined, page, page_size: 25 }),
  });

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

  const statCards = [
    { label: "Total", value: stats?.total ?? 0, icon: Briefcase, color: "text-gray-700 bg-gray-100" },
    { label: "Applied", value: stats?.applied ?? 0, icon: Send, color: "text-indigo-700 bg-indigo-100" },
    { label: "Interview", value: stats?.interview ?? 0, icon: Clock, color: "text-yellow-700 bg-yellow-100" },
    { label: "Offer", value: stats?.offer ?? 0, icon: Trophy, color: "text-green-700 bg-green-100" },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Applications</h1>
        <p className="text-sm text-gray-500 mt-1">Track your job applications</p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-4 gap-4">
        {statCards.map((s) => (
          <div key={s.label} className="rounded-lg border border-gray-200 bg-white p-4">
            <div className="flex items-center gap-3">
              <div className={`rounded-lg p-2 ${s.color}`}>
                <s.icon className="h-5 w-5" />
              </div>
              <div>
                <p className="text-2xl font-bold text-gray-900">{s.value}</p>
                <p className="text-sm text-gray-500">{s.label}</p>
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
              <th className="px-4 py-3 text-left font-medium text-gray-500">Status</th>
              <th className="px-4 py-3 text-left font-medium text-gray-500">Date</th>
              <th className="px-4 py-3 text-left font-medium text-gray-500">Actions</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr><td colSpan={7} className="px-4 py-8 text-center text-gray-400">Loading...</td></tr>
            ) : data?.items.length === 0 ? (
              <tr><td colSpan={7} className="px-4 py-8 text-center text-gray-400">No applications found</td></tr>
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
    </div>
  );
}
