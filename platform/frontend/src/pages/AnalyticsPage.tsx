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
