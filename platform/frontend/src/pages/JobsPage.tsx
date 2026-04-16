import { useState, useCallback, useEffect, useRef } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Search, Filter, CheckSquare, X, Send, ArrowUp, ArrowDown, ArrowUpDown } from "lucide-react";
import { Card } from "@/components/Card";
import { Button } from "@/components/Button";
import { StatusBadge } from "@/components/StatusBadge";
import { ScoreBar } from "@/components/ScoreBar";
import { Badge } from "@/components/Badge";
import { Pagination } from "@/components/Pagination";
import { BackendErrorBanner } from "@/components/BackendErrorBanner";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/Table";
import { getJobs, bulkAction, getActiveResume, prepareApplication, getRoleClusters } from "@/lib/api";
import type {
  JobFilters,
  JobStatus,
  BulkActionStatus,
  BulkFilterCriteria,
} from "@/lib/types";
import { formatCount } from "@/lib/format";

// F69: user-facing verb → backend status mapping. The buttons stay
// labelled Accept/Reject/Reset (what the user intends) but the wire
// payload must be one of the JobStatusLiteral values (F99 tightened
// the backend to reject verbs). The previous code sent the verb
// directly and 422'd in prod on every bulk action — silently,
// because the UI still showed a loading spinner and invalidated
// the query. Kept as a const map so a future status addition lands
// in one place.
const VERB_TO_STATUS: Record<"accept" | "reject" | "reset", BulkActionStatus> = {
  accept: "accepted",
  reject: "rejected",
  reset: "new",
};

// Regression finding 87: synthetic dropdown value used for the
// "Unclassified" option. Keeps the `<select>`'s `value` shape
// stable (always a string) while translating on the wire to
// `is_classified=false` + `role_cluster=""`. Picked a `__…__`
// sentinel so it cannot collide with any admin-defined cluster
// name (`/role-clusters` rejects names starting with `_`).
const UNCLASSIFIED_SENTINEL = "__unclassified__";

const STATUS_OPTIONS: { value: JobStatus | ""; label: string }[] = [
  { value: "", label: "All Statuses" },
  { value: "new", label: "New" },
  { value: "under_review", label: "Under Review" },
  { value: "accepted", label: "Accepted" },
  { value: "rejected", label: "Rejected" },
  { value: "expired", label: "Expired" },
];

