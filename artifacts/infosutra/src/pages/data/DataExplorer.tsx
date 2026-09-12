import React, { useMemo, useState } from "react";
import { Link } from "wouter";
import { useGetProjects, useGetSubmissions } from "@workspace/api-client-react";
import { Layout } from "@/components/layout/Layout";
import { Header } from "@/components/layout/Header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Search, ChevronDown, ChevronRight, FileJson, CalendarRange, X } from "lucide-react";
import { useStudy } from "@/components/study/StudyProvider";
import { RequireActiveStudy } from "@/components/study/RequireActiveStudy";

const PAGE_SIZE = 25;

export default function DataExplorer() {
  const { activeStudyId } = useStudy();
  const [expandedRow, setExpandedRow] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [projectFilter, setProjectFilter] = useState<string>("all");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [page, setPage] = useState(1);

  const projectsQuery = useGetProjects(
    activeStudyId ? { studyId: activeStudyId } : undefined,
    { query: { enabled: Boolean(activeStudyId) } as never },
  );
  const projects = projectsQuery.data ?? [];

  const submissionsQuery = useGetSubmissions(
    {
      studyId: activeStudyId ?? undefined,
      projectId: projectFilter !== "all" ? projectFilter : undefined,
      status: statusFilter !== "all" ? statusFilter : undefined,
      dateFrom: dateFrom || undefined,
      dateTo: dateTo || undefined,
      page,
      limit: PAGE_SIZE,
    },
    { query: { enabled: Boolean(activeStudyId) } as never },
  );

  const rows = submissionsQuery.data?.data ?? [];
  const total = submissionsQuery.data?.total ?? 0;
  const totalPages = submissionsQuery.data?.totalPages ?? 0;
  const hasDateFilter = Boolean(dateFrom || dateTo);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter(
      (row) =>
        row.id.toLowerCase().includes(q) ||
        row.displayId?.toLowerCase().includes(q) ||
        (row.enumerator || "").toLowerCase().includes(q) ||
        (row.projectName || "").toLowerCase().includes(q) ||
        (row.location || "").toLowerCase().includes(q),
    );
  }, [rows, search]);

  const toggleRow = (id: string) => {
    setExpandedRow(expandedRow === id ? null : id);
  };

  const from = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
  const to = Math.min(page * PAGE_SIZE, total);

  return (
    <Layout>
      <RequireActiveStudy
        title="Select a study"
        description="Data Explorer shows submissions for the active study workspace."
      >
        <Header
          title="Data Explorer"
          description="Inspect and filter raw submission data for this study"
        />
        <div className="flex flex-col flex-1 overflow-hidden bg-muted/20">
          <div className="p-4 bg-card border-b flex flex-wrap gap-3 items-center z-0">
            <div className="relative flex-1 min-w-[200px] max-w-sm">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
              <Input
                placeholder="Search submissions by ID, enumerator..."
                className="pl-9 h-9"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>

            <Select
              value={projectFilter}
              onValueChange={(value) => {
                setProjectFilter(value);
                setPage(1);
              }}
            >
              <SelectTrigger className="w-[200px] h-9">
                <SelectValue placeholder="All Projects" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All forms</SelectItem>
                {projects.map((project) => (
                  <SelectItem key={project.id} value={project.id}>
                    {project.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Select
              value={statusFilter}
              onValueChange={(value) => {
                setStatusFilter(value);
                setPage(1);
              }}
            >
              <SelectTrigger className="w-[150px] h-9">
                <SelectValue placeholder="Status" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Statuses</SelectItem>
                <SelectItem value="validated">Validated</SelectItem>
                <SelectItem value="pending">Pending</SelectItem>
                <SelectItem value="flagged">Flagged</SelectItem>
              </SelectContent>
            </Select>

            <div className="flex items-center gap-1 rounded-lg border border-border/80 bg-muted/30 p-1 shadow-sm">
              <CalendarRange className="ml-1.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
              <label className="flex items-center pl-0.5">
                <span className="sr-only">Submitted from date</span>
                <input
                  type="date"
                  className="h-7 w-[8.25rem] rounded-md border-0 bg-transparent px-1.5 text-xs text-foreground outline-none focus-visible:ring-1 focus-visible:ring-ring/40 [color-scheme:light]"
                  value={dateFrom}
                  max={dateTo || undefined}
                  onChange={(e) => {
                    setDateFrom(e.target.value);
                    setPage(1);
                  }}
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
                  onChange={(e) => {
                    setDateTo(e.target.value);
                    setPage(1);
                  }}
                  aria-label="Submitted to date"
                />
              </label>
              {hasDateFilter ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7 shrink-0 text-muted-foreground hover:text-foreground"
                  onClick={() => {
                    setDateFrom("");
                    setDateTo("");
                    setPage(1);
                  }}
                  aria-label="Clear date range"
                  title="All dates"
                >
                  <X className="h-3.5 w-3.5" />
                </Button>
              ) : (
                <span className="w-1.5" aria-hidden />
              )}
            </div>
          </div>

          <div className="flex-1 overflow-auto">
            {submissionsQuery.isLoading ? (
              <p className="p-6 text-sm text-muted-foreground">Loading submissions…</p>
            ) : submissionsQuery.error ? (
              <p className="p-6 text-sm text-destructive">{submissionsQuery.error.message}</p>
            ) : (
              <table className="w-full min-w-[640px] text-sm text-left border-collapse">
                <thead className="bg-muted/50 text-muted-foreground text-xs uppercase sticky top-0 backdrop-blur-sm z-10 shadow-sm">
                  <tr>
                    <th className="px-4 py-3 font-medium w-10"></th>
                    <th className="px-4 py-3 font-medium">ID</th>
                    <th className="px-4 py-3 font-medium">Project</th>
                    <th className="px-4 py-3 font-medium">Date</th>
                    <th className="px-4 py-3 font-medium">Enumerator</th>
                    <th className="px-4 py-3 font-medium">Location</th>
                    <th className="px-4 py-3 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border bg-card">
                  {filtered.map((row) => (
                    <React.Fragment key={row.id}>
                      <tr
                        className="hover:bg-muted/30 transition-colors cursor-pointer group"
                        onClick={() => toggleRow(row.id)}
                      >
                        <td className="px-4 py-3 text-muted-foreground">
                          {expandedRow === row.id ? (
                            <ChevronDown className="w-4 h-4" />
                          ) : (
                            <ChevronRight className="w-4 h-4" />
                          )}
                        </td>
                        <td className="px-4 py-3 font-mono text-xs text-primary">
                          <Link
                            href={`/submissions/${encodeURIComponent(row.id)}`}
                            onClick={(e) => e.stopPropagation()}
                            className="hover:underline"
                          >
                            {row.displayId || row.id}
                          </Link>
                        </td>
                        <td className="px-4 py-3 truncate max-w-[200px]" title={row.projectName}>
                          {row.projectName}
                        </td>
                        <td className="px-4 py-3 text-muted-foreground text-xs">
                          {new Date(row.submittedAt).toLocaleString()}
                        </td>
                        <td className="px-4 py-3">{row.enumerator || "—"}</td>
                        <td className="px-4 py-3">{row.location || "—"}</td>
                        <td className="px-4 py-3">
                          <Badge
                            variant="outline"
                            className={
                              row.status === "validated"
                                ? "bg-green-100 text-green-800 border-green-200 dark:bg-green-900/30 dark:text-green-400 dark:border-green-800"
                                : row.status === "pending"
                                  ? "bg-blue-100 text-blue-800 border-blue-200 dark:bg-blue-900/30 dark:text-blue-400 dark:border-blue-800"
                                  : "bg-red-100 text-red-800 border-red-200 dark:bg-red-900/30 dark:text-red-400 dark:border-red-800"
                            }
                          >
                            {row.status}
                          </Badge>
                        </td>
                      </tr>
                      {expandedRow === row.id && (
                        <tr className="bg-muted/20 border-b">
                          <td colSpan={7} className="p-0">
                            <div className="p-4 m-4 border rounded-md bg-card shadow-inner flex flex-col">
                              <div className="flex items-center text-xs font-semibold text-muted-foreground mb-2 uppercase tracking-wider">
                                <FileJson className="w-4 h-4 mr-2" />
                                Raw Submission Payload
                              </div>
                              <pre className="font-mono text-xs overflow-x-auto p-4 bg-muted/50 rounded text-foreground">
                                {JSON.stringify(row.data ?? {}, null, 2)}
                              </pre>
                            </div>
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  ))}
                  {filtered.length === 0 && (
                    <tr>
                      <td colSpan={7} className="px-4 py-8 text-center text-muted-foreground">
                        No submissions match these filters.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            )}
          </div>

          <div className="p-3 border-t bg-card flex items-center justify-between text-xs text-muted-foreground z-0">
            <span>
              Showing {from}-{to} of {total.toLocaleString()} submissions
            </span>
            <div className="flex gap-1">
              <Button
                variant="outline"
                size="sm"
                disabled={page <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
              >
                Previous
              </Button>
              <Button variant="outline" size="sm" className="bg-muted" disabled>
                {page}
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={page >= totalPages}
                onClick={() => setPage((p) => p + 1)}
              >
                Next
              </Button>
            </div>
          </div>
        </div>
      </RequireActiveStudy>
    </Layout>
  );
}
