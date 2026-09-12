import React, { useState } from "react";
import { Link } from "wouter";
import {
  useGetDashboardActivity,
  useGetDashboardSummary,
  useGetDqaByProject,
  useGetSubmissionTrends,
} from "@workspace/api-client-react";
import { Header } from "@/components/layout/Header";
import { Layout } from "@/components/layout/Layout";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Database, Users, Activity, FolderGit2, AlertCircle, ShieldCheck, CalendarRange, X } from "lucide-react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { useStudy } from "@/components/study/StudyProvider";
import { RequireActiveStudy } from "@/components/study/RequireActiveStudy";

function formatRelativeTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const diffMs = Date.now() - date.getTime();
  const minutes = Math.round(diffMs / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min${minutes === 1 ? "" : "s"} ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.round(hours / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

function formatTrendLabel(date: string): string {
  const parsed = new Date(`${date}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return date;
  return parsed.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export default function Dashboard() {
  const initialParams =
    typeof window !== "undefined"
      ? new URLSearchParams(window.location.search)
      : new URLSearchParams();
  const [dateFrom, setDateFrom] = useState(initialParams.get("dateFrom") || "");
  const [dateTo, setDateTo] = useState(initialParams.get("dateTo") || "");

  const syncDateParams = (nextFrom: string, nextTo: string) => {
    if (typeof window === "undefined") return;
    const url = new URL(window.location.href);
    if (nextFrom) url.searchParams.set("dateFrom", nextFrom);
    else url.searchParams.delete("dateFrom");
    if (nextTo) url.searchParams.set("dateTo", nextTo);
    else url.searchParams.delete("dateTo");
    window.history.replaceState({}, "", url);
  };

  const setDateFromWithUrl = (next: string) => {
    setDateFrom(next);
    syncDateParams(next, dateTo);
  };

  const setDateToWithUrl = (next: string) => {
    setDateTo(next);
    syncDateParams(dateFrom, next);
  };

  const clearDateRange = () => {
    setDateFrom("");
    setDateTo("");
    syncDateParams("", "");
  };

  const { activeStudy, activeStudyId } = useStudy();
  const dateRangeParams = {
    dateFrom: dateFrom || undefined,
    dateTo: dateTo || undefined,
  };
  const studyParams = activeStudyId
    ? { studyId: activeStudyId, ...dateRangeParams }
    : undefined;
  const enabled = { query: { enabled: Boolean(activeStudyId) } as never };
  const hasDateFilter = Boolean(dateFrom || dateTo);

  const summaryQuery = useGetDashboardSummary(studyParams, enabled);
  const activityQuery = useGetDashboardActivity(studyParams, enabled);
  const trendsQuery = useGetSubmissionTrends(
    {
      period: "30d",
      studyId: activeStudyId ?? undefined,
      ...dateRangeParams,
    },
    enabled,
  );
  const dqaByProjectQuery = useGetDqaByProject(studyParams, enabled);

  const summary = summaryQuery.data;
  const activityFeed = activityQuery.data ?? [];
  const trendData = (trendsQuery.data ?? []).map((point) => ({
    date: formatTrendLabel(point.date),
    submissions: point.submissions,
  }));
  const topProjects = summary?.topProjects ?? [];
  const projectDqa = dqaByProjectQuery.data ?? [];
  const isLoading =
    summaryQuery.isLoading || activityQuery.isLoading || trendsQuery.isLoading;
  const error =
    summaryQuery.error?.message ||
    activityQuery.error?.message ||
    trendsQuery.error?.message ||
    dqaByProjectQuery.error?.message;

  const dqaTotals = projectDqa.reduce(
    (acc, row) => {
      acc.total += row.totalSubmissions;
      acc.clean += row.cleanSubmissions;
      acc.amber += row.amberSubmissions;
      acc.red += row.redSubmissions;
      acc.amberFlags += row.amberFlags;
      acc.redFlags += row.redFlags;
      return acc;
    },
    { total: 0, clean: 0, amber: 0, red: 0, amberFlags: 0, redFlags: 0 },
  );

  return (
    <Layout>
      <Header
        title="Dashboard"
        description={
          activeStudy
            ? `${activeStudy.name}${
                activeStudy.dayNumber != null ? ` · Day ${activeStudy.dayNumber}` : ""
              }${
                summary?.lastSyncAt ? ` · Last sync ${formatRelativeTime(summary.lastSyncAt)}` : ""
              }`
            : "Select a study to view field operations"
        }
        action={
          <div className="flex items-center gap-2 sm:gap-3">
            <div className="flex items-center gap-1 rounded-lg border border-border/80 bg-muted/30 p-1 shadow-sm">
              <CalendarRange className="ml-1.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
              <label className="flex items-center gap-1.5 pl-0.5">
                <span className="sr-only">Submitted from date</span>
                <input
                  type="date"
                  className="h-7 w-[8.25rem] rounded-md border-0 bg-transparent px-1.5 text-xs text-foreground outline-none focus-visible:ring-1 focus-visible:ring-ring/40 [color-scheme:light]"
                  value={dateFrom}
                  max={dateTo || undefined}
                  onChange={(e) => setDateFromWithUrl(e.target.value)}
                  aria-label="Submitted from date"
                />
              </label>
              <span className="px-0.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground/80">
                to
              </span>
              <label className="flex items-center">
                <span className="sr-only">Submitted to date</span>
                <input
                  type="date"
                  className="h-7 w-[8.25rem] rounded-md border-0 bg-transparent px-1.5 text-xs text-foreground outline-none focus-visible:ring-1 focus-visible:ring-ring/40 [color-scheme:light]"
                  value={dateTo}
                  min={dateFrom || undefined}
                  onChange={(e) => setDateToWithUrl(e.target.value)}
                  aria-label="Submitted to date"
                />
              </label>
              {hasDateFilter ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7 shrink-0 text-muted-foreground hover:text-foreground"
                  onClick={clearDateRange}
                  aria-label="Clear date range"
                  title="All dates"
                >
                  <X className="h-3.5 w-3.5" />
                </Button>
              ) : (
                <span className="w-1.5" aria-hidden />
              )}
            </div>
            <span className="hidden sm:inline-flex items-center rounded-full border border-emerald-500/25 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold tracking-wider text-emerald-700 dark:text-emerald-400">
              LIVE
            </span>
          </div>
        }
      />
      <RequireActiveStudy
        title="Select a study for the dashboard"
        description="Dashboard metrics, activity, and data quality summaries run inside a study workspace."
      >
      <div className="flex-1 overflow-auto p-4 md:p-6">
        {error && (
          <Card className="mb-6 border-destructive/40">
            <CardContent className="flex items-center gap-3 p-4 text-sm text-destructive">
              <AlertCircle className="h-4 w-4 shrink-0" />
              {error}
            </CardContent>
          </Card>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
          <Card>
            <CardContent className="p-4 flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-muted-foreground mb-1">Total Submissions</p>
                <h3 className="text-3xl font-bold data-hero">
                  {isLoading
                    ? "—"
                    : (summary?.totalSubmissions ?? 0).toLocaleString()}
                </h3>
              </div>
              <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center text-primary">
                <Database className="w-5 h-5" />
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-4 flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-muted-foreground mb-1">
                  {hasDateFilter ? "This month (in range)" : "This Month"}
                </p>
                <h3 className="text-3xl font-bold data-hero">
                  {isLoading ? "—" : (summary?.submissionsThisMonth ?? 0).toLocaleString()}
                </h3>
              </div>
              <div className="w-10 h-10 rounded-full bg-secondary/10 flex items-center justify-center text-secondary">
                <Activity className="w-5 h-5" />
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-4 flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-muted-foreground mb-1">Study Forms</p>
                <h3 className="text-3xl font-bold data-hero">
                  {isLoading ? "—" : summary?.totalProjects ?? 0}
                </h3>
              </div>
              <div className="w-10 h-10 rounded-full bg-accent/10 flex items-center justify-center text-accent">
                <FolderGit2 className="w-5 h-5" />
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-4 flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-muted-foreground mb-1">Field Enumerators</p>
                <h3 className="text-3xl font-bold data-hero">
                  {isLoading ? "—" : summary?.activeEnumerators ?? 0}
                </h3>
              </div>
              <div className="w-10 h-10 rounded-full bg-muted flex items-center justify-center text-foreground">
                <Users className="w-5 h-5" />
              </div>
            </CardContent>
          </Card>
        </div>

        <Card className="mb-6">
          <CardHeader className="py-4 border-b flex flex-row items-center justify-between gap-3">
            <div>
              <CardTitle className="text-sm font-semibold flex items-center gap-2">
                <ShieldCheck className="w-4 h-4" />
                Data Quality by Project
              </CardTitle>
              <p className="text-xs text-muted-foreground mt-1">
                Clean / Amber / Red = submissions. Amber flags / Red flags = individual DQA checks
                (one form can have several flags).
              </p>
            </div>
            <Link href="/dqa" className="text-xs text-primary hover:underline shrink-0">
              Open Data Quality
            </Link>
          </CardHeader>
          <div className="overflow-x-auto">
            {dqaByProjectQuery.isLoading ? (
              <p className="p-4 text-sm text-muted-foreground">Loading DQA metrics…</p>
            ) : projectDqa.length === 0 ? (
              <p className="p-4 text-sm text-muted-foreground">
                No forms yet. Sync from Forms, assign them to a study, then recompute DQA.
              </p>
            ) : (
              <table className="w-full min-w-[720px] text-sm">
                <thead className="border-b bg-muted/40 text-left">
                  <tr>
                    <th className="p-3 font-medium">Project</th>
                    <th className="p-3 font-medium">Submissions</th>
                    <th className="p-3 font-medium text-emerald-700">Clean forms</th>
                    <th className="p-3 font-medium text-amber-700">Amber forms</th>
                    <th className="p-3 font-medium text-red-700">Red forms</th>
                    <th className="p-3 font-medium">Flagged %</th>
                    <th className="p-3 font-medium text-amber-700">Amber alerts</th>
                    <th className="p-3 font-medium text-red-700">Red alerts</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {projectDqa.map((row) => (
                    <tr key={row.projectId} className="hover:bg-muted/40">
                      <td className="p-3">
                        <Link
                          href={`/dqa?projectId=${encodeURIComponent(row.projectId)}`}
                          className="font-medium text-primary hover:underline"
                        >
                          {row.projectName}
                        </Link>
                      </td>
                      <td className="p-3 font-mono">{row.totalSubmissions}</td>
                      <td className="p-3 font-mono text-emerald-700">{row.cleanSubmissions}</td>
                      <td className="p-3 font-mono text-amber-700">{row.amberSubmissions}</td>
                      <td className="p-3 font-mono text-red-700">{row.redSubmissions}</td>
                      <td className="p-3 font-mono">{row.flaggedPct}%</td>
                      <td className="p-3 font-mono">{row.amberFlags}</td>
                      <td className="p-3 font-mono">{row.redFlags}</td>
                    </tr>
                  ))}
                  <tr className="bg-muted/30 font-medium">
                    <td className="p-3">All projects</td>
                    <td className="p-3 font-mono">{dqaTotals.total}</td>
                    <td className="p-3 font-mono text-emerald-700">{dqaTotals.clean}</td>
                    <td className="p-3 font-mono text-amber-700">{dqaTotals.amber}</td>
                    <td className="p-3 font-mono text-red-700">{dqaTotals.red}</td>
                    <td className="p-3 font-mono">
                      {dqaTotals.total
                        ? `${(((dqaTotals.amber + dqaTotals.red) / dqaTotals.total) * 100).toFixed(1)}%`
                        : "0%"}
                    </td>
                    <td className="p-3 font-mono">{dqaTotals.amberFlags}</td>
                    <td className="p-3 font-mono">{dqaTotals.redFlags}</td>
                  </tr>
                </tbody>
              </table>
            )}
          </div>
        </Card>

        <Card className="mb-6">
          <CardHeader className="py-4 border-b">
            <CardTitle className="text-sm font-semibold">
              {hasDateFilter
                ? "Submission Volume Trend (selected range)"
                : "Submission Volume Trend (30d)"}
            </CardTitle>
          </CardHeader>
          <CardContent className="p-4 h-[300px]">
            {trendData.length === 0 ? (
              <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                {isLoading
                  ? "Loading trend…"
                  : hasDateFilter
                    ? "No submissions in the selected range"
                    : "No submissions in the last 30 days"}
              </div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={trendData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <defs>
                    <linearGradient id="colorSub" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="hsl(var(--primary))" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="hsl(var(--primary))" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="hsl(var(--border))" />
                  <XAxis
                    dataKey="date"
                    axisLine={false}
                    tickLine={false}
                    tick={{ fontSize: 12, fill: "hsl(var(--muted-foreground))" }}
                    dy={10}
                  />
                  <YAxis
                    axisLine={false}
                    tickLine={false}
                    allowDecimals={false}
                    tick={{ fontSize: 12, fill: "hsl(var(--muted-foreground))" }}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "hsl(var(--card))",
                      borderColor: "hsl(var(--border))",
                      borderRadius: "4px",
                      fontSize: "12px",
                      fontFamily: "var(--app-font-mono)",
                    }}
                    itemStyle={{ color: "hsl(var(--foreground))" }}
                  />
                  <Area
                    type="monotone"
                    dataKey="submissions"
                    stroke="hsl(var(--primary))"
                    strokeWidth={2}
                    fillOpacity={1}
                    fill="url(#colorSub)"
                  />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <Card>
            <CardHeader className="py-4 border-b flex flex-row items-center justify-between">
              <CardTitle className="text-sm font-semibold">Top Forms by Volume</CardTitle>
              <Link href="/forms" className="text-xs text-primary hover:underline">
                View all
              </Link>
            </CardHeader>
            <div className="divide-y border-t-0">
              {topProjects.length === 0 ? (
                <p className="p-4 text-sm text-muted-foreground">
                  {isLoading ? "Loading…" : "No forms yet. Sync from Forms, then assign to a study."}
                </p>
              ) : (
                topProjects.map((project, i) => (
                  <Link key={project.id} href={`/forms/${project.id}`}>
                    <div className="flex items-center justify-between p-4 hover:bg-muted/50 transition-colors">
                      <div className="flex items-center gap-3 min-w-0">
                        <span className="text-xs font-mono text-muted-foreground">
                          {(i + 1).toString().padStart(2, "0")}
                        </span>
                        <span className="text-sm font-medium truncate">{project.name}</span>
                      </div>
                      <span className="text-sm font-mono shrink-0">
                        {project.submissionCount.toLocaleString()}
                      </span>
                    </div>
                  </Link>
                ))
              )}
            </div>
          </Card>

          <Card>
            <CardHeader className="py-4 border-b">
              <CardTitle className="text-sm font-semibold">Recent Activity</CardTitle>
            </CardHeader>
            <div className="p-4 space-y-4">
              {activityFeed.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  {isLoading ? "Loading…" : "No recent submissions"}
                </p>
              ) : (
                activityFeed.map((activity) => (
                  <div key={activity.id} className="flex gap-3">
                    <div
                      className="w-2 h-2 mt-1.5 rounded-full shrink-0 flex-none"
                      style={{
                        backgroundColor:
                          activity.type === "alert"
                            ? "hsl(var(--destructive))"
                            : activity.type === "insight"
                              ? "hsl(var(--accent))"
                              : "hsl(var(--primary))",
                      }}
                    />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-foreground">{activity.message}</p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {formatRelativeTime(activity.timestamp)}
                      </p>
                    </div>
                  </div>
                ))
              )}
            </div>
          </Card>
        </div>
      </div>
      </RequireActiveStudy>
    </Layout>
  );
}
