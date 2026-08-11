import React from "react";
import {
  useGetAnalyticsOverview,
  useGetDqaEnumerators,
  useGetSubmissionTrends,
} from "@workspace/api-client-react";
import { Layout } from "@/components/layout/Layout";
import { Header } from "@/components/layout/Header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { BarChart3 } from "lucide-react";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  AreaChart,
  Area,
  Cell,
} from "recharts";
import { useStudy } from "@/components/study/StudyProvider";
import { RequireActiveStudy } from "@/components/study/RequireActiveStudy";

function formatTrendLabel(date: string): string {
  const parsed = new Date(`${date}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return date;
  return parsed.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export default function Analytics() {
  const { activeStudyId } = useStudy();

  const overviewQuery = useGetAnalyticsOverview(
    activeStudyId ? { studyId: activeStudyId } : undefined,
    { query: { enabled: Boolean(activeStudyId) } as never },
  );
  const trendsQuery = useGetSubmissionTrends(
    { period: "30d", studyId: activeStudyId ?? undefined },
    { query: { enabled: Boolean(activeStudyId) } as never },
  );
  const enumeratorsQuery = useGetDqaEnumerators(
    activeStudyId ? { studyId: activeStudyId } : undefined,
    { query: { enabled: Boolean(activeStudyId) } as never },
  );

  const byProject = (overviewQuery.data?.submissionsByProject ?? []).map((item) => ({
    name: item.label.length > 18 ? `${item.label.slice(0, 16)}…` : item.label,
    fullName: item.label,
    count: item.value,
  }));

  const overTime = (trendsQuery.data ?? []).map((point) => ({
    month: formatTrendLabel(point.date),
    count: point.submissions,
  }));

  const enumerators = enumeratorsQuery.data ?? [];
  const isLoading =
    overviewQuery.isLoading || trendsQuery.isLoading || enumeratorsQuery.isLoading;
  const error =
    overviewQuery.error?.message ||
    trendsQuery.error?.message ||
    enumeratorsQuery.error?.message;

  return (
    <Layout>
      <RequireActiveStudy
        title="Select a study"
        description="Analytics are scoped to the active study workspace."
      >
        <Header
          title="Analytics"
          description="Study-scoped statistical overview of submissions and enumerators"
        />
        <div className="flex-1 overflow-auto p-4 md:p-6 bg-muted/30">
          {error && (
            <div className="mb-4 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
              {error}
            </div>
          )}
          {isLoading && (
            <p className="mb-4 text-sm text-muted-foreground">Loading analytics…</p>
          )}

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
            <Card>
              <CardHeader className="py-4 border-b">
                <CardTitle className="text-sm font-semibold flex items-center">
                  <BarChart3 className="w-4 h-4 mr-2 text-primary" />
                  Submissions by Form
                </CardTitle>
              </CardHeader>
              <CardContent className="p-4 h-72">
                {byProject.length === 0 ? (
                  <p className="text-sm text-muted-foreground h-full flex items-center justify-center">
                    No submission data yet.
                  </p>
                ) : (
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart
                      data={byProject}
                      layout="vertical"
                      margin={{ top: 5, right: 30, left: 20, bottom: 5 }}
                    >
                      <CartesianGrid
                        strokeDasharray="3 3"
                        horizontal={true}
                        vertical={false}
                        stroke="hsl(var(--border))"
                      />
                      <XAxis
                        type="number"
                        axisLine={false}
                        tickLine={false}
                        tick={{
                          fontSize: 12,
                          fill: "hsl(var(--muted-foreground))",
                          fontFamily: "var(--app-font-mono)",
                        }}
                      />
                      <YAxis
                        dataKey="name"
                        type="category"
                        axisLine={false}
                        tickLine={false}
                        width={100}
                        tick={{ fontSize: 12, fill: "hsl(var(--foreground))" }}
                      />
                      <Tooltip
                        cursor={{ fill: "hsl(var(--muted))" }}
                        contentStyle={{
                          backgroundColor: "hsl(var(--card))",
                          borderRadius: "4px",
                          fontSize: "12px",
                          fontFamily: "var(--app-font-mono)",
                        }}
                        formatter={(value: number, _name, props) => [
                          value,
                          props.payload.fullName,
                        ]}
                      />
                      <Bar dataKey="count" radius={[0, 4, 4, 0]}>
                        {byProject.map((_, index) => (
                          <Cell
                            key={`cell-${index}`}
                            fill={`hsl(var(--chart-${(index % 5) + 1}))`}
                          />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="py-4 border-b">
                <CardTitle className="text-sm font-semibold flex items-center">
                  <BarChart3 className="w-4 h-4 mr-2 text-secondary" />
                  Submission Velocity (30d)
                </CardTitle>
              </CardHeader>
              <CardContent className="p-4 h-72">
                {overTime.length === 0 ? (
                  <p className="text-sm text-muted-foreground h-full flex items-center justify-center">
                    No trend data yet.
                  </p>
                ) : (
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart
                      data={overTime}
                      margin={{ top: 10, right: 10, left: -20, bottom: 0 }}
                    >
                      <defs>
                        <linearGradient id="colorCount" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="hsl(var(--secondary))" stopOpacity={0.3} />
                          <stop offset="95%" stopColor="hsl(var(--secondary))" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid
                        strokeDasharray="3 3"
                        vertical={false}
                        stroke="hsl(var(--border))"
                      />
                      <XAxis
                        dataKey="month"
                        axisLine={false}
                        tickLine={false}
                        tick={{ fontSize: 12, fill: "hsl(var(--muted-foreground))" }}
                      />
                      <YAxis
                        axisLine={false}
                        tickLine={false}
                        tick={{
                          fontSize: 12,
                          fill: "hsl(var(--muted-foreground))",
                          fontFamily: "var(--app-font-mono)",
                        }}
                      />
                      <Tooltip
                        contentStyle={{
                          backgroundColor: "hsl(var(--card))",
                          borderColor: "hsl(var(--border))",
                          borderRadius: "4px",
                          fontSize: "12px",
                          fontFamily: "var(--app-font-mono)",
                        }}
                      />
                      <Area
                        type="monotone"
                        dataKey="count"
                        stroke="hsl(var(--secondary))"
                        strokeWidth={2}
                        fillOpacity={1}
                        fill="url(#colorCount)"
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                )}
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader className="py-4 border-b">
              <CardTitle className="text-sm font-semibold">Enumerator performance</CardTitle>
            </CardHeader>
            <div className="overflow-x-auto">
              <table className="w-full text-sm text-left">
                <thead className="bg-muted text-muted-foreground text-xs uppercase">
                  <tr>
                    <th className="px-6 py-3 font-medium">Enumerator</th>
                    <th className="px-6 py-3 font-medium text-right">Submissions</th>
                    <th className="px-6 py-3 font-medium text-right">Flagged</th>
                    <th className="px-6 py-3 font-medium text-right">Flagged %</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border bg-card">
                  {enumerators.map((stat) => (
                    <tr key={stat.enumerator} className="hover:bg-muted/50 transition-colors">
                      <td className="px-6 py-4 font-medium">{stat.enumerator}</td>
                      <td className="px-6 py-4 text-right font-mono">{stat.submissions}</td>
                      <td className="px-6 py-4 text-right font-mono">{stat.flagged}</td>
                      <td className="px-6 py-4 text-right">
                        <span
                          className={`px-2 py-1 rounded text-xs font-mono font-medium ${
                            stat.flaggedPct > 5
                              ? "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400"
                              : "text-muted-foreground"
                          }`}
                        >
                          {stat.flaggedPct.toFixed(1)}%
                        </span>
                      </td>
                    </tr>
                  ))}
                  {!isLoading && enumerators.length === 0 && (
                    <tr>
                      <td colSpan={4} className="px-6 py-8 text-center text-muted-foreground">
                        No enumerator stats yet.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </Card>
        </div>
      </RequireActiveStudy>
    </Layout>
  );
}
