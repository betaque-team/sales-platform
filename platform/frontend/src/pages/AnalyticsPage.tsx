import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
  AreaChart,
  Area,
} from "recharts";
import {
  Briefcase,
  CheckCircle2,
  XCircle,
  TrendingUp,
  Percent,
  BarChart3,
} from "lucide-react";
import { Card } from "@/components/Card";
import { BackendErrorBanner } from "@/components/BackendErrorBanner";
import {
  getAnalyticsOverview,
  getAnalyticsSources,
  getAnalyticsTrends,
  getAnalyticsFunnel,
  getApplicationFunnel,
  getApplicationsByPlatform,
  getReviewInsights,
  getRelevantJobsTrend,
} from "@/lib/api";
import { formatCount } from "@/lib/format";

const PIE_COLORS = [
  "#6366f1",
  "#3b82f6",
  "#10b981",
  "#f59e0b",
  "#ef4444",
  "#8b5cf6",
  "#ec4899",
  "#14b8a6",
  "#f97316",
  "#64748b",
];

const RANGE_OPTIONS = [
  { label: "7 days", value: 7 },
  { label: "30 days", value: 30 },
  { label: "90 days", value: 90 },
];

function MetricCard({
  label,
  value,
  icon: Icon,
  color,
}: {
  label: string;
  value: string | number;
  icon: React.ElementType;
  color: string;
}) {
  return (
    <Card>
      <div className="flex items-center gap-3">
        <div className={`flex h-10 w-10 items-center justify-center rounded-lg ${color}`}>
          <Icon className="h-5 w-5 text-white" />
        </div>
        <div>
          <p className="text-xs text-gray-500">{label}</p>
          {/* Regression finding 49: numeric metrics like `Total Jobs: 47776`
              rendered without thousand separators on this page while the
              same number on /platforms showed `47,776`. Format numeric
              values here through `formatCount` so the default is
              locale-grouped; callers passing a preformatted string (e.g.
              "3.5%") pass through untouched. */}
          <p className="text-xl font-bold text-gray-900">
            {typeof value === "number" ? formatCount(value) : value}
          </p>
        </div>
      </div>
    </Card>
  );
}

