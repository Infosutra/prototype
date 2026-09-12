import React, { useEffect, useMemo, useState } from "react";
import { Link } from "wouter";
import { useQueryClient } from "@tanstack/react-query";
import {
  getGetDqaEnumeratorsQueryKey,
  getGetDqaFlagsQueryKey,
  getGetDqaSummaryQueryKey,
  getGetTriangulationViewQueryKey,
  getGetTriangulationViewsQueryKey,
  useGetDqaEnumerators,
  useGetDqaFlags,
  useGetDqaSummary,
  useGetProjects,
  useGetTriangulationView,
  useGetTriangulationViews,
  useRecomputeDqa,
  type TriangulationCell,
  type TriangulationLink,
} from "@workspace/api-client-react";
import { Layout } from "@/components/layout/Layout";
import { Header } from "@/components/layout/Header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { AlertCircle, ArrowLeft, CalendarRange, RefreshCw, ShieldAlert, X } from "lucide-react";
import { useStudy } from "@/components/study/StudyProvider";
import { RequireActiveStudy } from "@/components/study/RequireActiveStudy";
import { DqaChecksPanel, DqaStudyRulesPanel } from "@/pages/dqa/DqaChecksPanel";
import { formatFlagFailureDetails } from "@/pages/dqa/formatFlagFailureDetails";

const TABS = [
  { id: "coverage", label: "Coverage" },
  { id: "flags", label: "DQA flags" },
  { id: "enumerators", label: "Enumerators" },
  { id: "triangulation", label: "Triangulation" },
  { id: "rules", label: "Rules" },
] as const;

type TabId = (typeof TABS)[number]["id"];

type DrillRule = { ruleId: string; title: string; severity: string; count: number };

function isTabId(value: string | null): value is TabId {
  return TABS.some((item) => item.id === value);
}

function FlagMessage({
  message,
  details,
}: {
  message: string;
  details?: Record<string, unknown> | null;
}) {
  const failure = formatFlagFailureDetails(details);
  return (
    <div className="max-w-md space-y-1 text-muted-foreground whitespace-normal break-words">
      <p>{message}</p>
      {failure && <p className="font-mono text-xs text-foreground/80">{failure}</p>}
    </div>
  );
}

