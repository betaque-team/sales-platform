import { useState, useCallback, useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Search, Filter, CheckSquare, X, Send, ArrowUp, ArrowDown, ArrowUpDown } from "lucide-react";
import { Card } from "@/components/Card";
import { Button } from "@/components/Button";
import { StatusBadge } from "@/components/StatusBadge";
import { ScoreBar } from "@/components/ScoreBar";
import { Badge } from "@/components/Badge";
import { Pagination } from "@/components/Pagination";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/Table";
import { getJobs, bulkAction, getActiveResume, prepareApplication } from "@/lib/api";
import type { JobFilters, JobStatus } from "@/lib/types";

const STATUS_OPTIONS: { value: JobStatus | ""; label: string }[] = [
  { value: "", label: "All Statuses" },
  { value: "new", label: "New" },
  { value: "under_review", label: "Under Review" },
  { value: "accepted", label: "Accepted" },
  { value: "rejected", label: "Rejected" },
  { value: "expired", label: "Expired" },
];

const PLATFORM_OPTIONS = [
  { value: "", label: "All Platforms" },
  { value: "greenhouse", label: "Greenhouse" },
  { value: "lever", label: "Lever" },
  { value: "ashby", label: "Ashby" },
  { value: "workable", label: "Workable" },
  { value: "linkedin", label: "LinkedIn" },
  { value: "wellfound", label: "Wellfound" },
  { value: "indeed", label: "Indeed" },
  { value: "builtin", label: "Built In" },
  { value: "himalayas", label: "Himalayas" },
  { value: "weworkremotely", label: "WeWorkRemotely" },
  { value: "remoteok", label: "RemoteOK" },
  { value: "remotive", label: "Remotive" },
  { value: "career_page", label: "Career Page" },
];

const GEOGRAPHY_OPTIONS = [
  { value: "", label: "All Geographies" },
  { value: "global_remote", label: "Global Remote" },
  { value: "usa_only", label: "USA Only" },
  { value: "uae_only", label: "UAE Only" },
];

