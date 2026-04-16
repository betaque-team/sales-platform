import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useMutation } from "@tanstack/react-query";
import {
  Activity,
  Database,
  HardDrive,
  Clock,
  AlertTriangle,
  CheckCircle2,
  BarChart3,
  Layers,
  Globe,
  Shield,
  Server,
  Briefcase,
  RefreshCw,
  Play,
  Loader2,
  Zap,
} from "lucide-react";
import { Card } from "@/components/Card";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { VmHealthPanel } from "@/components/VmHealthPanel";
import { QueryBoundary } from "@/components/QueryBoundary";
import {
  getSystemHealth,
  getVmHealth,
  triggerFullScan,
  triggerPlatformScanByName,
  triggerDiscoveryScan,
  getScanTaskStatus,
} from "@/lib/api";

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`;
}

function formatUptime(seconds: number): string {
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  if (days > 0) return `${days}d ${hours}h ${mins}m`;
  if (hours > 0) return `${hours}h ${mins}m`;
  return `${mins}m`;
}

function StatBox({
  label,
  value,
  icon: Icon,
  color = "text-gray-600",
  bgColor = "bg-gray-100",
}: {
  label: string;
  value: string | number;
  icon: React.ElementType;
  color?: string;
  bgColor?: string;
}) {
  return (
    <div className="flex items-center gap-3 rounded-lg border border-gray-100 bg-white p-4">
      <div className={`flex h-10 w-10 items-center justify-center rounded-lg ${bgColor}`}>
        <Icon className={`h-5 w-5 ${color}`} />
      </div>
      <div>
        <p className="text-xs text-gray-500">{label}</p>
        <p className="text-lg font-bold text-gray-900">{value}</p>
      </div>
    </div>
  );
}

function BreakdownTable({
  title,
  data,
  total,
  // Regression finding 87(c): optional href builder lets callers make
  // each row navigable (e.g. the role-cluster breakdown → /jobs with
  // the corresponding filter pre-applied). Returning null/undefined
  // for a key renders the row as plain text like before — so only the
  // cluster breakdown opts in to clickability.
  rowHref,
}: {
  title: string;
  data: Record<string, number>;
  total: number;
  rowHref?: (key: string) => string | null | undefined;
}) {
  const sorted = Object.entries(data).sort((a, b) => b[1] - a[1]);
  return (
    <div>
      <h4 className="mb-2 text-sm font-semibold text-gray-700">{title}</h4>
      <div className="space-y-1.5">
        {sorted.map(([key, count]) => {
          const pct = total > 0 ? ((count / total) * 100).toFixed(1) : "0";
          const href = rowHref?.(key);
          const rowInner = (
            <>
              <div className="w-32 truncate text-xs text-gray-600">{key}</div>
              <div className="flex-1">
                <div className="h-2 rounded-full bg-gray-100">
                  <div
                    className="h-2 rounded-full bg-primary-500"
                    style={{ width: `${Math.min(parseFloat(pct), 100)}%` }}
                  />
                </div>
              </div>
              <div className="w-20 text-right text-xs text-gray-500">
                {count.toLocaleString()} ({pct}%)
              </div>
            </>
          );
          return href ? (
            <Link
              key={key}
              to={href}
              className="flex items-center gap-2 rounded -mx-1 px-1 py-0.5 hover:bg-primary-50 transition-colors"
              title={`View ${key} jobs`}
            >
              {rowInner}
            </Link>
          ) : (
            <div key={key} className="flex items-center gap-2">
              {rowInner}
            </div>
          );
        })}
      </div>
    </div>
  );
}

const SCAN_PLATFORMS = ["greenhouse", "lever", "ashby", "workable", "bamboohr", "himalayas", "wellfound", "jobvite", "smartrecruiters", "recruitee", "weworkremotely", "remoteok", "remotive"];

export function MonitoringPage() {
  // F222: MonitoringPage is the ADMIN HEALTH page. If the backend itself
  // is unhealthy the previous "if (!data) return Failed to load monitoring
  // data" branch gave zero signal about WHY (auth, 500, network) and had
  // no retry. `<QueryBoundary>` at render time replaces it with an alert
  // card that shows the actual error + a Try-again button. The VM panel
  // stays on `retry: false` so it can gracefully degrade to "unavailable"
  // without blocking the whole page.
  const systemHealthQ = useQuery({
    queryKey: ["monitoring"],
    queryFn: getSystemHealth,
    refetchInterval: 30000,
  });
  const { data, refetch, dataUpdatedAt } = systemHealthQ;

  // VM host-metrics (live, polls every 30s). If the backend can't read the
  // host snapshot (dev/CI), the panel renders a graceful "unavailable" card.
  const { data: vmData } = useQuery({
    queryKey: ["monitoring-vm"],
    queryFn: getVmHealth,
    refetchInterval: 30000,
    retry: false,
  });

  const [activeScan, setActiveScan] = useState<{
    taskId: string;
    label: string;
    status: string;
    result?: any;
  } | null>(null);

  const fullScanMutation = useMutation({
    mutationFn: triggerFullScan,
    onSuccess: (data) => {
      setActiveScan({ taskId: data.task_id, label: "Full Scan (All Platforms)", status: "PENDING" });
      pollScanStatus(data.task_id, "Full Scan (All Platforms)");
    },
  });

  const platformScanMutation = useMutation({
    mutationFn: (platform: string) => triggerPlatformScanByName(platform),
    onSuccess: (data) => {
      const label = `${data.platform} (${data.boards} boards)`;
      setActiveScan({ taskId: data.task_id, label, status: "PENDING" });
      pollScanStatus(data.task_id, label);
    },
  });

  const discoveryScanMutation = useMutation({
    mutationFn: triggerDiscoveryScan,
    onSuccess: (data) => {
      setActiveScan({ taskId: data.task_id, label: "Platform Discovery (Find New Boards)", status: "PENDING" });
      pollScanStatus(data.task_id, "Platform Discovery");
    },
  });

  const pollScanStatus = async (taskId: string, _label: string) => {
    const poll = async () => {
      try {
        const status = await getScanTaskStatus(taskId);
        setActiveScan((prev) =>
          prev?.taskId === taskId
            ? { ...prev, status: status.status, result: status.result }
            : prev
        );
        if (status.status !== "SUCCESS" && status.status !== "FAILURE") {
          setTimeout(poll, 3000);
        } else {
          refetch();
        }
      } catch {
        // Silently ignore polling errors
      }
    };
    setTimeout(poll, 2000);
  };

  // F222: single boundary covers loading AND error. Admin-access-required
  // 403 flows through here as a clear error message instead of a silent
  // blank. The old `if (!data)` catchall assumed the ONLY reason `data`
  // could be undefined was auth — in practice a 500 or network timeout
  // would hit the same branch and give the same misleading message.
  if (systemHealthQ.isLoading || systemHealthQ.isError) {
    return (
      <div className="mx-auto max-w-2xl pt-10">
        <QueryBoundary query={systemHealthQ}>
          <></>
        </QueryBoundary>
      </div>
    );
  }

  if (!data) {
    // Shouldn't happen now (isLoading/isError covered above) but keep a
    // harmless fallback so TS narrows correctly below.
    return null;
  }

  const d = data;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">System Monitor</h1>
          <p className="mt-1 text-sm text-gray-500">
            Platform health, storage, and resource overview
          </p>
        </div>
        <button
          onClick={() => refetch()}
          className="flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-600 hover:bg-gray-50"
        >
          <RefreshCw className="h-4 w-4" />
          Refresh
        </button>
      </div>

      {/* Health status bar */}
      <div className="flex items-center gap-3 rounded-lg border border-green-200 bg-green-50 px-4 py-3">
        {d.database.healthy ? (
          <>
            <CheckCircle2 className="h-5 w-5 text-green-600" />
            <span className="text-sm font-medium text-green-800">All systems operational</span>
          </>
        ) : (
          <>
            <AlertTriangle className="h-5 w-5 text-red-600" />
            <span className="text-sm font-medium text-red-800">Database connection issue detected</span>
          </>
        )}
        <span className="ml-auto text-xs text-green-600">
          Uptime: {formatUptime(d.uptime_seconds)}
        </span>
      </div>

      {/* VM host monitoring + Oracle Always-Free guardrails (top of page so the
          banner is the first thing seen when something drifts toward billing) */}
      <VmHealthPanel data={vmData} />

      {/* Scan Controls */}
      <Card>
        <div className="mb-4 flex items-center gap-2">
          <Zap className="h-5 w-5 text-amber-500" />
          <h3 className="text-base font-semibold text-gray-900">Scan Controls</h3>
        </div>

        {/* Active scan status */}
        {activeScan && (
          <div className={`mb-4 flex items-center gap-3 rounded-lg border px-4 py-3 ${
            activeScan.status === "SUCCESS"
              ? "border-green-200 bg-green-50"
              : activeScan.status === "FAILURE"
              ? "border-red-200 bg-red-50"
              : "border-blue-200 bg-blue-50"
          }`}>
            {activeScan.status === "SUCCESS" ? (
              <CheckCircle2 className="h-5 w-5 text-green-600" />
            ) : activeScan.status === "FAILURE" ? (
              <AlertTriangle className="h-5 w-5 text-red-600" />
            ) : (
              <Loader2 className="h-5 w-5 animate-spin text-blue-600" />
            )}
            <div className="flex-1">
              <p className={`text-sm font-medium ${
                activeScan.status === "SUCCESS"
                  ? "text-green-800"
                  : activeScan.status === "FAILURE"
                  ? "text-red-800"
                  : "text-blue-800"
              }`}>
                {activeScan.label}
              </p>
              <p className="text-xs text-gray-500">
                Status: {activeScan.status}
                {activeScan.result && activeScan.status === "SUCCESS" && (
                  <span className="ml-2">
                    Found: {activeScan.result.jobs_found || 0} | New: {activeScan.result.new_jobs || 0} | Errors: {activeScan.result.errors || 0}
                  </span>
                )}
              </p>
            </div>
            {(activeScan.status === "SUCCESS" || activeScan.status === "FAILURE") && (
              <button
                onClick={() => setActiveScan(null)}
                className="text-xs text-gray-500 hover:text-gray-700"
              >
                Dismiss
              </button>
            )}
          </div>
        )}

        <div className="space-y-3">
          {/* Full scan */}
          <div className="flex items-center justify-between rounded-lg bg-gray-50 px-4 py-3">
            <div>
              <p className="text-sm font-medium text-gray-900">Full Platform Scan</p>
              <p className="text-xs text-gray-500">Scan all active boards across all platforms</p>
            </div>
            <Button
              variant="primary"
              size="sm"
              onClick={() => {
                if (window.confirm("Run a full scan across all active boards? This triggers hundreds of outbound ATS API calls and may take several minutes.")) {
                  fullScanMutation.mutate();
                }
              }}
              loading={fullScanMutation.isPending}
              disabled={!!activeScan && activeScan.status !== "SUCCESS" && activeScan.status !== "FAILURE"}
            >
              <Play className="mr-1.5 h-3 w-3" />
              Run Full Scan
            </Button>
          </div>

          {/* Discovery scan */}
          <div className="flex items-center justify-between rounded-lg bg-amber-50 border border-amber-100 px-4 py-3">
            <div>
              <p className="text-sm font-medium text-gray-900">Discover New Platforms</p>
              <p className="text-xs text-gray-500">Probe ATS sitemaps and known slugs to find new company boards</p>
            </div>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => {
                if (window.confirm("Run platform discovery? This probes ATS sitemaps and known slugs — may take several minutes and queue follow-up scans.")) {
                  discoveryScanMutation.mutate();
                }
              }}
              loading={discoveryScanMutation.isPending}
              disabled={!!activeScan && activeScan.status !== "SUCCESS" && activeScan.status !== "FAILURE"}
            >
              <Play className="mr-1.5 h-3 w-3" />
              Run Discovery
            </Button>
          </div>

          {/* Per-platform scans */}
          <div className="rounded-lg border border-gray-100 p-4">
            <p className="text-xs font-semibold text-gray-500 uppercase mb-3">Scan by Platform</p>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
              {SCAN_PLATFORMS.map((platform) => {
                const platformData = d.jobs_breakdown?.by_platform?.[platform];
                return (
                  <button
                    key={platform}
                    onClick={() => platformScanMutation.mutate(platform)}
                    disabled={
                      platformScanMutation.isPending ||
                      (!!activeScan && activeScan.status !== "SUCCESS" && activeScan.status !== "FAILURE")
                    }
                    className="flex flex-col items-center gap-1 rounded-lg border border-gray-200 bg-white px-3 py-3 text-center hover:border-primary-300 hover:bg-primary-50 transition-colors disabled:opacity-50"
                  >
                    <Server className="h-4 w-4 text-gray-400" />
                    <span className="text-xs font-medium text-gray-900 capitalize">{platform}</span>
                    {platformData !== undefined && (
                      <span className="text-xs text-gray-400">{platformData} jobs</span>
                    )}
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      </Card>

      {/* Key metrics */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <StatBox label="Total Jobs" value={d.data_counts.jobs.toLocaleString()} icon={Briefcase} color="text-primary-600" bgColor="bg-primary-50" />
        <StatBox label="Companies" value={d.data_counts.companies.toLocaleString()} icon={Layers} color="text-blue-600" bgColor="bg-blue-50" />
        <StatBox label="Active Boards" value={d.data_counts.boards_active} icon={Server} color="text-purple-600" bgColor="bg-purple-50" />
        <StatBox label="Reviews" value={d.data_counts.reviews} icon={CheckCircle2} color="text-green-600" bgColor="bg-green-50" />
        <StatBox label="Scored Jobs" value={d.scoring.scored_count.toLocaleString()} icon={BarChart3} color="text-amber-600" bgColor="bg-amber-50" />
        <StatBox label="Avg Score" value={d.scoring.avg_score} icon={Activity} color="text-indigo-600" bgColor="bg-indigo-50" />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Database & Storage */}
        <Card>
          <div className="mb-4 flex items-center gap-2">
            <Database className="h-5 w-5 text-blue-500" />
            <h3 className="text-base font-semibold text-gray-900">Database & Storage</h3>
          </div>
          <div className="space-y-3">
            <div className="flex items-center justify-between rounded-lg bg-gray-50 px-4 py-3">
              <span className="text-sm text-gray-600">Database Size</span>
              <span className="text-sm font-bold text-gray-900">{d.database.size_mb} MB</span>
            </div>
            <div className="flex items-center justify-between rounded-lg bg-gray-50 px-4 py-3">
              <span className="text-sm text-gray-600">Total Boards</span>
              <span className="text-sm font-semibold text-gray-900">
                {d.data_counts.boards_active} active / {d.data_counts.boards_total} total
              </span>
            </div>
            <div className="flex items-center justify-between rounded-lg bg-gray-50 px-4 py-3">
              <span className="text-sm text-gray-600">Scan Logs</span>
              <span className="text-sm font-semibold text-gray-900">{d.data_counts.scan_logs}</span>
            </div>

            {d.database.table_sizes.length > 0 && (
              <div className="mt-3">
                <h4 className="mb-2 text-xs font-semibold text-gray-500 uppercase">Table Sizes</h4>
                <div className="space-y-1">
                  {d.database.table_sizes.map((t: any) => (
                    <div key={t.table} className="flex items-center justify-between text-xs">
                      <span className="text-gray-600 font-mono">{t.table}</span>
                      <span className="text-gray-900 font-semibold">{formatBytes(t.size_bytes)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </Card>

        {/* Activity (24h) */}
        <Card>
          <div className="mb-4 flex items-center gap-2">
            <Clock className="h-5 w-5 text-green-500" />
            <h3 className="text-base font-semibold text-gray-900">Activity (Last 24h)</h3>
          </div>
          <div className="space-y-3">
            <div className="flex items-center justify-between rounded-lg bg-gray-50 px-4 py-3">
              <span className="text-sm text-gray-600">Scans Run</span>
              <span className="text-sm font-bold text-gray-900">{d.activity_24h.scans_run}</span>
            </div>
            <div className="flex items-center justify-between rounded-lg bg-gray-50 px-4 py-3">
              <span className="text-sm text-gray-600">New Jobs Added</span>
              <Badge variant="success">{d.activity_24h.new_jobs_added}</Badge>
            </div>
            <div className="flex items-center justify-between rounded-lg bg-gray-50 px-4 py-3">
              <span className="text-sm text-gray-600">Errors</span>
              <Badge variant={d.activity_24h.errors > 0 ? "danger" : "default"}>
                {d.activity_24h.errors}
              </Badge>
            </div>
            <div className="flex items-center justify-between rounded-lg bg-gray-50 px-4 py-3">
              <span className="text-sm text-gray-600">Last Scan</span>
              <div className="text-right">
                <p className="text-xs font-semibold text-gray-900">
                  {d.activity_24h.last_scan_at
                    ? new Date(d.activity_24h.last_scan_at).toLocaleString()
                    : "Never"}
                </p>
                {d.activity_24h.last_scan_source && (
                  <p className="text-xs text-gray-500">{d.activity_24h.last_scan_source}</p>
                )}
              </div>
            </div>

            {/* Uptime */}
            <div className="mt-4 rounded-lg border border-blue-100 bg-blue-50 px-4 py-3">
              <div className="flex items-center gap-2">
                <HardDrive className="h-4 w-4 text-blue-600" />
                <span className="text-sm font-medium text-blue-800">
                  Backend Uptime: {formatUptime(d.uptime_seconds)}
                </span>
              </div>
            </div>
          </div>
        </Card>
      </div>

      {/* Data Breakdowns */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card>
          <div className="mb-4 flex items-center gap-2">
            <Shield className="h-5 w-5 text-red-500" />
            <h3 className="text-base font-semibold text-gray-900">Jobs by Role Cluster</h3>
          </div>
          {/* F87(c): make each cluster row a link to the matching
              /jobs filter. The backend labels empty/null clusters as
              "unclassified" in this map, so that key maps to the new
              `is_classified=false` filter; every other key maps to a
              normal `role_cluster=<name>` URL so the admin can click
              through to the underlying jobs in a single tap. */}
          <BreakdownTable
            title=""
            data={d.jobs_breakdown.by_role_cluster}
            total={d.data_counts.jobs}
            rowHref={(key) =>
              key === "unclassified"
                ? "/jobs?is_classified=false"
                : `/jobs?role_cluster=${encodeURIComponent(key)}`
            }
          />
        </Card>

        <Card>
          <div className="mb-4 flex items-center gap-2">
            <Globe className="h-5 w-5 text-green-500" />
            <h3 className="text-base font-semibold text-gray-900">Jobs by Geography</h3>
          </div>
          <BreakdownTable
            title=""
            data={d.jobs_breakdown.by_geography}
            total={d.data_counts.jobs}
          />
        </Card>

        <Card>
          <div className="mb-4 flex items-center gap-2">
            <Server className="h-5 w-5 text-purple-500" />
            <h3 className="text-base font-semibold text-gray-900">Jobs by Platform</h3>
          </div>
          <BreakdownTable
            title=""
            data={d.jobs_breakdown.by_platform}
            total={d.data_counts.jobs}
          />
        </Card>

        <Card>
          <div className="mb-4 flex items-center gap-2">
            <Briefcase className="h-5 w-5 text-blue-500" />
            <h3 className="text-base font-semibold text-gray-900">Jobs by Status</h3>
          </div>
          <BreakdownTable
            title=""
            data={d.jobs_breakdown.by_status}
            total={d.data_counts.jobs}
          />
        </Card>
      </div>

      <div className="text-center text-xs text-gray-400">
        Last updated: {new Date(dataUpdatedAt).toLocaleString()} · Auto-refreshes every 30s
      </div>
    </div>
  );
}