function formatDate(value?: string | null) {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function relatedFromFlag(flag: {
  submissionId: string;
  details?: Record<string, unknown> | null;
}): Array<{ submissionId: string; koboId?: string | null }> {
  const raw = flag.details?.relatedSubmissions;
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
    .map((item) => ({
      submissionId: String(item.submissionId || ""),
      koboId: typeof item.koboId === "string" ? item.koboId : null,
    }))
    .filter((item) => item.submissionId && item.submissionId !== flag.submissionId);
}

function FormLink({ link, label }: { link?: TriangulationLink | null; label?: string }) {
  if (!link?.submissionId) return <span className="text-muted-foreground">—</span>;
  const text = label || link.koboId || link.submissionId.slice(0, 8);
  return (
    <Link className="text-primary underline font-mono text-xs" href={`/submissions/${link.submissionId}`}>
      {text}
    </Link>
  );
}

function formatCell(cell: TriangulationCell | undefined) {
  if (!cell || cell.value == null || cell.value === "") return "—";
  if (cell.kind === "bool") return cell.value ? "Yes" : "No";
  if (cell.kind === "list" && Array.isArray(cell.value)) {
    return cell.value.length ? cell.value.join(", ") : "—";
  }
  return String(cell.value);
}

function cellByKey(cells: TriangulationCell[] | undefined, key: string) {
  return cells?.find((c) => c.key === key);
}

export default function DqaDashboard() {
  const initialParams =
    typeof window !== "undefined"
      ? new URLSearchParams(window.location.search)
      : new URLSearchParams();
  const initialTab = initialParams.get("tab");
  const [tab, setTab] = useState<TabId>(isTabId(initialTab) ? initialTab : "coverage");
  const [projectId, setProjectId] = useState<string>(initialParams.get("projectId") || "");
  const [dateFrom, setDateFrom] = useState<string>(initialParams.get("dateFrom") || "");
  const [dateTo, setDateTo] = useState<string>(initialParams.get("dateTo") || "");
  const [severity, setSeverity] = useState<string>("");
  const [drillRuleId, setDrillRuleId] = useState<string | null>(initialParams.get("ruleId"));
  const [mismatchOnly, setMismatchOnly] = useState(true);
  const [triViewId, setTriViewId] = useState("");
  const [rulesIntent, setRulesIntent] = useState<{
    view: "table" | "add" | "edit" | "edit-ai";
    editRuleId: string | null;
  }>({ view: "table", editRuleId: null });

  const syncDateParams = (nextFrom: string, nextTo: string) => {
    if (typeof window === "undefined") return;
    const url = new URL(window.location.href);
    if (nextFrom) url.searchParams.set("dateFrom", nextFrom);
    else url.searchParams.delete("dateFrom");
    if (nextTo) url.searchParams.set("dateTo", nextTo);
    else url.searchParams.delete("dateTo");
    window.history.replaceState({}, "", url);
  };

  const openRule = (ruleId: string | null) => {
    setDrillRuleId(ruleId);
    if (typeof window !== "undefined") {
      const url = new URL(window.location.href);
      if (ruleId) url.searchParams.set("ruleId", ruleId);
      else url.searchParams.delete("ruleId");
      window.history.replaceState({}, "", url);
    }
  };

  const setTabWithUrl = (next: TabId) => {
    setTab(next);
    if (typeof window !== "undefined") {
      const url = new URL(window.location.href);
      if (next === "coverage") url.searchParams.delete("tab");
      else url.searchParams.set("tab", next);
      if (next !== "coverage") openRule(null);
      window.history.replaceState({}, "", url);
    } else if (next !== "coverage") {
      openRule(null);
    }
  };

  const setProjectIdWithUrl = (nextProjectId: string) => {
    setProjectId(nextProjectId);
    setRulesIntent({ view: "table", editRuleId: null });
    openRule(null);
    if (typeof window !== "undefined") {
      const url = new URL(window.location.href);
      if (nextProjectId) url.searchParams.set("projectId", nextProjectId);
      else url.searchParams.delete("projectId");
      window.history.replaceState({}, "", url);
    }
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

  const hasDateFilter = Boolean(dateFrom || dateTo);

  const openFormRules = (
    nextProjectId: string,
    opts?: { editRuleId?: string; add?: boolean },
  ) => {
    setProjectId(nextProjectId);
    setRulesIntent(
      opts?.add
        ? { view: "add", editRuleId: null }
        : opts?.editRuleId
          ? { view: "edit", editRuleId: opts.editRuleId }
          : { view: "table", editRuleId: null },
    );
    openRule(null);
    if (typeof window !== "undefined") {
      const url = new URL(window.location.href);
      url.searchParams.set("projectId", nextProjectId);
      window.history.replaceState({}, "", url);
    }
  };
  const queryClient = useQueryClient();
  const { activeStudy, activeStudyId } = useStudy();
  const projectsQuery = useGetProjects();
  const allProjects = projectsQuery.data ?? [];
  const projects = activeStudyId
    ? allProjects.filter((p) => p.studyId === activeStudyId)
    : allProjects;

  const studyScopedId = projectId ? undefined : activeStudyId || undefined;
  const dateRangeParams = {
    dateFrom: dateFrom || undefined,
    dateTo: dateTo || undefined,
  };
  const summaryParams = {
    projectId: projectId || undefined,
    studyId: studyScopedId,
    ...dateRangeParams,
  };
  const flagsParams = {
    projectId: projectId || undefined,
    studyId: studyScopedId,
    severity: severity || undefined,
    ...dateRangeParams,
  };
  const drillFlagsParams = {
    projectId: projectId || undefined,
    studyId: studyScopedId,
    ruleId: drillRuleId || undefined,
    ...dateRangeParams,
  };
  const enumeratorParams = {
    projectId: projectId || undefined,
    studyId: studyScopedId,
    ...dateRangeParams,
  };

  const viewsQuery = useGetTriangulationViews(
    activeStudyId ? { studyId: activeStudyId } : undefined,
    {
      query: { enabled: tab === "triangulation" && Boolean(activeStudyId) } as never,
    },
  );

  useEffect(() => {
    const views = viewsQuery.data ?? [];
    if (!views.length) return;
    if (!triViewId || !views.some((v) => v.id === triViewId)) {
      setTriViewId(views[0].id);
    }
  }, [viewsQuery.data, triViewId]);

  const summaryQuery = useGetDqaSummary(summaryParams, {
    query: { enabled: Boolean(projectId || studyScopedId) } as never,
  });
  const flagsQuery = useGetDqaFlags(flagsParams, {
    query: { enabled: Boolean(projectId || studyScopedId) } as never,
  });
  const drillFlagsQuery = useGetDqaFlags(drillFlagsParams, {
    query: { enabled: Boolean(drillRuleId) && Boolean(projectId || studyScopedId) } as never,
  });
  const enumeratorsQuery = useGetDqaEnumerators(enumeratorParams, {
    query: { enabled: Boolean(projectId || studyScopedId) } as never,
  });
  const triangulationQuery = useGetTriangulationView(
    triViewId,
    activeStudyId ? { studyId: activeStudyId } : undefined,
    {
      query: {
        enabled: tab === "triangulation" && Boolean(activeStudyId) && Boolean(triViewId),
      } as never,
    },
  );

  const recompute = useRecomputeDqa({
    mutation: {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: getGetDqaSummaryQueryKey() });
        queryClient.invalidateQueries({ queryKey: getGetDqaFlagsQueryKey() });
        queryClient.invalidateQueries({ queryKey: getGetDqaEnumeratorsQueryKey() });
        queryClient.invalidateQueries({
          queryKey: getGetTriangulationViewQueryKey(triViewId),
        });
        queryClient.invalidateQueries({
          queryKey: getGetTriangulationViewsQueryKey(),
        });
      },
    },
  });

  const summary = summaryQuery.data;
  const error =
    summaryQuery.error?.message ||
    flagsQuery.error?.message ||
    drillFlagsQuery.error?.message ||
    enumeratorsQuery.error?.message ||
    triangulationQuery.error?.message ||
    recompute.error?.message;

  const coverageCards = useMemo(
    () => [
      { label: "Submissions", value: summary?.totalSubmissions ?? 0 },
      { label: "Flagged", value: summary?.flaggedSubmissions ?? 0 },
      { label: "Flagged %", value: `${summary?.flaggedPct ?? 0}%` },
      { label: "RED flags", value: summary?.redFlags ?? 0 },
      { label: "AMBER flags", value: summary?.amberFlags ?? 0 },
    ],
    [summary],
  );

  const triangulationRows = useMemo(() => {
    const rows = triangulationQuery.data?.rows ?? [];
    return mismatchOnly ? rows.filter((r) => r.mismatch) : rows;
  }, [triangulationQuery.data?.rows, mismatchOnly]);

  const enumeratorTotals = useMemo(() => {
    const rows = enumeratorsQuery.data ?? [];
    const submissions = rows.reduce((sum, row) => sum + row.submissions, 0);
    const flagged = rows.reduce((sum, row) => sum + row.flagged, 0);
    const redFlags = rows.reduce((sum, row) => sum + row.redFlags, 0);
    const amberFlags = rows.reduce((sum, row) => sum + (row.amberFlags ?? 0), 0);
    return {
      submissions,
      flagged,
      flaggedPct: submissions ? Math.round((flagged / submissions) * 1000) / 10 : 0,
      redFlags,
      amberFlags,
    };
  }, [enumeratorsQuery.data]);

  const drillRule: DrillRule | null = useMemo(() => {
    if (!drillRuleId) return null;
    const known = summary?.byRule.find((rule) => rule.ruleId === drillRuleId);
    return (
      known ?? {
        ruleId: drillRuleId,
        title: "",
        severity: "",
        count: drillFlagsQuery.data?.length ?? 0,
      }
    );
  }, [drillRuleId, summary?.byRule, drillFlagsQuery.data?.length]);

  return (
    <Layout>
      <Header
        title="Data Quality"
        description={
          activeStudy
            ? `${activeStudy.name}${activeStudy.dayNumber != null ? ` · Day ${activeStudy.dayNumber}` : ""}`
            : "Per-form DQA flags, enumerator monitors, and UDISE triangulation"
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
            <Button
              size="sm"
              onClick={() =>
                recompute.mutate({
                  params: projectId
                    ? { projectId }
                    : activeStudyId
                      ? { studyId: activeStudyId }
                      : undefined,
                })
              }
              disabled={recompute.isPending || !activeStudyId}
              className="bg-primary text-primary-foreground"
              aria-label="Recompute DQA"
            >
              <RefreshCw className={`w-4 h-4 sm:mr-2 ${recompute.isPending ? "animate-spin" : ""}`} />
              <span className="hidden sm:inline">Recompute DQA</span>
            </Button>
          </div>
        }
      />

      <RequireActiveStudy
        title="Select a study for DQA"
        description="Data quality checks, enumerator monitors, and triangulation run inside a study workspace."
      >
      <div className="flex-1 overflow-auto p-4 md:p-6 bg-muted/30 space-y-6">
        <div className="flex flex-col sm:flex-row flex-wrap gap-3 items-stretch sm:items-center">
          <select
            className="h-9 w-full sm:w-auto field-control px-3 text-sm"
            value={projectId}
            onChange={(e) => setProjectIdWithUrl(e.target.value)}
          >
            <option value="">All study forms</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.toolCode ? `${p.toolCode} · ` : ""}
                {p.name}
              </option>
            ))}
          </select>
          <div className="flex gap-1 rounded-md border bg-card p-1 overflow-x-auto max-w-full">
            {TABS.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => setTabWithUrl(item.id)}
                className={`px-3 py-1.5 text-sm rounded whitespace-nowrap shrink-0 ${
                  tab === item.id ? "bg-primary text-primary-foreground" : "text-muted-foreground"
                }`}
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>

        {error && (
          <div className="flex items-start gap-3 rounded-md border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <p>{error}</p>
          </div>
        )}

        {recompute.data && (
          <div className="rounded-md border border-green-200 bg-green-50 p-3 text-sm text-green-800">
            Recomputed {recompute.data.submissions} submissions → {recompute.data.flags} flags (
            {recompute.data.flaggedSubmissions} flagged).
          </div>
        )}

        {tab === "coverage" && !drillRule && (
          <>
            <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
              {coverageCards.map((card) => (
                <Card key={card.label}>
                  <CardContent className="p-4">
                    <p className="text-xs text-muted-foreground mb-1">{card.label}</p>
                    <p className="text-2xl font-bold font-mono">{card.value}</p>
                  </CardContent>
                </Card>
              ))}
            </div>
            <Card>
              <CardHeader className="py-4 border-b">
                <CardTitle className="text-sm">Flags by rule</CardTitle>
              </CardHeader>
              <div className="divide-y">
                {(summary?.byRule ?? []).length === 0 ? (
                  <p className="p-4 text-sm text-muted-foreground">No flags yet. Run Recompute DQA.</p>
                ) : (
                  summary?.byRule.map((rule) => (
                    <button
                      key={rule.ruleId}
                      type="button"
                      onClick={() => openRule(rule.ruleId)}
                      className="flex w-full items-center justify-between p-4 text-sm text-left hover:bg-muted/50 transition-colors"
                    >
                      <div>
                        <span className="font-mono text-xs text-muted-foreground mr-2">{rule.ruleId}</span>
                        {rule.title}
                      </div>
                      <div className="flex items-center gap-2">
                        <Badge variant={rule.severity === "red" ? "destructive" : "secondary"}>
                          {rule.severity.toUpperCase()}
                        </Badge>
                        <span className="font-mono underline decoration-dotted">{rule.count}</span>
                      </div>
                    </button>
                  ))
                )}
              </div>
            </Card>
          </>
        )}

        {tab === "coverage" && drillRule && (
          <Card>
            <CardHeader className="py-4 border-b flex flex-row items-center justify-between gap-3">
              <div className="space-y-1">
                <Button variant="ghost" size="sm" className="h-8 px-2 -ml-2" onClick={() => openRule(null)}>
                  <ArrowLeft className="w-4 h-4 mr-1" />
                  Back to rules
                </Button>
                <CardTitle className="text-sm flex items-center gap-2 flex-wrap">
                  <span className="font-mono text-xs text-muted-foreground">{drillRule.ruleId}</span>
                  {drillRule.title}
                  {drillRule.severity && (
                    <Badge variant={drillRule.severity === "red" ? "destructive" : "secondary"}>
                      {drillRule.severity.toUpperCase()}
                    </Badge>
                  )}
                  <span className="font-mono text-muted-foreground">{drillRule.count} forms</span>
                </CardTitle>
              </div>
            </CardHeader>
            <div className="overflow-x-auto">
              {drillFlagsQuery.isLoading ? (
                <p className="p-4 text-sm text-muted-foreground">Loading flagged forms…</p>
              ) : (drillFlagsQuery.data ?? []).length === 0 ? (
                <p className="p-4 text-sm text-muted-foreground">No flagged forms for this rule.</p>
              ) : (
                <table className="w-full min-w-[640px] text-sm">
                  <thead className="border-b bg-muted/40 text-left">
                    <tr>
                      <th className="p-3 font-medium">Form ID</th>
                      <th className="p-3 font-medium">Project</th>
                      <th className="p-3 font-medium">Enumerator</th>
                      <th className="p-3 font-medium">Submitted</th>
                      <th className="p-3 font-medium">Also in</th>
                      <th className="p-3 font-medium">Message</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {drillFlagsQuery.data?.map((flag) => {
                      const related = relatedFromFlag(flag);
                      return (
                      <tr key={flag.id}>
                        <td className="p-3">
                          <Link
                            className="text-primary underline font-mono text-xs"
                            href={`/submissions/${flag.submissionId}`}
                          >
                            {flag.koboId || flag.submissionId.slice(0, 8)}
                          </Link>
                        </td>
                        <td className="p-3">{flag.projectName || "—"}</td>
                        <td className="p-3">{flag.enumerator || "—"}</td>
                        <td className="p-3 whitespace-nowrap">{formatDate(flag.submittedAt)}</td>
                        <td className="p-3">
                          {related.length === 0 ? (
                            <span className="text-muted-foreground">—</span>
                          ) : (
                            <div className="flex flex-col gap-1">
                              {related.map((item) => (
                                <Link
                                  key={item.submissionId}
                                  className="text-primary underline font-mono text-xs"
                                  href={`/submissions/${item.submissionId}`}
                                >
                                  {item.koboId || item.submissionId.slice(0, 8)}
                                </Link>
                              ))}
                            </div>
                          )}
                        </td>
                        <td className="p-3 align-top">
                          <FlagMessage
                            message={flag.message}
                            details={
                              flag.details && typeof flag.details === "object"
                                ? (flag.details as Record<string, unknown>)
                                : null
                            }
                          />
                        </td>
                      </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </div>
          </Card>
        )}

        {tab === "flags" && (
          <Card>
            <CardHeader className="py-4 border-b flex flex-row items-center justify-between">
              <CardTitle className="text-sm flex items-center gap-2">
                <ShieldAlert className="w-4 h-4" /> Flagged records
              </CardTitle>
              <select
                className="field-control h-8 px-2 text-xs"
                value={severity}
                onChange={(e) => setSeverity(e.target.value)}
              >
                <option value="">All severities</option>
                <option value="red">RED</option>
                <option value="amber">AMBER</option>
              </select>
            </CardHeader>
            <div className="divide-y max-h-[70vh] overflow-auto">
              {(flagsQuery.data ?? []).length === 0 ? (
                <p className="p-4 text-sm text-muted-foreground">No flags match the filter.</p>
              ) : (
                flagsQuery.data?.map((flag) => {
                  const related = relatedFromFlag(flag);
                  const sharedValue =
                    flag.details && typeof flag.details === "object" && "value" in flag.details
                      ? String(flag.details.value ?? "")
                      : "";
                  return (
                  <div key={flag.id} className="p-4 text-sm space-y-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <Badge variant={flag.severity === "red" ? "destructive" : "secondary"}>
                        {flag.severity.toUpperCase()}
                      </Badge>
                      <span className="font-mono text-xs">{flag.ruleId}</span>
                      <span className="font-medium">{flag.title}</span>
                    </div>
                    <FlagMessage
                      message={flag.message}
                      details={
                        flag.details && typeof flag.details === "object"
                          ? (flag.details as Record<string, unknown>)
                          : null
                      }
                    />
                    <div className="text-xs text-muted-foreground flex flex-wrap gap-3">
                      <span>{flag.projectName}</span>
                      <span>{flag.enumerator}</span>
                      <span>{formatDate(flag.submittedAt)}</span>
                      <Link className="text-primary underline" href={`/submissions/${flag.submissionId}`}>
                        Submission-{flag.koboId || flag.submissionId}
                      </Link>
                    </div>
                    {related.length > 0 && (
                      <div className="text-xs pt-1">
                        {sharedValue && (
                          <span className="text-muted-foreground mr-2">
                            Value <span className="font-mono">{sharedValue}</span> also in:
                          </span>
                        )}
                        {related.map((item, idx) => (
                          <span key={item.submissionId}>
                            {idx > 0 && <span className="text-muted-foreground">, </span>}
                            <Link
                              className="text-primary underline font-mono"
                              href={`/submissions/${item.submissionId}`}
                            >
                              {item.koboId || item.submissionId.slice(0, 8)}
                            </Link>
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                  );
                })
              )}
            </div>
          </Card>
        )}

        {tab === "enumerators" && (
          <Card>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[520px] text-sm">
                <thead className="border-b bg-muted/40 text-left">
                  <tr>
                    <th className="p-3 font-medium">Enumerator</th>
                    <th className="p-3 font-medium">Submissions</th>
                    <th className="p-3 font-medium">Flagged %</th>
                    <th className="p-3 font-medium">RED</th>
                    <th className="p-3 font-medium">AMBER</th>
                    <th className="p-3 font-medium">Median mins</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {(enumeratorsQuery.data ?? []).map((row) => (
                    <tr key={row.enumerator}>
                      <td className="p-3">{row.enumerator}</td>
                      <td className="p-3 font-mono">{row.submissions}</td>
                      <td className="p-3 font-mono">{row.flaggedPct}%</td>
                      <td className="p-3 font-mono">{row.redFlags}</td>
                      <td className="p-3 font-mono">{row.amberFlags ?? 0}</td>
                      <td className="p-3 font-mono">
                        {row.medianDurationMinutes ?? "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
                {(enumeratorsQuery.data ?? []).length > 0 && (
                  <tfoot>
                    <tr className="border-t bg-muted/30 font-medium">
                      <td className="p-3">
                        Total ({(enumeratorsQuery.data ?? []).length})
                      </td>
                      <td className="p-3 font-mono">{enumeratorTotals.submissions}</td>
                      <td className="p-3 font-mono">{enumeratorTotals.flaggedPct}%</td>
                      <td className="p-3 font-mono">{enumeratorTotals.redFlags}</td>
                      <td className="p-3 font-mono">{enumeratorTotals.amberFlags}</td>
                      <td className="p-3 font-mono text-muted-foreground">—</td>
                    </tr>
                  </tfoot>
                )}
              </table>
            </div>
          </Card>
        )}

        {tab === "rules" &&
          (projectId ? (
            <DqaChecksPanel
              key={`${projectId}:${rulesIntent.view}:${rulesIntent.editRuleId || ""}`}
              projectId={projectId}
              initialView={rulesIntent.view}
              initialEditRuleId={rulesIntent.editRuleId}
            />
          ) : (
            <DqaStudyRulesPanel
              projects={projects.map((p) => ({
                id: p.id,
                name: p.name,
                toolCode: p.toolCode,
              }))}
              onOpenForm={openFormRules}
            />
          ))}

        {tab === "triangulation" && (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-3">
              <select
                className="field-control h-9 px-3 text-sm"
                value={triViewId}
                onChange={(e) => setTriViewId(e.target.value)}
              >
                {(viewsQuery.data ?? []).map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.id} · {v.title}
                  </option>
                ))}
              </select>
              <label className="flex items-center gap-2 text-xs text-muted-foreground">
                <input
                  type="checkbox"
                  checked={mismatchOnly}
                  onChange={(e) => setMismatchOnly(e.target.checked)}
                />
                Mismatches only
              </label>
              {activeStudyId && (
                <Button variant="outline" size="sm" asChild>
                  <Link href={`/studies/${activeStudyId}/triangulation`}>Edit views</Link>
                </Button>
              )}
            </div>

            {triangulationQuery.data?.description && (
              <p className="text-sm text-muted-foreground max-w-3xl">
                {triangulationQuery.data.description}
              </p>
            )}

            {(triangulationQuery.data?.practices?.length ?? 0) > 0 && (
              <Card>
                <CardHeader className="py-3 border-b">
                  <CardTitle className="text-sm">Practice summary (claimed % vs observed %)</CardTitle>
                </CardHeader>
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[640px] text-sm">
                    <thead className="border-b bg-muted/40 text-left">
                      <tr>
                        <th className="p-3">Practice</th>
                        <th className="p-3">Claimed %</th>
                        <th className="p-3">Observed %</th>
                        <th className="p-3">Gap</th>
                        <th className="p-3">Concordance</th>
                        <th className="p-3">n</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y">
                      {triangulationQuery.data?.practices?.map((p) => (
                        <tr key={p.id}>
                          <td className="p-3">{p.label}</td>
                          <td className="p-3 font-mono">{p.claimedPct}%</td>
                          <td className="p-3 font-mono">{p.observedPct}%</td>
                          <td className="p-3 font-mono text-amber-700">{p.gapPct}%</td>
                          <td className="p-3 font-mono">{p.concordancePct}%</td>
                          <td className="p-3 font-mono">{p.n}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
            )}

            <Card>
              <CardHeader className="py-4 border-b flex flex-row items-center justify-between gap-3">
                <CardTitle className="text-sm">
                  {triangulationQuery.data?.title || triViewId} — mismatches:{" "}
                  {triangulationQuery.data?.mismatchCount ?? 0}
                </CardTitle>
              </CardHeader>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[720px] text-sm">
                  <thead className="border-b bg-muted/40 text-left">
                    <tr>
                      {(triangulationQuery.data?.columns ?? []).map((col) => (
                        <th key={col.key} className="p-3">
                          {col.label}
                        </th>
                      ))}
                      <th className="p-3">Forms</th>
                      <th className="p-3">Mismatch</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {triangulationRows.length === 0 ? (
                      <tr>
                        <td
                          colSpan={(triangulationQuery.data?.columns?.length ?? 0) + 2 || 4}
                          className="p-4 text-muted-foreground"
                        >
                          {triangulationQuery.isLoading || viewsQuery.isLoading
                            ? "Loading…"
                            : mismatchOnly
                              ? "No mismatches found."
                              : "No triangulation rows."}
                        </td>
                      </tr>
                    ) : (
                      triangulationRows.map((row) => {
                        const linkEntries = Object.entries(row.links ?? {});
                        return (
                          <tr
                            key={`${row.key}-${linkEntries.map(([, l]) => l?.submissionId).join("-")}`}
                            className={row.mismatch ? "bg-destructive/5" : undefined}
                          >
                            {(triangulationQuery.data?.columns ?? []).map((col) => (
                              <td
                                key={col.key}
                                className={
                                  col.kind === "number" || col.key === "join_key"
                                    ? "p-3 font-mono text-xs"
                                    : col.kind === "list"
                                      ? "p-3 text-xs"
                                      : "p-3"
                                }
                              >
                                {formatCell(cellByKey(row.cells, col.key))}
                              </td>
                            ))}
                            <td className="p-3">
                              <div className="flex flex-col gap-1">
                                {linkEntries.length === 0 ? (
                                  <span className="text-xs text-muted-foreground">—</span>
                                ) : (
                                  linkEntries.map(([role, link]) => (
                                    <span key={role} className="text-xs text-muted-foreground">
                                      {role}: <FormLink link={link} />
                                    </span>
                                  ))
                                )}
                              </div>
                            </td>
                            <td className="p-3">{row.mismatch ? "Yes" : ""}</td>
                          </tr>
                        );
                      })
                    )}
                  </tbody>
                </table>
              </div>
            </Card>
          </div>
        )}
      </div>
      </RequireActiveStudy>
    </Layout>
  );
}
