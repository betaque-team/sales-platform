import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Brain, DollarSign, Clock, Users, AlertTriangle,
  CheckCircle2, XCircle, ArrowRight, Linkedin, Mail,
  Zap, AlertCircle, RefreshCw,
} from "lucide-react";
import {
  ApiError,
  getSkillGaps, getSalaryInsights, getTimingIntelligence, getNetworkingSuggestions,
} from "@/lib/api";
import { formatCount } from "@/lib/format";

// Regression finding 216 (mirror of F207 on IntelligencePage tabs):
// previously each tab only destructured `{ data, isLoading }` and rendered
// `null` on any non-loading state where `data` was falsy — so an expired
// session (401), a backend outage (5xx), or a network drop all produced
// the same blank tab panel. Users couldn't tell "the server is down" from
// "there's no data to show you." This file now renders distinct error UX
// for 401/403 (session expired → sign-in link), 5xx / network, and other
// failures, while keeping the networking tab's empty-data state intact
// (that one is a valid "no suggestions yet" message, not an error).
type QueryRetry = (failureCount: number, err: unknown) => boolean;

const skipAuthAnd404Retry: QueryRetry = (failureCount, err) => {
  if (err instanceof ApiError && (err.status === 401 || err.status === 404)) {
    return false;
  }
  return failureCount < 2;
};

const TABS = [
  { key: "skills", label: "Skill Gaps", icon: Brain },
  { key: "salary", label: "Salary Intel", icon: DollarSign },
  { key: "timing", label: "Timing", icon: Clock },
  { key: "networking", label: "Networking", icon: Users },
] as const;

type TabKey = (typeof TABS)[number]["key"];

