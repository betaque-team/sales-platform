import {
  AlertTriangle,
  CheckCircle2,
  Cpu,
  HardDrive,
  Network,
  Server,
  Shield,
  Clock,
  Zap,
  Box,
  GitCommit,
  Info,
} from "lucide-react";
import { Card } from "@/components/Card";
import { Badge } from "@/components/Badge";
import type { VmMetrics, VmMetricsAvailable, VmGuardrail } from "@/lib/types";

// ─── Helpers ─────────────────────────────────────────────────────────────────

function formatBytes(bytes: number, decimals = 1): string {
  if (!bytes || bytes < 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(k)), sizes.length - 1);
  return `${(bytes / Math.pow(k, i)).toFixed(decimals)} ${sizes[i]}`;
}

function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || seconds < 0) return "—";
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${seconds % 60}s`;
  return `${seconds}s`;
}

function formatAge(seconds: number | null | undefined): string {
  if (seconds == null) return "never";
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

function bytesToGB(bytes: number): number {
  return bytes / (1024 ** 3);
}

// ─── Sub-components ──────────────────────────────────────────────────────────

function GuardrailBanner({ guardrails, overallStatus }: {
  guardrails: VmGuardrail[];
  overallStatus: "ok" | "warn" | "critical";
}) {
  if (overallStatus === "ok") {
    return (
      <div className="flex items-center gap-3 rounded-lg border border-green-200 bg-green-50 px-4 py-3">
        <CheckCircle2 className="h-5 w-5 text-green-600" />
        <div className="flex-1">
          <p className="text-sm font-medium text-green-800">Free-tier guardrails — all green</p>
          <p className="text-xs text-green-700">No CPU reclaim risk, no billing risk, no container issues.</p>
        </div>
      </div>
    );
  }
  const borderColor = overallStatus === "critical" ? "border-red-200" : "border-amber-200";
  const bgColor = overallStatus === "critical" ? "bg-red-50" : "bg-amber-50";
  const iconColor = overallStatus === "critical" ? "text-red-600" : "text-amber-600";
  const titleColor = overallStatus === "critical" ? "text-red-900" : "text-amber-900";
  return (
    <div className={`rounded-lg border ${borderColor} ${bgColor} px-4 py-3`}>
      <div className="mb-2 flex items-center gap-3">
        <AlertTriangle className={`h-5 w-5 ${iconColor}`} />
        <p className={`text-sm font-semibold ${titleColor}`}>
          Free-tier guardrails — {overallStatus === "critical" ? "action required" : "warnings"}
        </p>
      </div>
      <ul className="ml-8 list-disc space-y-1 text-sm">
        {guardrails.map((g) => (
          <li
            key={g.name}
            className={g.severity === "critical" ? "text-red-800" : "text-amber-800"}
          >
            <span className="font-mono text-xs font-semibold">[{g.severity}]</span>{" "}
            {g.message}
          </li>
        ))}
      </ul>
    </div>
  );
}

function UsageBar({
  label,
  used,
  total,
  formatValue,
  severity,
}: {
  label: string;
  used: number;
  total: number;
  formatValue: (v: number) => string;
  severity?: "ok" | "warn" | "critical";
}) {
  const pct = total > 0 ? Math.min((used / total) * 100, 100) : 0;
  const barColor =
    severity === "critical" ? "bg-red-500"
    : severity === "warn" ? "bg-amber-500"
    : pct > 95 ? "bg-red-500"
    : pct > 80 ? "bg-amber-500"
    : "bg-emerald-500";
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between text-xs">
        <span className="font-medium text-gray-700">{label}</span>
        <span className="text-gray-500">
          {formatValue(used)} / {formatValue(total)}
          <span className="ml-1.5 font-semibold text-gray-700">{pct.toFixed(1)}%</span>
        </span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-gray-100">
        <div
          className={`h-full rounded-full transition-all ${barColor}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function StatTile({
  label,
  primary,
  secondary,
  icon: Icon,
  tone = "slate",
}: {
  label: string;
  primary: string;
  secondary?: string;
  icon: React.ElementType;
  tone?: "slate" | "emerald" | "amber" | "red" | "blue" | "indigo";
}) {
  const toneBg: Record<string, string> = {
    slate: "bg-slate-50 text-slate-700 border-slate-100",
    emerald: "bg-emerald-50 text-emerald-700 border-emerald-100",
    amber: "bg-amber-50 text-amber-700 border-amber-100",
    red: "bg-red-50 text-red-700 border-red-100",
    blue: "bg-blue-50 text-blue-700 border-blue-100",
    indigo: "bg-indigo-50 text-indigo-700 border-indigo-100",
  };
  return (
    <div className={`rounded-lg border p-3 ${toneBg[tone]}`}>
      <div className="mb-1 flex items-center gap-2">
        <Icon className="h-4 w-4" />
        <span className="text-xs font-medium opacity-80">{label}</span>
      </div>
      <p className="text-xl font-bold">{primary}</p>
      {secondary && <p className="text-xs opacity-70">{secondary}</p>}
    </div>
  );
}