export function AnalyticsPage() {
  const [days, setDays] = useState(30);

  // F222: see DashboardPage for the rationale. 7 previously-silent
  // queries are now routed through the shared `<BackendErrorBanner>`.
  const overviewQ = useQuery({
    queryKey: ["analytics", "overview"],
    queryFn: getAnalyticsOverview,
  });
  const overview = overviewQ.data;
  const overviewLoading = overviewQ.isLoading;

  const sourcesQ = useQuery({
    queryKey: ["analytics", "sources"],
    queryFn: getAnalyticsSources,
  });
  const sources = sourcesQ.data;

  const trendsQ = useQuery({
    queryKey: ["analytics", "trends", days],
    queryFn: () => getAnalyticsTrends(days),
  });
  const trends = trendsQ.data;

  const funnelQ = useQuery({
    queryKey: ["analytics", "funnel"],
    queryFn: getAnalyticsFunnel,
  });
  const funnel = funnelQ.data;

  const appFunnelQ = useQuery({
    queryKey: ["app-funnel"],
    queryFn: getApplicationFunnel,
  });
  const appFunnel = appFunnelQ.data;

  const appByPlatformQ = useQuery({
    queryKey: ["app-by-platform"],
    queryFn: getApplicationsByPlatform,
  });
  const appByPlatform = appByPlatformQ.data;

  const reviewInsightsQ = useQuery({
    queryKey: ["review-insights"],
    queryFn: getReviewInsights,
  });
  const reviewInsights = reviewInsightsQ.data;

  const analyticsQueries = [
    overviewQ, sourcesQ, trendsQ, funnelQ, appFunnelQ, appByPlatformQ, reviewInsightsQ,
  ];

  if (overviewLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="spinner h-8 w-8" />
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Analytics</h1>
          <p className="mt-1 text-sm text-gray-500">
            Performance metrics and trends
          </p>
        </div>
        <div className="flex items-center gap-1 rounded-lg bg-gray-100 p-1">
          {RANGE_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => setDays(opt.value)}
              className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                days === opt.value
                  ? "bg-white text-gray-900 shadow-sm"
                  : "text-gray-600 hover:text-gray-900"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {/* F222: surfaces any failed query out of the 7 on this page. */}
      <BackendErrorBanner queries={analyticsQueries} />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <MetricCard
          label="Total Jobs"
          value={overview?.total_jobs ?? 0}
          icon={Briefcase}
          color="bg-primary-600"
        />
        <MetricCard
          label="Accepted"
          value={overview?.accepted_count ?? 0}
          icon={CheckCircle2}
          color="bg-green-600"
        />
        <MetricCard
          label="Rejected"
          value={overview?.rejected_count ?? 0}
          icon={XCircle}
          color="bg-red-500"
        />
        <MetricCard
          label="Acceptance Rate"
          value={
            overview?.acceptance_rate
              ? `${(overview.acceptance_rate * 100).toFixed(1)}%`
              : "N/A"
          }
          icon={Percent}
          color="bg-emerald-500"
        />
        <MetricCard
          label="Avg Score"
          value={overview?.avg_relevance_score?.toFixed(1) ?? "0.0"}
          icon={TrendingUp}
          color="bg-purple-600"
        />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card padding="none">
          <div className="border-b border-gray-100 px-6 py-4">
            <h3 className="text-base font-semibold text-gray-900">
              Job Trends ({days}d)
            </h3>
          </div>
          <div className="p-6">
            {trends && trends.length > 0 ? (
              <ResponsiveContainer width="100%" height={300}>
                <LineChart data={trends} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                  <XAxis
                    dataKey="day"
                    tick={{ fontSize: 11, fill: "#9ca3af" }}
                    axisLine={{ stroke: "#e5e7eb" }}
                    tickFormatter={(val: string) => {
                      if (!val) return "";
                      const d = new Date(val);
                      if (isNaN(d.getTime())) return val;
                      return `${d.getMonth() + 1}/${d.getDate()}`;
                    }}
                  />
                  <YAxis
                    tick={{ fontSize: 11, fill: "#9ca3af" }}
                    axisLine={{ stroke: "#e5e7eb" }}
                  />
                  <Tooltip
                    contentStyle={{
                      borderRadius: "8px",
                      border: "1px solid #e5e7eb",
                      fontSize: "13px",
                    }}
                  />
                  {/* Regression finding 48: default <Legend /> rendered
                      the three series labels as one concatenated run
                      ("New JobsAcceptedRejected") because Tailwind's
                      preflight resets the default margins Recharts relies
                      on to space `<li>` items. Supplying a wrapperStyle
                      with an explicit horizontal gap and a formatter that
                      pads the text restores readable separation without
                      replacing the component. */}
                  <Legend
                    wrapperStyle={{ paddingTop: 8, display: "flex", justifyContent: "center", gap: 16 }}
                    formatter={(v) => <span style={{ marginLeft: 4, marginRight: 4 }}>{v}</span>}
                  />
                  <Line
                    type="monotone"
                    dataKey="total"
                    stroke="#6366f1"
                    strokeWidth={2}
                    dot={false}
                    name="New Jobs"
                  />
                  <Line
                    type="monotone"
                    dataKey="accepted"
                    stroke="#10b981"
                    strokeWidth={2}
                    dot={false}
                    name="Accepted"
                  />
                  <Line
                    type="monotone"
                    dataKey="rejected"
                    stroke="#ef4444"
                    strokeWidth={2}
                    dot={false}
                    name="Rejected"
                  />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <div className="flex items-center justify-center py-16 text-sm text-gray-500">
                No trend data available
              </div>
            )}
          </div>
        </Card>

        <Card padding="none">
          <div className="border-b border-gray-100 px-6 py-4">
            <h3 className="text-base font-semibold text-gray-900">
              Source Distribution
            </h3>
          </div>
          <div className="p-6">
            {sources && sources.length > 0 ? (
              <ResponsiveContainer width="100%" height={300}>
                <PieChart>
                  <Pie
                    data={sources}
                    dataKey="count"
                    nameKey="platform"
                    cx="50%"
                    cy="50%"
                    outerRadius={100}
                    innerRadius={50}
                    paddingAngle={2}
                    label={({ platform, percent }: { platform: string; percent: number }) =>
                      `${platform} (${(percent * 100).toFixed(0)}%)`
                    }
                    labelLine={{ strokeWidth: 1 }}
                  >
                    {sources.map((_, index) => (
                      <Cell
                        key={`cell-${index}`}
                        fill={PIE_COLORS[index % PIE_COLORS.length]}
                      />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={{
                      borderRadius: "8px",
                      border: "1px solid #e5e7eb",
                      fontSize: "13px",
                    }}
                  />
                </PieChart>
              </ResponsiveContainer>
            ) : (
              <div className="flex items-center justify-center py-16 text-sm text-gray-500">
                No source data available
              </div>
            )}
          </div>
        </Card>
      </div>

      <Card padding="none">
        <div className="border-b border-gray-100 px-6 py-4">
          <h3 className="text-base font-semibold text-gray-900">
            Pipeline Funnel
          </h3>
        </div>
        <div className="p-6">
          {funnel && funnel.stages && funnel.stages.length > 0 ? (
            <ResponsiveContainer width="100%" height={300}>
              <BarChart
                data={funnel.stages}
                layout="vertical"
                margin={{ top: 5, right: 30, bottom: 5, left: 100 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" horizontal={false} />
                <XAxis
                  type="number"
                  tick={{ fontSize: 11, fill: "#9ca3af" }}
                  axisLine={{ stroke: "#e5e7eb" }}
                />
                <YAxis
                  type="category"
                  dataKey="stage"
                  tick={{ fontSize: 12, fill: "#6b7280" }}
                  axisLine={{ stroke: "#e5e7eb" }}
                  width={90}
                />
                <Tooltip
                  contentStyle={{
                    borderRadius: "8px",
                    border: "1px solid #e5e7eb",
                    fontSize: "13px",
                  }}
                />
                <Bar
                  dataKey="count"
                  fill="#6366f1"
                  radius={[0, 4, 4, 0]}
                  maxBarSize={32}
                />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex items-center justify-center py-16">
              <div className="text-center">
                <BarChart3 className="mx-auto h-10 w-10 text-gray-300" />
                <p className="mt-3 text-sm text-gray-500">
                  No funnel data available yet
                </p>
              </div>
            </div>
          )}
        </div>
      </Card>

      {/* F258: Relevant pipeline — per-day breakdown by cluster + geography */}
      <RelevantPipelineCard days={days} />

      {/* Application Analytics */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card padding="none">
          <div className="border-b border-gray-100 px-6 py-4">
            <h3 className="text-base font-semibold text-gray-900">
              Application Funnel
            </h3>
          </div>
          <div className="p-6">
            {appFunnel?.stages && appFunnel.stages.length > 0 ? (
              <div>
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart
                    data={appFunnel.stages}
                    layout="vertical"
                    margin={{ top: 5, right: 30, bottom: 5, left: 80 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" horizontal={false} />
                    <XAxis
                      type="number"
                      tick={{ fontSize: 11, fill: "#9ca3af" }}
                      axisLine={{ stroke: "#e5e7eb" }}
                    />
                    <YAxis
                      type="category"
                      dataKey="stage"
                      tick={{ fontSize: 12, fill: "#6b7280" }}
                      axisLine={{ stroke: "#e5e7eb" }}
                      width={70}
                    />
                    <Tooltip
                      contentStyle={{
                        borderRadius: "8px",
                        border: "1px solid #e5e7eb",
                        fontSize: "13px",
                      }}
                    />
                    <Bar dataKey="count" fill="#6366f1" radius={[0, 4, 4, 0]} maxBarSize={28} />
                  </BarChart>
                </ResponsiveContainer>
                {appFunnel.conversion && appFunnel.conversion.length > 0 && (
                  <div className="mt-4 flex flex-wrap gap-3">
                    {appFunnel.conversion.map(
                      (c: { from: string; to: string; rate: number }, i: number) => (
                        <span
                          key={i}
                          className="rounded-full bg-gray-100 px-3 py-1 text-xs text-gray-600"
                        >
                          {c.from} &rarr; {c.to}: {c.rate.toFixed(1)}%
                        </span>
                      )
                    )}
                  </div>
                )}
                {(appFunnel.rejected != null || appFunnel.withdrawn != null) && (
                  <div className="mt-3 flex gap-4 text-xs text-gray-500">
                    {appFunnel.rejected != null && (
                      <span>Rejected: {appFunnel.rejected}</span>
                    )}
                    {appFunnel.withdrawn != null && (
                      <span>Withdrawn: {appFunnel.withdrawn}</span>
                    )}
                  </div>
                )}
              </div>
            ) : (
              <div className="flex items-center justify-center py-16 text-sm text-gray-500">
                No application funnel data available
              </div>
            )}
          </div>
        </Card>

        <Card padding="none">
          <div className="border-b border-gray-100 px-6 py-4">
            <h3 className="text-base font-semibold text-gray-900">
              Applications by Platform
            </h3>
          </div>
          <div className="p-6">
            {appByPlatform?.platforms && appByPlatform.platforms.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-100 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                      <th className="pb-3 pr-4">Platform</th>
                      <th className="pb-3 pr-4 text-right">Total</th>
                      <th className="pb-3 pr-4 text-right">Applied</th>
                      <th className="pb-3 pr-4 text-right">Interview</th>
                      <th className="pb-3 text-right">Offer</th>
                    </tr>
                  </thead>
                  <tbody>
                    {appByPlatform.platforms.map(
                      (
                        p: {
                          platform: string;
                          total: number;
                          applied: number;
                          interview: number;
                          offer: number;
                        },
                        i: number
                      ) => (
                        <tr
                          key={i}
                          className="border-b border-gray-50 last:border-0"
                        >
                          <td className="py-2.5 pr-4 font-medium text-gray-900">
                            {p.platform}
                          </td>
                          <td className="py-2.5 pr-4 text-right text-gray-600">
                            {p.total}
                          </td>
                          <td className="py-2.5 pr-4 text-right text-gray-600">
                            {p.applied}
                          </td>
                          <td className="py-2.5 pr-4 text-right text-gray-600">
                            {p.interview}
                          </td>
                          <td className="py-2.5 text-right text-gray-600">
                            {p.offer}
                          </td>
                        </tr>
                      )
                    )}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="flex items-center justify-center py-16 text-sm text-gray-500">
                No platform data available
              </div>
            )}
          </div>
        </Card>
      </div>

      {/* Review Insights */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card padding="none">
          <div className="border-b border-gray-100 px-6 py-4">
            <h3 className="text-base font-semibold text-gray-900">
              Rejection Reasons
            </h3>
          </div>
          <div className="p-6">
            {reviewInsights?.rejection_reasons &&
            reviewInsights.rejection_reasons.length > 0 ? (
              <ResponsiveContainer width="100%" height={300}>
                <PieChart>
                  <Pie
                    data={reviewInsights.rejection_reasons}
                    dataKey="count"
                    nameKey="tag"
                    cx="50%"
                    cy="50%"
                    outerRadius={100}
                    innerRadius={50}
                    paddingAngle={2}
                    label={({ tag, percent }: { tag: string; percent: number }) =>
                      `${tag} (${(percent * 100).toFixed(0)}%)`
                    }
                    labelLine={{ strokeWidth: 1 }}
                  >
                    {reviewInsights.rejection_reasons.map(
                      (_: unknown, index: number) => (
                        <Cell
                          key={`rej-${index}`}
                          fill={PIE_COLORS[index % PIE_COLORS.length]}
                        />
                      )
                    )}
                  </Pie>
                  <Tooltip
                    contentStyle={{
                      borderRadius: "8px",
                      border: "1px solid #e5e7eb",
                      fontSize: "13px",
                    }}
                  />
                </PieChart>
              </ResponsiveContainer>
            ) : (
              <div className="flex items-center justify-center py-16 text-sm text-gray-500">
                No rejection data available
              </div>
            )}
          </div>
        </Card>

        <Card padding="none">
          <div className="border-b border-gray-100 px-6 py-4">
            <h3 className="text-base font-semibold text-gray-900">
              Acceptance by Platform
            </h3>
          </div>
          <div className="p-6">
            {reviewInsights?.acceptance_by_platform &&
            reviewInsights.acceptance_by_platform.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-100 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                      <th className="pb-3 pr-4">Platform</th>
                      <th className="pb-3 pr-4 text-right">Accepted</th>
                      <th className="pb-3 pr-4 text-right">Rejected</th>
                      <th className="pb-3 text-right">Rate</th>
                    </tr>
                  </thead>
                  <tbody>
                    {reviewInsights.acceptance_by_platform.map(
                      (
                        p: {
                          platform: string;
                          accepted: number;
                          rejected: number;
                          rate: number;
                        },
                        i: number
                      ) => (
                        <tr
                          key={i}
                          className="border-b border-gray-50 last:border-0"
                        >
                          <td className="py-2.5 pr-4 font-medium text-gray-900">
                            {p.platform}
                          </td>
                          <td className="py-2.5 pr-4 text-right text-green-600">
                            {p.accepted}
                          </td>
                          <td className="py-2.5 pr-4 text-right text-red-500">
                            {p.rejected}
                          </td>
                          <td className="py-2.5 text-right text-gray-600">
                            {p.rate.toFixed(1)}%
                          </td>
                        </tr>
                      )
                    )}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="flex items-center justify-center py-16 text-sm text-gray-500">
                No acceptance data available
              </div>
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
// F258 — Relevant pipeline card (per-day breakdown by cluster + geography)
// ─────────────────────────────────────────────────────────────────────

// Stable colour palette for cluster + geography series. Distinct from
// PIE_COLORS so a same-page chart pair doesn't reuse the indigo for
// two different concepts. Order is opinion-led: infra first because
// it's the dominant cluster on the dashboard; security next; geography
// gets its own colour family (greens / ambers / pinks) so a quick
// glance can tell "this is cluster" vs "this is geography".
const CLUSTER_COLORS: Record<string, string> = {
  infra:    "#6366f1",
  security: "#3b82f6",
  qa:       "#f59e0b",
  devops:   "#8b5cf6",
  cloud:    "#14b8a6",
  data:     "#ec4899",
};
// Legacy series keys (analytics endpoint still pivots on the old
// ``geography_bucket`` strings during the transition window). New
// vocabulary keys piggy-back so charts produced by either pipeline
// pick up consistent colours. Source of truth:
// ``frontend/src/lib/remote-policy.ts``.
const GEO_COLORS: Record<string, string> = {
  // Legacy
  global_remote: "#10b981",
  usa_only:      "#f97316",
  uae_only:      "#ec4899",
  // New (matches REMOTE_POLICY_COLORS)
  worldwide:           "#10b981",
  country_restricted:  "#f97316",
  region_restricted:   "#f59e0b",
  hybrid:              "#3b82f6",
  onsite:              "#6366f1",
  unknown:             "#94a3b8",
};

const _SERIES_FALLBACK = ["#64748b", "#0ea5e9", "#a855f7", "#facc15", "#22c55e", "#ef4444"];
function _colourFor(map: Record<string, string>, key: string, idx: number): string {
  return map[key] || _SERIES_FALLBACK[idx % _SERIES_FALLBACK.length];
}

/**
 * F258 — daily breakdown of newly-discovered RELEVANT jobs by
 * cluster AND geography. Two stacked-area charts side-by-side so
 * the operator can see "what's flowing in" along both axes from a
 * single card.
 *
 * Both charts share one query / one ``days`` window (driven by the
 * page-level range selector). The stacked-area encoding is the
 * right pick because the operator's mental model is "is the total
 * pipeline growing AND how is the mix shifting" — a stacked
 * representation answers both at once. A side-by-side line chart
 * would answer the second but make total-pipeline trend require a
 * mental sum.
 *
 * Empty days (zero relevant jobs added) still render as zero-height
 * stack columns so the x-axis stays continuous and a multi-day gap
 * in scans is visible as an obvious flat zero stretch.
 */
function RelevantPipelineCard({ days }: { days: number }) {
  const trendQ = useQuery({
    queryKey: ["relevant-jobs-trend", days],
    queryFn: () => getRelevantJobsTrend(days),
    staleTime: 60_000,
  });

  if (trendQ.isLoading) {
    return (
      <Card padding="none">
        <div className="border-b border-gray-100 px-6 py-4">
          <h3 className="text-base font-semibold text-gray-900">Relevant pipeline</h3>
        </div>
        <div className="flex items-center justify-center py-16 text-sm text-gray-500">
          Loading relevant-jobs trend…
        </div>
      </Card>
    );
  }

  if (trendQ.isError || !trendQ.data) {
    return (
      <Card padding="none">
        <div className="border-b border-gray-100 px-6 py-4">
          <h3 className="text-base font-semibold text-gray-900">Relevant pipeline</h3>
        </div>
        <div className="flex items-center justify-center py-16 text-sm text-red-500">
          {(trendQ.error as Error)?.message || "Failed to load trend"}
        </div>
      </Card>
    );
  }

  const { rows, clusters, geographies } = trendQ.data;

  // Recharts wants a flat row shape — flatten the nested ``by_cluster``
  // / ``by_geography`` dicts into top-level keys per series. Two
  // separate chart-data arrays so the charts don't share a y-axis
  // scale (a 5x bigger total in one would dwarf the other).
  const clusterRows = rows.map((r) => ({
    day: r.day,
    total: r.total_relevant,
    ...Object.fromEntries(clusters.map((c) => [c, r.by_cluster[c] ?? 0])),
  }));
  const geoRows = rows.map((r) => ({
    day: r.day,
    total: r.total_relevant,
    ...Object.fromEntries(geographies.map((g) => [g, r.by_geography[g] ?? 0])),
  }));

  // Sum across the window for the small totals strip beneath each chart.
  const clusterTotals = clusters.map((c) => ({
    name: c,
    n: rows.reduce((sum, r) => sum + (r.by_cluster[c] ?? 0), 0),
  }));
  const geoTotals = geographies.map((g) => ({
    name: g,
    n: rows.reduce((sum, r) => sum + (r.by_geography[g] ?? 0), 0),
  }));
  const grandTotal = rows.reduce((s, r) => s + r.total_relevant, 0);

  const tickFormatter = (val: string): string => {
    if (!val) return "";
    const d = new Date(val);
    if (isNaN(d.getTime())) return val;
    return `${d.getMonth() + 1}/${d.getDate()}`;
  };

  return (
    <Card padding="none">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-100 px-6 py-4">
        <div>
          <h3 className="text-base font-semibold text-gray-900">
            Relevant pipeline ({days}d)
          </h3>
          <p className="text-xs text-gray-500">
            New relevant jobs added per day, broken down by cluster and geography.
          </p>
        </div>
        <div className="rounded-md bg-primary-50 px-3 py-1.5 text-sm font-semibold text-primary-700">
          {grandTotal.toLocaleString()} relevant added
        </div>
      </div>
      <div className="grid grid-cols-1 gap-4 p-6 lg:grid-cols-2">
        {/* By cluster */}
        <div>
          <div className="mb-2 flex items-center justify-between">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500">
              By role cluster
            </h4>
            <div className="flex flex-wrap gap-1.5">
              {clusterTotals.map((t, i) => (
                <span
                  key={t.name}
                  className="inline-flex items-center gap-1 rounded bg-gray-50 px-1.5 py-0.5 text-[11px] font-medium text-gray-700"
                  title={`${t.n.toLocaleString()} relevant ${t.name} jobs in ${days}d`}
                >
                  <span
                    className="h-2 w-2 rounded-sm"
                    style={{ backgroundColor: _colourFor(CLUSTER_COLORS, t.name, i) }}
                  />
                  {t.name}: {t.n.toLocaleString()}
                </span>
              ))}
            </div>
          </div>
          <ResponsiveContainer width="100%" height={250}>
            <AreaChart data={clusterRows} margin={{ top: 5, right: 12, bottom: 5, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis
                dataKey="day"
                tick={{ fontSize: 10, fill: "#9ca3af" }}
                axisLine={{ stroke: "#e5e7eb" }}
                tickFormatter={tickFormatter}
              />
              <YAxis
                tick={{ fontSize: 10, fill: "#9ca3af" }}
                axisLine={{ stroke: "#e5e7eb" }}
              />
              <Tooltip
                contentStyle={{ borderRadius: "8px", border: "1px solid #e5e7eb", fontSize: "12px" }}
              />
              <Legend wrapperStyle={{ paddingTop: 4, fontSize: 11 }} />
              {clusters.map((c, i) => (
                <Area
                  key={c}
                  type="monotone"
                  dataKey={c}
                  stackId="cluster"
                  stroke={_colourFor(CLUSTER_COLORS, c, i)}
                  fill={_colourFor(CLUSTER_COLORS, c, i)}
                  fillOpacity={0.6}
                  name={c}
                />
              ))}
            </AreaChart>
          </ResponsiveContainer>
        </div>

        {/* By geography */}
        <div>
          <div className="mb-2 flex items-center justify-between">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500">
              By geography
            </h4>
            <div className="flex flex-wrap gap-1.5">
              {geoTotals.map((t, i) => (
                <span
                  key={t.name}
                  className="inline-flex items-center gap-1 rounded bg-gray-50 px-1.5 py-0.5 text-[11px] font-medium text-gray-700"
                  title={`${t.n.toLocaleString()} relevant jobs in ${t.name.replace(/_/g, " ")} (${days}d)`}
                >
                  <span
                    className="h-2 w-2 rounded-sm"
                    style={{ backgroundColor: _colourFor(GEO_COLORS, t.name, i) }}
                  />
                  {t.name.replace(/_/g, " ")}: {t.n.toLocaleString()}
                </span>
              ))}
            </div>
          </div>
          <ResponsiveContainer width="100%" height={250}>
            <AreaChart data={geoRows} margin={{ top: 5, right: 12, bottom: 5, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis
                dataKey="day"
                tick={{ fontSize: 10, fill: "#9ca3af" }}
                axisLine={{ stroke: "#e5e7eb" }}
                tickFormatter={tickFormatter}
              />
              <YAxis
                tick={{ fontSize: 10, fill: "#9ca3af" }}
                axisLine={{ stroke: "#e5e7eb" }}
              />
              <Tooltip
                contentStyle={{ borderRadius: "8px", border: "1px solid #e5e7eb", fontSize: "12px" }}
              />
              <Legend wrapperStyle={{ paddingTop: 4, fontSize: 11 }} />
              {geographies.map((g, i) => (
                <Area
                  key={g}
                  type="monotone"
                  dataKey={g}
                  stackId="geo"
                  stroke={_colourFor(GEO_COLORS, g, i)}
                  fill={_colourFor(GEO_COLORS, g, i)}
                  fillOpacity={0.6}
                  name={g.replace(/_/g, " ")}
                />
              ))}
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>
    </Card>
  );
}