export function IntelligencePage() {
  const [tab, setTab] = useState<TabKey>("skills");
  const [roleFilter, setRoleFilter] = useState("");

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Intelligence</h1>
        <p className="mt-1 text-sm text-gray-600">
          Competitive insights to stay ahead of other candidates
        </p>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 rounded-lg bg-gray-100 p-1">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-colors ${
              tab === t.key
                ? "bg-white text-gray-900 shadow-sm"
                : "text-gray-600 hover:text-gray-900"
            }`}
          >
            <t.icon className="h-4 w-4" />
            {t.label}
          </button>
        ))}
      </div>

      {/* Role filter for skills and salary */}
      {(tab === "skills" || tab === "salary") && (
        <div className="flex items-center gap-2">
          <label className="text-sm text-gray-600">Role cluster:</label>
          <select
            value={roleFilter}
            onChange={(e) => setRoleFilter(e.target.value)}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm"
          >
            <option value="">All</option>
            <option value="infra">Infrastructure</option>
            <option value="security">Security</option>
            <option value="qa">QA / Testing</option>
          </select>
        </div>
      )}

      {tab === "skills" && <SkillGapTab roleCluster={roleFilter} />}
      {tab === "salary" && <SalaryTab roleCluster={roleFilter} />}
      {tab === "timing" && <TimingTab />}
      {tab === "networking" && <NetworkingTab />}
    </div>
  );
}

// ── Skill Gap Tab ─��─────────────────────────────────────────────────────────

function SkillGapTab({ roleCluster }: { roleCluster: string }) {
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["skill-gaps", roleCluster],
    queryFn: () => getSkillGaps(roleCluster || undefined),
    retry: skipAuthAnd404Retry,
  });

  if (isLoading) return <LoadingSkeleton />;
  if (isError) return <TabErrorState error={error} onRetry={() => refetch()} />;
  if (!data) return null;

  const { summary, top_missing, category_breakdown, skills } = data;

  return (
    <div className="space-y-4">
      {/* Summary cards */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <StatCard label="Jobs Analyzed" value={summary.jobs_analyzed} />
        <StatCard label="Skills Tracked" value={summary.total_skills_tracked} />
        <StatCard label="On Your Resume" value={summary.skills_on_resume} color="green" />
        <StatCard label="Missing" value={summary.skills_missing} color="red" />
        <StatCard label="Coverage" value={`${summary.coverage_pct}%`} color={summary.coverage_pct >= 60 ? "green" : "amber"} />
      </div>

      {!data.has_resume && (
        <div className="flex items-center gap-2 rounded-lg bg-amber-50 border border-amber-200 p-4 text-sm text-amber-800">
          <AlertTriangle className="h-4 w-4 flex-shrink-0" />
          Upload and set an active resume to see which skills you have vs. missing.
        </div>
      )}

      {/* Top Missing Skills */}
      {top_missing.length > 0 && (
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <h3 className="text-sm font-semibold text-gray-900 mb-3">Top Missing Skills (High Demand)</h3>
          <div className="flex flex-wrap gap-2">
            {top_missing.map((s) => (
              <span
                key={s.skill}
                className="inline-flex items-center gap-1 rounded-full bg-red-50 border border-red-200 px-3 py-1 text-sm"
              >
                <XCircle className="h-3.5 w-3.5 text-red-500" />
                <span className="font-medium text-red-800">{s.skill}</span>
                <span className="text-red-500 text-xs">{s.demand_pct}% of jobs</span>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Category Breakdown */}
      <div className="rounded-xl border border-gray-200 bg-white p-5">
        <h3 className="text-sm font-semibold text-gray-900 mb-3">Skills by Category</h3>
        <div className="space-y-3">
          {category_breakdown.map((cat) => {
            const pct = cat.total ? Math.round((cat.have / cat.total) * 100) : 0;
            return (
              <div key={cat.category} className="space-y-1">
                <div className="flex items-center justify-between text-sm">
                  <span className="font-medium text-gray-700 capitalize">{cat.category.replace("_", " ")}</span>
                  <span className="text-gray-500">
                    {cat.have}/{cat.total} skills ({pct}%)
                  </span>
                </div>
                <div className="h-2 rounded-full bg-gray-100 overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all ${pct >= 70 ? "bg-green-500" : pct >= 40 ? "bg-amber-500" : "bg-red-500"}`}
                    style={{ width: `${pct}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Full Skills Table */}
      <div className="rounded-xl border border-gray-200 bg-white p-5">
        <h3 className="text-sm font-semibold text-gray-900 mb-3">All Skills by Demand</h3>
        <div className="max-h-96 overflow-y-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-white">
              <tr className="text-left text-gray-500 border-b">
                <th className="pb-2 font-medium">Skill</th>
                <th className="pb-2 font-medium">Category</th>
                <th className="pb-2 font-medium text-right">Demand</th>
                <th className="pb-2 font-medium text-center">Status</th>
              </tr>
            </thead>
            <tbody>
              {skills.filter((s) => s.demand_pct >= 3).map((s) => (
                <tr key={s.skill} className="border-b border-gray-50">
                  <td className="py-2 font-medium text-gray-900">{s.skill}</td>
                  <td className="py-2 text-gray-500 capitalize">{s.category.replace("_", " ")}</td>
                  <td className="py-2 text-right text-gray-600">{s.demand_pct}%</td>
                  <td className="py-2 text-center">
                    {s.on_resume ? (
                      <CheckCircle2 className="h-4 w-4 text-green-500 inline" />
                    ) : (
                      <XCircle className="h-4 w-4 text-red-400 inline" />
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ── Salary Tab ──────────────────────────────────────────────────────────────

function SalaryTab({ roleCluster }: { roleCluster: string }) {
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["salary-insights", roleCluster],
    queryFn: () => getSalaryInsights(roleCluster || undefined),
    retry: skipAuthAnd404Retry,
  });

  if (isLoading) return <LoadingSkeleton />;
  if (isError) return <TabErrorState error={error} onRetry={() => refetch()} />;
  if (!data) return null;

  const fmt = (n: number) => `$${Math.round(n / 1000)}k`;

  return (
    <div className="space-y-4">
      {/* Overall stats */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <StatCard label="Jobs w/ Salary" value={data.total_with_salary} />
        <StatCard label="Median" value={fmt(data.overall.median)} color="green" />
        <StatCard label="Average" value={fmt(data.overall.avg)} />
        <StatCard label="Min" value={fmt(data.overall.min)} />
        <StatCard label="Max" value={fmt(data.overall.max)} color="blue" />
      </div>

      {/* Distribution */}
      <div className="rounded-xl border border-gray-200 bg-white p-5">
        <h3 className="text-sm font-semibold text-gray-900 mb-3">Salary Distribution</h3>
        <div className="flex items-end gap-2 h-40">
          {data.distribution.map((d) => {
            const maxCount = Math.max(...data.distribution.map((x) => x.count), 1);
            const height = (d.count / maxCount) * 100;
            return (
              <div key={d.range} className="flex-1 flex flex-col items-center gap-1">
                <span className="text-xs text-gray-600">{d.count}</span>
                <div
                  className="w-full rounded-t bg-primary-500 transition-all"
                  style={{ height: `${height}%`, minHeight: d.count > 0 ? "4px" : "0" }}
                />
                <span className="text-xs text-gray-500 whitespace-nowrap">{d.range}</span>
              </div>
            );
          })}
        </div>
      </div>

      {/* By cluster */}
      <div className="grid gap-4 md:grid-cols-2">
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <h3 className="text-sm font-semibold text-gray-900 mb-3">By Role Cluster</h3>
          <div className="space-y-3">
            {Object.entries(data.by_cluster).map(([cluster, stats]) => (
              <div key={cluster} className="flex items-center justify-between rounded-lg bg-gray-50 p-3">
                <div>
                  <span className="text-sm font-medium text-gray-900 capitalize">{cluster || "Other"}</span>
                  <span className="ml-2 text-xs text-gray-500">{formatCount(stats.count)} jobs</span>
                </div>
                <div className="text-right">
                  <span className="text-sm font-semibold text-gray-900">{fmt(stats.median)}</span>
                  <span className="ml-1 text-xs text-gray-500">median</span>
                </div>
              </div>
            ))}
          </div>
        </div>
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <h3 className="text-sm font-semibold text-gray-900 mb-3">By Geography</h3>
          <div className="space-y-3">
            {Object.entries(data.by_geography).map(([geo, stats]) => (
              <div key={geo} className="flex items-center justify-between rounded-lg bg-gray-50 p-3">
                <div>
                  <span className="text-sm font-medium text-gray-900 capitalize">{geo.replace("_", " ") || "Unspecified"}</span>
                  <span className="ml-2 text-xs text-gray-500">{formatCount(stats.count)} jobs</span>
                </div>
                <div className="text-right">
                  <span className="text-sm font-semibold text-gray-900">{fmt(stats.median)}</span>
                  <span className="ml-1 text-xs text-gray-500">median</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Top paying */}
      <div className="rounded-xl border border-gray-200 bg-white p-5">
        <h3 className="text-sm font-semibold text-gray-900 mb-3">Top Paying Roles</h3>
        <div className="space-y-2">
          {data.top_paying.slice(0, 10).map((j, i) => (
            <div key={i} className="flex items-center justify-between rounded-lg bg-gray-50 p-3">
              <div className="min-w-0">
                <div className="text-sm font-medium text-gray-900 truncate">{j.title}</div>
                <div className="text-xs text-gray-500">{j.company} &middot; {j.role_cluster}</div>
              </div>
              <span className="text-sm font-semibold text-green-700 whitespace-nowrap ml-3">
                {fmt(j.min)}-{fmt(j.max)}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Timing Tab ──────────────────────────────────────────────────────────────

function TimingTab() {
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["timing-intelligence"],
    queryFn: getTimingIntelligence,
    retry: skipAuthAnd404Retry,
  });

  if (isLoading) return <LoadingSkeleton />;
  if (isError) return <TabErrorState error={error} onRetry={() => refetch()} />;
  if (!data) return null;

  return (
    <div className="space-y-4">
      {/* Recommendations */}
      <div className="rounded-xl border border-blue-200 bg-blue-50 p-5">
        <h3 className="text-sm font-semibold text-blue-900 mb-3 flex items-center gap-2">
          <Zap className="h-4 w-4" /> Timing Recommendations
        </h3>
        <div className="grid gap-3 md:grid-cols-2">
          <div className="rounded-lg bg-white p-3">
            <div className="text-xs text-gray-500 uppercase font-medium">Best Day to Apply</div>
            <div className="text-lg font-bold text-gray-900">{data.recommendations.best_day}</div>
          </div>
          <div className="rounded-lg bg-white p-3">
            <div className="text-xs text-gray-500 uppercase font-medium">Peak Posting Hours</div>
            <div className="text-lg font-bold text-gray-900">{data.recommendations.peak_posting_hours}</div>
          </div>
          <div className="rounded-lg bg-white p-3">
            <div className="text-xs text-gray-500 uppercase font-medium">Ideal Apply Window</div>
            <div className="text-sm font-medium text-gray-900">{data.recommendations.ideal_apply_window}</div>
          </div>
          <div className="rounded-lg bg-white p-3">
            <div className="text-xs text-gray-500 uppercase font-medium">Avg Time to Review</div>
            <div className="text-lg font-bold text-gray-900">{data.avg_review_hours}h</div>
          </div>
        </div>
      </div>

      {/* Posting by day */}
      <div className="rounded-xl border border-gray-200 bg-white p-5">
        <h3 className="text-sm font-semibold text-gray-900 mb-3">Jobs Posted by Day of Week (Last 90 Days)</h3>
        <div className="flex items-end gap-2 h-32">
          {data.posting_by_day.map((d) => {
            const max = Math.max(...data.posting_by_day.map((x) => x.count), 1);
            const height = (d.count / max) * 100;
            return (
              <div key={d.day} className="flex-1 flex flex-col items-center gap-1">
                <span className="text-xs text-gray-600">{d.count}</span>
                <div
                  className="w-full rounded-t bg-primary-500 transition-all"
                  style={{ height: `${height}%`, minHeight: d.count > 0 ? "4px" : "0" }}
                />
                <span className="text-xs text-gray-500">{d.day.slice(0, 3)}</span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Platform velocity */}
      <div className="rounded-xl border border-gray-200 bg-white p-5">
        <h3 className="text-sm font-semibold text-gray-900 mb-3">Platform Velocity</h3>
        <div className="space-y-2">
          {data.platform_velocity.map((p) => (
            <div key={p.platform} className="flex items-center justify-between rounded-lg bg-gray-50 p-3">
              <span className="text-sm font-medium text-gray-900 capitalize">{p.platform}</span>
              <div className="flex items-center gap-4 text-sm">
                <span className="text-gray-500">{formatCount(p.total_90d)} total (90d)</span>
                <span className="font-medium text-green-700">{formatCount(p.last_7d)} this week</span>
                <span className="text-gray-600">{formatCount(p.last_30d)} this month</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Freshness */}
      <div className="rounded-xl border border-gray-200 bg-white p-5">
        <h3 className="text-sm font-semibold text-gray-900 mb-3">When Were Accepted Jobs Reviewed?</h3>
        <div className="flex items-end gap-3 h-32">
          {data.freshness_distribution.map((f) => {
            const max = Math.max(...data.freshness_distribution.map((x) => x.count), 1);
            const height = (f.count / max) * 100;
            return (
              <div key={f.bucket} className="flex-1 flex flex-col items-center gap-1">
                <span className="text-xs text-gray-600">{f.count}</span>
                <div
                  className="w-full rounded-t bg-green-500"
                  style={{ height: `${height}%`, minHeight: f.count > 0 ? "4px" : "0" }}
                />
                <span className="text-xs text-gray-500 text-center">{f.bucket}</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// ── Networking Tab ──────────────────────────────────────────────────────────

function NetworkingTab() {
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["networking-suggestions"],
    queryFn: () => getNetworkingSuggestions(),
    retry: skipAuthAnd404Retry,
  });

  if (isLoading) return <LoadingSkeleton />;
  // F216: error must precede the empty-state check. A 5xx/401 returns
  // `data === undefined`, which the old guard collapsed into the "no
  // networking suggestions yet" message — silently lying to the user about
  // whether the backend was reachable.
  if (isError) return <TabErrorState error={error} onRetry={() => refetch()} />;
  if (!data?.suggestions?.length) {
    return (
      <div className="rounded-xl border border-gray-200 bg-white p-8 text-center">
        <Users className="h-8 w-8 text-gray-300 mx-auto mb-2" />
        <p className="text-sm text-gray-500">No networking suggestions yet. Accept some jobs and enrich companies to see suggestions.</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-blue-200 bg-blue-50 p-4">
        <p className="text-sm text-blue-800">
          These contacts are at companies with open roles matching your criteria. Prioritized by decision-maker status, email verification, and job relevance.
        </p>
      </div>

      <div className="space-y-3">
        {data.suggestions.map((s) => (
          <div key={s.contact_id} className="rounded-xl border border-gray-200 bg-white p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold text-gray-900">{s.name}</span>
                  {s.is_decision_maker && (
                    <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold text-amber-700">
                      Decision Maker
                    </span>
                  )}
                  <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
                    s.email_status === "valid" ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-600"
                  }`}>
                    {s.email_status}
                  </span>
                </div>
                <div className="text-sm text-gray-600">{s.title}</div>
                <div className="text-xs text-gray-500 mt-0.5">{s.company}</div>
                {s.open_roles && (
                  <div className="text-xs text-primary-600 mt-1">{s.open_roles} open roles, top score: {s.top_relevance_score}</div>
                )}
              </div>
              <div className="flex gap-2 flex-shrink-0">
                {s.linkedin_url && (
                  <a href={s.linkedin_url} target="_blank" rel="noopener noreferrer"
                    className="rounded-lg border border-gray-200 p-2 text-gray-600 hover:bg-gray-50 hover:text-blue-600">
                    <Linkedin className="h-4 w-4" />
                  </a>
                )}
                {s.email && s.email_status === "valid" && (
                  <a href={`mailto:${s.email}`}
                    className="rounded-lg border border-gray-200 p-2 text-gray-600 hover:bg-gray-50 hover:text-green-600">
                    <Mail className="h-4 w-4" />
                  </a>
                )}
              </div>
            </div>
            <div className="mt-2 flex items-center gap-2 text-xs">
              <span className="text-gray-500">{s.relevance_reason}</span>
              <ArrowRight className="h-3 w-3 text-gray-400" />
              <span className="text-primary-700 font-medium">{s.suggested_approach}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─�� Shared Components ───────────────────────────────────────────────────────

function StatCard({ label, value, color }: { label: string; value: string | number; color?: string }) {
  const colorMap: Record<string, string> = {
    green: "text-green-700",
    red: "text-red-700",
    amber: "text-amber-700",
    blue: "text-blue-700",
  };
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4">
      <div className="text-xs text-gray-500 font-medium">{label}</div>
      {/* Regression finding 36: stat-card counts like `15865 total (90d)`
          rendered unformatted. Numeric values route through `formatCount`
          for locale grouping; pre-formatted strings pass through. */}
      <div className={`text-xl font-bold mt-1 ${colorMap[color || ""] || "text-gray-900"}`}>
        {typeof value === "number" ? formatCount(value) : value}
      </div>
    </div>
  );
}