// F218 (Round 31 follow-up): backend `PlatformFilter` Literal in
// `platform/backend/app/schemas/job.py` rejects any value outside the set
// of fetcher `PLATFORM` attributes. The previous dropdown listed `indeed`,
// `builtin`, `career_page` — none of which are real fetchers — and was
// missing `bamboohr`, `smartrecruiters`, `jobvite`, `recruitee`. Pre-F218
// the backend silently returned `total:0` for invalid values and missing
// ones were un-filterable; post-F218 invalid values 422. This list is the
// one source of truth for UX and must stay aligned with the backend
// Literal (14 entries; see comment in schemas/job.py).
const PLATFORM_OPTIONS = [
  { value: "", label: "All Platforms" },
  { value: "greenhouse", label: "Greenhouse" },
  { value: "lever", label: "Lever" },
  { value: "ashby", label: "Ashby" },
  { value: "workable", label: "Workable" },
  { value: "bamboohr", label: "BambooHR" },
  { value: "smartrecruiters", label: "SmartRecruiters" },
  { value: "jobvite", label: "Jobvite" },
  { value: "recruitee", label: "Recruitee" },
  { value: "wellfound", label: "Wellfound" },
  { value: "himalayas", label: "Himalayas" },
  { value: "linkedin", label: "LinkedIn" },
  { value: "weworkremotely", label: "WeWorkRemotely" },
  { value: "remoteok", label: "RemoteOK" },
  { value: "remotive", label: "Remotive" },
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
  const [searchParams, setSearchParams] = useSearchParams();
  // Regression finding 34: ref guards against infinite URL ↔ state loops
  const syncingFromUrl = useRef(false);

  // F87: `is_classified` serialises to/from the URL as "true"/"false"/(absent)
  // alongside `role_cluster`. Parse once here and again inside the URL→state
  // sync below so direct links (/jobs?is_classified=false) stay sticky.
  const parseIsClassified = (raw: string | null): boolean | undefined => {
    if (raw === "true") return true;
    if (raw === "false") return false;
    return undefined;
  };

  const [filters, setFilters] = useState<JobFilters>(() => ({
    search: searchParams.get("search") || "",
    status: (searchParams.get("status") || "") as JobFilters["status"],
    platform: searchParams.get("platform") || "",
    geography: searchParams.get("geography") || "",
    role_cluster: searchParams.get("role_cluster") || "",
    is_classified: parseIsClassified(searchParams.get("is_classified")),
    sort_by: searchParams.get("sort_by") || "relevance_score",
    sort_dir: searchParams.get("sort_dir") || "desc",
    page: Number(searchParams.get("page")) || 1,
    page_size: 25,
  }));

  // URL → state: re-sync filters when URL params change externally
  // (e.g. Sidebar navigation between "All Jobs" and "Relevant Jobs")
  useEffect(() => {
    syncingFromUrl.current = true;
    setFilters({
      search: searchParams.get("search") || "",
      status: (searchParams.get("status") || "") as JobFilters["status"],
      platform: searchParams.get("platform") || "",
      geography: searchParams.get("geography") || "",
      role_cluster: searchParams.get("role_cluster") || "",
      is_classified: parseIsClassified(searchParams.get("is_classified")),
      sort_by: searchParams.get("sort_by") || "relevance_score",
      sort_dir: searchParams.get("sort_dir") || "desc",
      page: Number(searchParams.get("page")) || 1,
      page_size: 25,
    });
  }, [searchParams]);

  // State → URL: write filter changes back to the URL so it's shareable.
  // Skip when the change originated from the URL→state sync above.
  useEffect(() => {
    if (syncingFromUrl.current) {
      syncingFromUrl.current = false;
      return;
    }
    const params = new URLSearchParams();
    if (filters.search) params.set("search", filters.search);
    if (filters.status) params.set("status", filters.status);
    if (filters.platform) params.set("platform", filters.platform);
    if (filters.geography) params.set("geography", filters.geography);
    if (filters.role_cluster) params.set("role_cluster", filters.role_cluster);
    // F87: only serialise `is_classified` when the user has explicitly
    // narrowed to it — `undefined` = "both", which is the default and
    // doesn't need to show up in the URL. `true`/`false` round-trip
    // via the `parseIsClassified` helper above.
    if (filters.is_classified === true) params.set("is_classified", "true");
    else if (filters.is_classified === false) params.set("is_classified", "false");
    if (filters.sort_by && filters.sort_by !== "relevance_score") params.set("sort_by", filters.sort_by);
    if (filters.sort_dir && filters.sort_dir !== "desc") params.set("sort_dir", filters.sort_dir);
    if ((filters.page ?? 1) > 1) params.set("page", String(filters.page));
    setSearchParams(params, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters]);

  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  // F69: when true, the bulk action targets *every* row matching the
  // current filter (server-side enumeration), not just the ids in
  // `selectedIds`. The banner below the filter Card flips this on,
  // and any filter change or cancel flips it off. Kept separate from
  // `selectedIds` so the existing per-page select-all path is
  // unchanged when the user hasn't opted into the full-matching mode.
  const [selectAllMatching, setSelectAllMatching] = useState(false);
  // F69: remember the last bulk error so the banner above the action
  // Card can show "Filter matches 8,342 jobs which exceeds the cap of
  // 5000" instead of silently failing. `bulkMutation.error` also
  // carries it, but extracting the .detail payload and clearing on
  // success is clearer as its own state.
  const [bulkErrorMsg, setBulkErrorMsg] = useState<string | null>(null);

  // Regression finding 70: clear checkbox selections when filters change —
  // stale selections from a previous filter-set could silently target
  // jobs the user can no longer see in the table. F87: `is_classified`
  // is also a filter axis (Unclassified dropdown option), so toggling
  // between "classified" and "unclassified" views must likewise reset.
  // F69: `selectAllMatching` is explicitly scoped to the filter set
  // active at click-time, so the same "filters changed" event must
  // cancel it too — otherwise a user could narrow the filter AFTER
  // clicking "Select all N matching" and silently shrink the blast
  // radius (surprising) or broaden it (dangerous).
  useEffect(() => {
    setSelectedIds(new Set());
    setSelectAllMatching(false);
    setBulkErrorMsg(null);
  }, [
    filters.search, filters.status, filters.platform, filters.geography,
    filters.role_cluster, filters.is_classified, filters.sort_by, filters.sort_dir,
  ]);

  // F222: destructure full queries so failures surface via the banner.
  const activeResumeQ = useQuery({
    queryKey: ["active-resume"],
    queryFn: getActiveResume,
  });
  const activeResumeData = activeResumeQ.data;
  const hasActiveResume = !!activeResumeData?.active_resume;

  const jobsQ = useQuery({
    queryKey: ["jobs", filters],
    queryFn: () => getJobs(filters),
  });
  const { data, isLoading } = jobsQ;

  // Regression finding 87: the role-cluster dropdown used to hardcode
  // four options (`relevant` + `infra` + `security` + `qa`). That drifts
  // the moment an admin adds or removes a cluster via `/role-clusters`,
  // and it had no affordance for the ~90% of rows with no cluster.
  // Fetch the live catalog here and build options dynamically: keep
  // the synthetic "relevant" pseudo at the top, then one option per
  // active cluster sorted by the admin-defined `sort_order`, then the
  // new "Unclassified" sentinel that maps to `is_classified=false` on
  // the wire. `gcTime: Infinity` / long `staleTime` because the cluster
  // config is low-churn and refetching on every JobsPage mount would
  // be wasteful; invalidation is manual via the admin RoleClusters UI.
  const roleClustersQ = useQuery({
    queryKey: ["role-clusters"],
    queryFn: getRoleClusters,
    staleTime: 10 * 60 * 1000,
  });
  const activeClusters = (roleClustersQ.data?.items ?? [])
    .filter((c) => c.is_active)
    .sort((a, b) => a.sort_order - b.sort_order);
  // The dropdown carries a single string value. Derive it from the
  // current filters state: `__unclassified__` if `is_classified=false`,
  // otherwise the `role_cluster` string (or empty for "All Roles").
  const roleSelectValue =
    filters.is_classified === false ? UNCLASSIFIED_SENTINEL : (filters.role_cluster || "");

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
      // F69: clear full-matching intent after it fires — otherwise
      // the next bulk click would silently re-target the whole
      // (now-invalidated) filter set, which is a foot-gun. The user
      // re-opts in by clicking "Select all N matching" again.
      setSelectAllMatching(false);
      setBulkErrorMsg(null);
    },
    onError: (err: any) => {
      // F69: surface backend 400s from the filter branch (cap exceeded
      // or zero-match) in the UI instead of silently failing. Fall
      // back to a generic message if the error shape is unexpected.
      const detail =
        err?.body?.detail ||
        err?.detail ||
        err?.message ||
        "Bulk action failed. Please try again.";
      setBulkErrorMsg(typeof detail === "string" ? detail : "Bulk action failed.");
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

  // Regression finding 68: union/subtract visible page ids instead of
  // replacing the entire Set, so cross-page curation is preserved.
  const toggleSelectAll = () => {
    if (!data) return;
    const pageIds = data.items.map((j) => j.id);
    const allVisible = pageIds.every((id) => selectedIds.has(id));
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (allVisible) {
        pageIds.forEach((id) => next.delete(id));
      } else {
        pageIds.forEach((id) => next.add(id));
      }
      return next;
    });
  };

  // F69: translate the current filters state into the BulkFilterCriteria
  // shape the backend expects. Only non-empty fields survive so the
  // generated WHERE chain matches what `GET /jobs` produced for the
  // page the user is looking at. The frontend uses `geography` in its
  // JobFilters state but the backend field is `geography_bucket`, so
  // we rename here. `sort_by` / `sort_dir` / `page` are intentionally
  // left out — they don't affect the matching id set and sending them
  // would just produce audit-log noise.
  const buildFilterCriteria = (): BulkFilterCriteria => {
    const c: BulkFilterCriteria = {};
    if (filters.search && filters.search.trim()) c.search = filters.search.trim();
    if (filters.status) c.status = filters.status;
    if (filters.platform) c.platform = filters.platform;
    if (filters.geography) c.geography_bucket = filters.geography;
    if (filters.role_cluster) c.role_cluster = filters.role_cluster;
    if (filters.is_classified !== undefined) c.is_classified = filters.is_classified;
    return c;
  };

  // Regression finding 71: gate bulk actions behind window.confirm() so a
  // misclick doesn't silently change the status of dozens of jobs.
  // F69: route between id-list and filter branches based on
  // `selectAllMatching`. The confirm prompt includes the real blast
  // radius — "X selected jobs" for the id path, "all N matching" for
  // the filter path — so the user can't mistake one for the other.
  const handleBulkAction = (verb: "accept" | "reject" | "reset") => {
    const status = VERB_TO_STATUS[verb];
    const verbLabel = verb === "accept" ? "Accept" : verb === "reject" ? "Reject" : "Reset";
    const total = data?.total ?? 0;

    if (selectAllMatching) {
      // Filter branch — target everything matching the current filter.
      // Confirm message calls out the total so the user sees the actual
      // row count they're about to mutate. Backend caps at 5000; if the
      // filter exceeds that, the mutation rejects with a 400 surfaced
      // via `bulkErrorMsg` (no need to pre-check — single round trip).
      if (!window.confirm(
        `${verbLabel} all ${total.toLocaleString()} jobs matching the current filter? This cannot be undone.`
      )) return;
      setBulkErrorMsg(null);
      bulkMutation.mutate({
        filter: buildFilterCriteria(),
        action: status,
      });
      return;
    }

    // Legacy id-list branch — unchanged semantics, correct status value.
    const count = selectedIds.size;
    if (count === 0) return;
    if (!window.confirm(
      `${verbLabel} ${count} selected job${count !== 1 ? "s" : ""}? This cannot be undone.`
    )) return;
    setBulkErrorMsg(null);
    bulkMutation.mutate({
      job_ids: Array.from(selectedIds),
      action: status,
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
            {filters.is_classified === false
              ? "Unclassified Jobs"
              : filters.role_cluster === "relevant"
                ? "Relevant Jobs"
                : filters.role_cluster
                  ? `${(activeClusters.find((c) => c.name === filters.role_cluster)?.display_name) || (filters.role_cluster.charAt(0).toUpperCase() + filters.role_cluster.slice(1))} Jobs`
                  : "All Jobs"}
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            {filters.is_classified === false
              ? (data ? `${formatCount(data.total)} jobs without a role cluster` : "Loading jobs...")
              : filters.role_cluster === "relevant"
                ? "Cloud, DevOps, SRE, Compliance & Security positions"
                : data ? `${formatCount(data.total)} jobs found` : "Loading jobs..."}
            {data && filters.role_cluster === "relevant" ? ` · ${formatCount(data.total)} jobs found` : ""}
          </p>
        </div>
      </div>

      {/* F222: surfaces /jobs failures with a Retry button. */}
      <BackendErrorBanner queries={[jobsQ, activeResumeQ]} />

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
          {/* F87: role-cluster dropdown is now driven by the admin
              config (`/role-clusters`) with the synthetic "Relevant"
              pseudo at the top and a new "Unclassified" option that
              translates to `is_classified=false` on the wire. */}
          <select
            className="select w-auto"
            value={roleSelectValue}
            onChange={(e) => {
              const v = e.target.value;
              if (v === UNCLASSIFIED_SENTINEL) {
                // Unclassified: clear role_cluster, switch is_classified=false.
                setFilters((prev) => ({
                  ...prev,
                  role_cluster: "",
                  is_classified: false,
                  page: 1,
                }));
              } else {
                // Any cluster name (including "" for All and "relevant"
                // for the pseudo): clear is_classified, set role_cluster.
                setFilters((prev) => ({
                  ...prev,
                  role_cluster: v,
                  is_classified: undefined,
                  page: 1,
                }));
              }
            }}
          >
            <option value="">All Roles</option>
            <option value="relevant">Relevant (configured clusters)</option>
            {activeClusters.map((c) => (
              <option key={c.id} value={c.name}>
                {c.display_name || c.name}
              </option>
            ))}
            <option value={UNCLASSIFIED_SENTINEL}>Unclassified</option>
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
          {(filters.search || filters.status || filters.platform || filters.geography || filters.role_cluster || filters.is_classified !== undefined) && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() =>
                // F87: also reset `is_classified` so Clear truly clears
                // every filter axis (the Unclassified view used to
                // survive a Clear and silently narrow the result set).
                setFilters({
                  search: "",
                  status: "",
                  platform: "",
                  geography: "",
                  role_cluster: "",
                  is_classified: undefined,
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

      {/* F69: "Select all N matching" banner. Appears only when the
          user has checked every row on the current page AND there are
          rows beyond this page (i.e. `total > data.items.length`).
          Clicking the action flips `selectAllMatching` to true so the
          next bulk click POSTs the filter payload instead of the id
          list. We deliberately don't show the banner when the user
          has partially selected — that signals deliberate curation,
          and the banner would nudge them away from it. Hidden once
          already in filter-mode (we show the filter-mode badge
          inside the action Card below instead). */}
      {data &&
        data.items.length > 0 &&
        selectedIds.size > 0 &&
        data.items.every((j) => selectedIds.has(j.id)) &&
        data.total > data.items.length &&
        !selectAllMatching && (
          <Card padding="sm">
            <div className="flex items-center justify-between gap-4">
              <span className="text-sm text-gray-700">
                All <strong>{data.items.length}</strong> jobs on this page are selected.
              </span>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setSelectAllMatching(true)}
              >
                Select all {data.total.toLocaleString()} jobs matching the filter
              </Button>
            </div>
          </Card>
        )}

      {(selectedIds.size > 0 || selectAllMatching) && (
        <Card padding="sm">
          <div className="flex flex-wrap items-center gap-4">
            <div className="flex items-center gap-2">
              <CheckSquare className="h-4 w-4 text-primary-600" />
              <span className="text-sm font-medium text-gray-700">
                {selectAllMatching
                  ? `All ${(data?.total ?? 0).toLocaleString()} jobs matching the filter selected`
                  : `${selectedIds.size} selected`}
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
                onClick={() => {
                  setSelectedIds(new Set());
                  setSelectAllMatching(false);
                  setBulkErrorMsg(null);
                }}
              >
                Cancel
              </Button>
            </div>
            {/* F69: surface the backend 400 message inline. The most
                likely case is "Filter matches X jobs which exceeds the
                bulk cap of 5000. Narrow the filter before retrying." —
                pre-fix that message was swallowed and the user saw
                only a dead spinner. */}
            {bulkErrorMsg && (
              <div className="w-full rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                {bulkErrorMsg}
              </div>
            )}
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
                    {/* F71: header checkbox was DOM-unlabeled — screen
                        readers announced it as "checkbox, not checked"
                        with zero context. Row checkboxes below get
                        per-row labels so AT can navigate the table. */}
                    <input
                      type="checkbox"
                      checked={
                        data.items.length > 0 &&
                        data.items.every((j) => selectedIds.has(j.id))
                      }
                      onChange={toggleSelectAll}
                      aria-label="Select all visible jobs"
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
                      {/* F71: per-row `aria-label` gives AT users the
                          job context when the Tab lands on a checkbox,
                          so bulk-select isn't a game of blind guesses.
                          `id="job-select-<id>"` + `name="job_ids"` lets
                          native form-enumerating AT treat them as a
                          set (optional; mostly belt-and-suspenders). */}
                      <input
                        id={`job-select-${job.id}`}
                        name="job_ids"
                        type="checkbox"
                        checked={selectedIds.has(job.id)}
                        onChange={() => toggleSelect(job.id)}
                        onClick={(e) => e.stopPropagation()}
                        aria-label={`Select ${job.title}${job.company_name ? ` at ${job.company_name}` : ""}`}
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