function ContainerList({ containers }: { containers: VmMetricsAvailable["containers"] }) {
  if (containers.length === 0) {
    return <p className="text-xs text-gray-500">No containers reported.</p>;
  }
  const total = containers.length;
  const running = containers.filter((c) => c.state === "running").length;
  const allHealthy = running === total;
  return (
    <div>
      <div className="mb-2 flex items-center gap-2">
        <Box className="h-4 w-4 text-gray-400" />
        <span className="text-xs font-semibold text-gray-500">
          Containers:
        </span>
        <Badge variant={allHealthy ? "success" : "danger"}>
          {running}/{total} running
        </Badge>
      </div>
      <div className="space-y-1">
        {containers.map((c) => {
          const healthy = c.state === "running" && c.status.toLowerCase().includes("healthy");
          const up = c.state === "running";
          const variant: "success" | "warning" | "danger" = healthy ? "success" : up ? "warning" : "danger";
          return (
            <div
              key={c.name}
              className="flex items-center justify-between rounded border border-gray-100 bg-gray-50 px-3 py-1.5 text-xs"
            >
              <span className="truncate font-mono text-gray-700">{c.name}</span>
              <Badge variant={variant}>{c.status}</Badge>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Main component ──────────────────────────────────────────────────────────

export function VmHealthPanel({ data }: { data: VmMetrics | undefined }) {
  if (!data) {
    return (
      <Card>
        <div className="flex items-center gap-2 py-4">
          <Info className="h-5 w-5 text-gray-400" />
          <p className="text-sm text-gray-500">Loading VM metrics…</p>
        </div>
      </Card>
    );
  }

  if (!data.available) {
    return (
      <Card>
        <div className="flex items-start gap-3">
          <Info className="mt-0.5 h-5 w-5 shrink-0 text-gray-400" />
          <div>
            <p className="text-sm font-medium text-gray-700">VM metrics unavailable</p>
            <p className="mt-1 text-xs text-gray-500">{data.reason}</p>
          </div>
        </div>
      </Card>
    );
  }

  const d = data;

  // Used CPU ≈ cores × (utilization_percent / 100) is misleading — just show CPU count
  // vs. free-tier cap. For CPU "usage", the meaningful number is the load avg vs. cores.

  const cpuCoresUsed = d.cpu.cores;
  const memGBUsed = bytesToGB(d.memory.total_bytes); // VM shape has this much RAM allocated
  const diskGBUsed = bytesToGB(d.disk.used_bytes);
  const egressTB = d.network.projected_monthly_egress_tb ?? 0;

  return (
    <div className="space-y-4">
      <GuardrailBanner guardrails={d.guardrails} overallStatus={d.overall_status} />

      <Card>
        <div className="mb-4 flex items-center gap-2">
          <Server className="h-5 w-5 text-indigo-500" />
          <h3 className="text-base font-semibold text-gray-900">
            VM Health · Oracle Always Free
          </h3>
          <Badge variant="info" className="ml-2">
            $0/mo · {d.cpu.cores} OCPU · {formatBytes(d.memory.total_bytes, 0)}
          </Badge>
          <span className="ml-auto text-xs text-gray-400">
            snapshot {formatAge(d.snapshot_age_seconds)}
          </span>
        </div>

        {/* ── Free-tier usage bars (the $0 guardrails) ── */}
        <div className="mb-5 rounded-lg border border-gray-100 bg-gray-50 p-4">
          <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-gray-500">
            Free-tier usage (exceed these → Oracle starts charging)
          </p>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <UsageBar
              label="OCPUs (ARM A1)"
              used={cpuCoresUsed}
              total={d.free_tier.max_ocpus}
              formatValue={(v) => v.toString()}
            />
            <UsageBar
              label="RAM"
              used={memGBUsed}
              total={d.free_tier.max_memory_gb}
              formatValue={(v) => `${v.toFixed(1)} GB`}
            />
            <UsageBar
              label="Block storage"
              used={diskGBUsed}
              total={d.free_tier.max_disk_gb}
              formatValue={(v) => `${v.toFixed(1)} GB`}
              severity={d.disk.free_tier_used_percent > 95 ? "critical" : d.disk.free_tier_used_percent > 80 ? "warn" : "ok"}
            />
            <UsageBar
              label="Egress (projected this month)"
              used={egressTB}
              total={d.free_tier.max_egress_tb_month}
              formatValue={(v) => `${v.toFixed(2)} TB`}
              severity={
                (d.network.projected_egress_pct_of_free_tier ?? 0) > 95 ? "critical"
                : (d.network.projected_egress_pct_of_free_tier ?? 0) > 80 ? "warn"
                : "ok"
              }
            />
          </div>
        </div>

        {/* ── Live stats ── */}
        <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatTile
            label="CPU util"
            primary={`${d.cpu.utilization_percent.toFixed(1)}%`}
            secondary={`load ${d.cpu.load_1m.toFixed(2)} / ${d.cpu.load_5m.toFixed(2)} / ${d.cpu.load_15m.toFixed(2)}`}
            icon={Cpu}
            tone="indigo"
          />
          <StatTile
            label="Memory"
            primary={`${d.memory.used_percent.toFixed(1)}%`}
            secondary={`${formatBytes(d.memory.used_bytes)} / ${formatBytes(d.memory.total_bytes)}`}
            icon={HardDrive}
            tone="blue"
          />
          <StatTile
            label="Disk (root)"
            primary={`${d.disk.used_percent.toFixed(1)}%`}
            secondary={`${formatBytes(d.disk.used_bytes)} / ${formatBytes(d.disk.total_bytes)}`}
            icon={HardDrive}
            tone={d.disk.used_percent > 90 ? "red" : d.disk.used_percent > 75 ? "amber" : "slate"}
          />
          <StatTile
            label="Host uptime"
            primary={formatDuration(d.host_uptime_seconds)}
            secondary={`swap ${formatBytes(d.memory.swap_used_bytes)} / ${formatBytes(d.memory.swap_total_bytes)}`}
            icon={Clock}
            tone="slate"
          />
        </div>

        {/* ── Tunnel + keepalive + last deploy ── */}
        <div className="mb-5 grid grid-cols-1 gap-3 md:grid-cols-3">
          <div className="rounded-lg border border-gray-100 p-3">
            <div className="mb-1 flex items-center gap-2">
              <Shield className="h-4 w-4 text-gray-400" />
              <span className="text-xs font-semibold text-gray-500">Cloudflare tunnel</span>
            </div>
            {d.cloudflared.running ? (
              <div>
                <div className="flex items-center gap-2">
                  <Badge variant="success">Up</Badge>
                  <span className="text-xs text-gray-600">
                    {d.cloudflared.connections ?? "?"} conn · {formatDuration(d.cloudflared.uptime_seconds)}
                  </span>
                </div>
              </div>
            ) : (
              <Badge variant="danger">Down — site unreachable</Badge>
            )}
          </div>

          <div className="rounded-lg border border-gray-100 p-3">
            <div className="mb-1 flex items-center gap-2">
              <Zap className="h-4 w-4 text-gray-400" />
              <span className="text-xs font-semibold text-gray-500">Keepalive (reclaim defense)</span>
            </div>
            {d.keepalive.last_run ? (
              <div>
                <p className="text-sm font-semibold text-gray-800">
                  {formatAge(d.keepalive.seconds_since)}
                </p>
                <p className="text-xs text-gray-500">
                  last: {new Date(d.keepalive.last_run).toLocaleString()}
                </p>
              </div>
            ) : (
              <Badge variant="danger">Never ran — check cron</Badge>
            )}
          </div>

          <div className="rounded-lg border border-gray-100 p-3">
            <div className="mb-1 flex items-center gap-2">
              <GitCommit className="h-4 w-4 text-gray-400" />
              <span className="text-xs font-semibold text-gray-500">Last deploy</span>
            </div>
            {d.last_deploy ? (
              <div>
                <p className="font-mono text-sm font-semibold text-gray-800">
                  {d.last_deploy.release}
                </p>
                <p className="text-xs text-gray-500">
                  {new Date(d.last_deploy.deployed_at).toLocaleString()}
                </p>
              </div>
            ) : (
              <span className="text-sm text-gray-400">no deploy recorded</span>
            )}
          </div>
        </div>

        {/* ── Containers + Network ── */}
        <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
          <ContainerList containers={d.containers} />

          <div>
            <div className="mb-2 flex items-center gap-2">
              <Network className="h-4 w-4 text-gray-400" />
              <span className="text-xs font-semibold text-gray-500">Network (since boot)</span>
            </div>
            <div className="space-y-1.5">
              {d.network.interfaces.map((iface) => (
                <div
                  key={iface.name}
                  className="flex items-center justify-between rounded border border-gray-100 bg-gray-50 px-3 py-1.5 text-xs"
                >
                  <span className="font-mono text-gray-700">{iface.name}</span>
                  <span className="text-gray-500">
                    ↓ {formatBytes(iface.rx_bytes)} · ↑ {formatBytes(iface.tx_bytes)}
                  </span>
                </div>
              ))}
              {d.network.projected_monthly_egress_tb !== null && (
                <div className="flex items-center justify-between rounded bg-amber-50 border border-amber-100 px-3 py-1.5 text-xs">
                  <span className="text-amber-800">Projected monthly egress</span>
                  <span className="font-semibold text-amber-900">
                    {d.network.projected_monthly_egress_tb.toFixed(2)} TB
                    <span className="ml-1 font-normal opacity-70">
                      ({(d.network.projected_egress_pct_of_free_tier ?? 0).toFixed(1)}% of cap)
                    </span>
                  </span>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* ── Backups ── */}
        {d.backups.count > 0 && (
          <div className="mt-5 rounded-lg border border-gray-100 bg-gray-50 px-4 py-3">
            <div className="mb-1 flex items-center gap-2">
              <HardDrive className="h-4 w-4 text-gray-400" />
              <span className="text-xs font-semibold text-gray-500">Backups on disk</span>
            </div>
            <p className="text-xs text-gray-600">
              {d.backups.count} dumps · {formatBytes(d.backups.total_size_bytes)}
              {d.backups.newest && (
                <> · newest {new Date(d.backups.newest).toLocaleDateString()}</>
              )}
              {d.backups.oldest && (
                <> · oldest {new Date(d.backups.oldest).toLocaleDateString()}</>
              )}
            </p>
          </div>
        )}
      </Card>
    </div>
  );
}