export function JobsPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [searchParams] = useSearchParams();

  const [filters, setFilters] = useState<JobFilters>(() => ({
    search: searchParams.get("search") || "",
    status: (searchParams.get("status") || "") as JobFilters["status"],
    platform: searchParams.get("platform") || "",
    geography: searchParams.get("geography") || "",
    role_cluster: searchParams.get("role_cluster") || "",
    sort_by: searchParams.get("sort_by") || "relevance_score",
    sort_dir: searchParams.get("sort_dir") || "desc",
    page: Number(searchParams.get("page")) || 1,
    page_size: 25,
  }));

  // Re-sync filters when URL params change (e.g. Sidebar navigation between
  // "All Jobs" and "Relevant Jobs" reuses this component without remounting)
  useEffect(() => {
    setFilters({
      search: searchParams.get("search") || "",
      status: (searchParams.get("status") || "") as JobFilters["status"],
      platform: searchParams.get("platform") || "",
      geography: searchParams.get("geography") || "",
      role_cluster: searchParams.get("role_cluster") || "",
      sort_by: searchParams.get("sort_by") || "relevance_score",
      sort_dir: searchParams.get("sort_dir") || "desc",
      page: Number(searchParams.get("page")) || 1,
      page_size: 25,
    });
  }, [searchParams]);

  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  const { data: activeResumeData } = useQuery({
    queryKey: ["active-resume"],
    queryFn: getActiveResume,
  });
  const hasActiveResume = !!activeResumeData?.active_resume;

  const { data, isLoading } = useQuery({
    queryKey: ["jobs", filters],
    queryFn: () => getJobs(filters),
  });

  const [applyingJobId, setApplyingJobId] = useState<string | null>(null);
  const [applyFeedback, setApplyFeedback] = useState<{ jobId: string; msg: string; ok: boolean } | null>(null);

  const applyMutation = useMutation({
    mutationFn: (jobId: string) => prepareApplication(jobId),
    onSuccess: (_data, jobId) => {
      setApplyingJobId(null);
      queryClient.invalidateQueries({ queryKey: ["applications"] });
      queryClient.invalidateQueries({ queryKey: ["application-stats"] });
      // Navigate to job detail page where the full apply panel lives
      navigate(`/jobs/${jobId}`);
    },
    onError: (error: any, jobId) => {
      setApplyingJobId(null);
      if (error?.status === 409 || error?.message?.includes("already")) {
        // Already applied — go to the job detail to see the existing application
        navigate(`/jobs/${jobId}`);
      } else {
        const msg = error?.message || "Failed to prepare";
        setApplyFeedback({ jobId, msg, ok: false });
        setTimeout(() => setApplyFeedback(null), 3000);
      }
    },
  });

  const bulkMutation = useMutation({
    mutationFn: bulkAction,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      setSelectedIds(new Set());
    },
  });

  const updateFilter = useCallback(
    (key: keyof JobFilters, value: string | number) => {
      setFilters((prev) => ({ ...prev, [key]: value, page: key === "page" ? Number(value) : 1 }));
    },
    []
  );

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (!data) return;
    if (selectedIds.size === data.items.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(data.items.map((j) => j.id)));
    }
  };

  const handleBulkAction = (action: "accept" | "reject" | "reset") => {
    bulkMutation.mutate({
      job_ids: Array.from(selectedIds),
      action,
    });
  };

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
    });
  };

  const handleColumnSort = (column: string) => {
    setFilters((prev) => {
      if (prev.sort_by === column) {
        // Toggle direction
        return { ...prev, sort_dir: prev.sort_dir === "desc" ? "asc" : "desc", page: 1 };
      }
      // New column: default to desc for scores/dates, asc for text
      const defaultDir = ["title", "company_name", "platform"].includes(column) ? "asc" : "desc";
      return { ...prev, sort_by: column, sort_dir: defaultDir, page: 1 };
    });
  };

  const SortIcon = ({ column }: { column: string }) => {
    if (filters.sort_by !== column) {
      return <ArrowUpDown className="ml-1 inline h-3 w-3 text-gray-300" />;
    }
    return filters.sort_dir === "asc"
      ? <ArrowUp className="ml-1 inline h-3 w-3 text-primary-600" />
      : <ArrowDown className="ml-1 inline h-3 w-3 text-primary-600" />;
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">
            {filters.role_cluster === "relevant"
              ? "Relevant Jobs"
              : filters.role_cluster
                ? `${filters.role_cluster.charAt(0).toUpperCase() + filters.role_cluster.slice(1)} Jobs`
                : "All Jobs"}
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            {filters.role_cluster === "relevant"
              ? "Cloud, DevOps, SRE, Compliance & Security positions"
              : data ? `${data.total} jobs found` : "Loading jobs..."}
            {data && filters.role_cluster === "relevant" ? ` · ${data.total} jobs found` : ""}
          </p>
        </div>
      </div>

      <Card padding="sm">
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative flex-1 min-w-[200px]">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
            <input
              type="text"
              placeholder="Search jobs by title or company..."
              className="input pl-9"
              value={filters.search}
              onChange={(e) => updateFilter("search", e.target.value)}
            />
          </div>
          <select
            className="select w-auto"
            value={filters.status}
            onChange={(e) => updateFilter("status", e.target.value)}
          >
            {STATUS_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          <select
            className="select w-auto"
            value={filters.platform}
            onChange={(e) => updateFilter("platform", e.target.value)}
          >
            {PLATFORM_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          <select
            className="select w-auto"
            value={filters.geography}
            onChange={(e) => updateFilter("geography", e.target.value)}
          >
            {GEOGRAPHY_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          <select
            className="select w-auto"
            value={filters.role_cluster || ""}
            onChange={(e) => updateFilter("role_cluster", e.target.value)}
          >
            <option value="">All Roles</option>
            <option value="relevant">Relevant (Infra + Security + QA)</option>
            <option value="infra">Infra / Cloud / DevOps / SRE</option>
            <option value="security">Security / Compliance / DevSecOps</option>
            <option value="qa">QA / Testing / SDET</option>
          </select>
          <select
            className="select w-auto"
            value={`${filters.sort_by}:${filters.sort_dir}`}
            onChange={(e) => {
              const [sort_by, sort_dir] = e.target.value.split(":");
              setFilters((prev) => ({ ...prev, sort_by, sort_dir, page: 1 }));
            }}
          >
            <option value="relevance_score:desc">Relevance (High to Low)</option>
            <option value="relevance_score:asc">Relevance (Low to High)</option>
            {hasActiveResume && <option value="resume_score:desc">Resume Match (High to Low)</option>}
            {hasActiveResume && <option value="resume_score:asc">Resume Match (Low to High)</option>}
            <option value="first_seen_at:desc">Newest First</option>
            <option value="first_seen_at:asc">Oldest First</option>
            <option value="title:asc">Title A-Z</option>
            <option value="title:desc">Title Z-A</option>
            <option value="company_name:asc">Company A-Z</option>
            <option value="company_name:desc">Company Z-A</option>
            <option value="platform:asc">Platform A-Z</option>
            <option value="status:asc">Status A-Z</option>
          </select>
          {(filters.search || filters.status || filters.platform || filters.geography || filters.role_cluster) && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() =>
                setFilters({
                  search: "",
                  status: "",
                  platform: "",
                  geography: "",
                  role_cluster: "",
                  sort_by: "relevance_score",
                  sort_dir: "desc",
                  page: 1,
                  page_size: 25,
                })
              }
            >
              <X className="h-4 w-4" />
              Clear
            </Button>
          )}
        </div>
      </Card>

      {selectedIds.size > 0 && (
        <Card padding="sm">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <CheckSquare className="h-4 w-4 text-primary-600" />
              <span className="text-sm font-medium text-gray-700">
                {selectedIds.size} selected
              </span>
            </div>
            <div className="flex items-center gap-2">
              <Button
                variant="primary"
                size="sm"
                onClick={() => handleBulkAction("accept")}
                loading={bulkMutation.isPending}
              >
                Accept
              </Button>
              <Button
                variant="danger"
                size="sm"
                onClick={() => handleBulkAction("reject")}
                loading={bulkMutation.isPending}
              >
                Reject
              </Button>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => handleBulkAction("reset")}
                loading={bulkMutation.isPending}
              >
                Reset
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setSelectedIds(new Set())}
              >
                Cancel
              </Button>
            </div>
          </div>
        </Card>
      )}

      <Card padding="none">
        {isLoading ? (
          <div className="flex items-center justify-center py-20">
            <div className="spinner h-8 w-8" />
          </div>
        ) : data && data.items.length > 0 ? (
          <>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-10">
                    <input
                      type="checkbox"
                      checked={
                        data.items.length > 0 &&
                        selectedIds.size === data.items.length
                      }
                      onChange={toggleSelectAll}
                      className="rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                    />
                  </TableHead>
                  <TableHead className="cursor-pointer select-none" onClick={() => handleColumnSort("title")}>
                    Title <SortIcon column="title" />
                  </TableHead>
                  <TableHead className="cursor-pointer select-none" onClick={() => handleColumnSort("company_name")}>
                    Company <SortIcon column="company_name" />
                  </TableHead>
                  <TableHead className="cursor-pointer select-none" onClick={() => handleColumnSort("platform")}>
                    Platform <SortIcon column="platform" />
                  </TableHead>
                  <TableHead>Remote Scope</TableHead>
                  <TableHead className="cursor-pointer select-none" onClick={() => handleColumnSort("status")}>
                    Status <SortIcon column="status" />
                  </TableHead>
                  <TableHead className="cursor-pointer select-none" onClick={() => handleColumnSort("relevance_score")}>
                    Relevance <SortIcon column="relevance_score" />
                  </TableHead>
                  {hasActiveResume && (
                    <TableHead className="cursor-pointer select-none" onClick={() => handleColumnSort("resume_score")}>
                      ATS Match <SortIcon column="resume_score" />
                    </TableHead>
                  )}
                  <TableHead className="cursor-pointer select-none" onClick={() => handleColumnSort("first_seen_at")} title="First discovered date">
                    Discovered <SortIcon column="first_seen_at" />
                  </TableHead>
                  {hasActiveResume && <TableHead className="w-16">Apply</TableHead>}
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.items.map((job) => (
                  <TableRow
                    key={job.id}
                    clickable
                    onClick={() => navigate(`/jobs/${job.id}`)}
                  >
                    <TableCell onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        checked={selectedIds.has(job.id)}
                        onChange={() => toggleSelect(job.id)}
                        onClick={(e) => e.stopPropagation()}
                        className="rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                      />
                    </TableCell>
                    <TableCell>
                      <div className="max-w-[300px]">
                        <p className="truncate font-medium text-gray-900">
                          {job.title}
                        </p>
                        <div className="mt-0.5 flex gap-1">
                          {job.role_cluster && <Badge variant="gray">{job.role_cluster}</Badge>}
                          {job.geography_bucket && (
                            <Badge variant="gray">
                              {job.geography_bucket.replace(/_/g, " ")}
                            </Badge>
                          )}
                        </div>
                      </div>
                    </TableCell>
                    <TableCell>
                      <span className="font-medium">{job.company_name}</span>
                    </TableCell>
                    <TableCell>{job.source_platform}</TableCell>
                    <TableCell>
                      <span className="max-w-[150px] truncate block text-xs">
                        {job.remote_scope}
                      </span>
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={job.status} />
                    </TableCell>
                    <TableCell>
                      <ScoreBar score={job.relevance_score} />
                    </TableCell>
                    {hasActiveResume && (
                      <TableCell>
                        {job.resume_score != null ? (
                          <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-semibold ${
                            job.resume_score >= 70 ? "bg-green-100 text-green-700" :
                            job.resume_score >= 50 ? "bg-yellow-100 text-yellow-700" :
                            "bg-gray-100 text-gray-500"
                          }`}>
                            {job.resume_score}%
                          </span>
                        ) : (
                          <span className="text-xs text-gray-300">—</span>
                        )}
                      </TableCell>
                    )}
                    <TableCell>{formatDate(job.created_at)}</TableCell>
                    {hasActiveResume && (
                      <TableCell onClick={(e) => e.stopPropagation()}>
                        {applyFeedback?.jobId === job.id ? (
                          <span className={`text-xs font-medium ${applyFeedback.ok ? "text-green-600" : "text-red-500"}`}>
                            {applyFeedback.msg}
                          </span>
                        ) : (
                          <button
                            onClick={() => {
                              setApplyingJobId(job.id);
                              applyMutation.mutate(job.id);
                            }}
                            disabled={applyingJobId === job.id}
                            className="rounded p-1.5 text-primary-600 hover:bg-primary-50 hover:text-primary-700 disabled:opacity-50"
                            title="Prepare & apply to this job"
                          >
                            <Send className="h-4 w-4" />
                          </button>
                        )}
                      </TableCell>
                    )}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <Pagination
              page={data.page}
              totalPages={data.total_pages}
              onPageChange={(p) => updateFilter("page", p)}
            />
          </>
        ) : (
          <div className="py-20 text-center">
            <Filter className="mx-auto h-10 w-10 text-gray-300" />
            <p className="mt-3 text-sm font-medium text-gray-900">
              No jobs found
            </p>
            <p className="mt-1 text-sm text-gray-500">
              Try adjusting your filters or run a new scraping task.
            </p>
          </div>
        )}
      </Card>
    </div>
  );
}