function LoadingSkeleton() {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        {[...Array(5)].map((_, i) => (
          <div key={i} className="rounded-xl border border-gray-200 bg-white p-4 animate-pulse">
            <div className="h-3 w-16 bg-gray-200 rounded" />
            <div className="h-6 w-12 bg-gray-200 rounded mt-2" />
          </div>
        ))}
      </div>
      <div className="rounded-xl border border-gray-200 bg-white p-5 h-48 animate-pulse" />
    </div>
  );
}

// F216: tab-level error state. Distinguishes session-expired (401/403 —
// offer a sign-in link that preserves `next` so the user lands back here
// after auth) from transient/server failures (5xx / network — offer a
// retry). We don't render a 404 branch because the intelligence endpoints
// are aggregates that don't take a resource id; a 404 from them means
// the route is gone and retry won't help either, so we fall through to
// the generic failure message.
function TabErrorState({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const status = error instanceof ApiError ? error.status : 0;
  const message = error instanceof Error ? error.message : "";

  if (status === 401 || status === 403) {
    return (
      <div className="rounded-xl border border-amber-200 bg-amber-50 p-8 text-center">
        <AlertTriangle className="mx-auto h-8 w-8 text-amber-500" />
        <p className="mt-3 text-sm font-medium text-gray-900">Your session has expired</p>
        <p className="mt-1 text-sm text-gray-600">Please sign in again to continue.</p>
        <button
          onClick={() => {
            const next = encodeURIComponent(window.location.pathname + window.location.search);
            window.location.assign(`/login?next=${next}`);
          }}
          className="mt-4 rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 transition-colors"
        >
          Sign in
        </button>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-8 text-center">
      <AlertCircle className="mx-auto h-8 w-8 text-amber-400" />
      <p className="mt-3 text-sm font-medium text-gray-900">Couldn't load this section</p>
      <p className="mt-1 text-sm text-gray-500">
        {status >= 500
          ? "The server ran into a problem. Please try again in a moment."
          : message || "Check your connection and try again."}
      </p>
      <button
        onClick={onRetry}
        className="mt-4 inline-flex items-center gap-2 rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 transition-colors"
      >
        <RefreshCw className="h-4 w-4" />
        Retry
      </button>
    </div>
  );
}
