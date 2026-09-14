import React, { useEffect, useMemo } from "react";
import { useSearchParams } from "wouter";
import { useGetProjects } from "@workspace/api-client-react";
import { Layout, useMobileNav } from "@/components/layout/Layout";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { CalendarRange, Menu, X } from "lucide-react";
import { useStudy } from "@/components/study/StudyProvider";
import { RequireActiveStudy } from "@/components/study/RequireActiveStudy";
import { SubmissionsGrid } from "@/pages/projects/SubmissionsGrid";

function shortFormName(name?: string): string {
  if (!name) return "Form";
  const clause = name.split(/[—(]/)[0]?.trim();
  if (clause && clause.length > 0 && clause.length < name.length) {
    return clause.length > 48 ? `${clause.slice(0, 45)}…` : clause;
  }
  return name.length > 48 ? `${name.slice(0, 45)}…` : name;
}

function DataExplorerChrome({
  studyName,
  projects,
  selectedProjectId,
  onProjectChange,
  projectsLoading,
  dateFrom,
  dateTo,
  onDateFromChange,
  onDateToChange,
  onClearDateRange,
}: {
  studyName?: string;
  projects: { id: string; name: string; toolCode?: string | null }[];
  selectedProjectId: string;
  onProjectChange: (id: string) => void;
  projectsLoading: boolean;
  dateFrom: string;
  dateTo: string;
  onDateFromChange: (value: string) => void;
  onDateToChange: (value: string) => void;
  onClearDateRange: () => void;
}) {
  const { setOpen } = useMobileNav();
  const hasDateFilter = Boolean(dateFrom || dateTo);

  return (
    <header className="min-h-14 shrink-0 flex items-center justify-between gap-3 px-4 md:px-6 py-2 bg-card border-b border-border z-10">
      <div className="flex items-center gap-2 min-w-0 flex-1">
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="md:hidden shrink-0 -ml-1"
          onClick={() => setOpen(true)}
          aria-label="Open navigation"
        >
          <Menu className="h-5 w-5" />
        </Button>
        <div className="flex flex-wrap items-center gap-2 min-w-0">
          <h1
            className="text-base md:text-lg font-semibold tracking-tight text-foreground truncate max-w-[min(100%,20rem)]"
            title={studyName || undefined}
          >
            {studyName || "Study"}
          </h1>
          <Select
            value={selectedProjectId || undefined}
            onValueChange={onProjectChange}
            disabled={projectsLoading || projects.length === 0}
          >
            <SelectTrigger className="h-8 w-[min(100%,20rem)] text-xs" aria-label="Form">
              <SelectValue placeholder="Select a form" />
            </SelectTrigger>
            <SelectContent>
              {projects.map((project) => (
                <SelectItem key={project.id} value={project.id}>
                  {project.toolCode ? `${project.toolCode} · ` : ""}
                  {shortFormName(project.name)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="flex items-center gap-2 sm:gap-3 shrink-0">
        <div className="flex items-center gap-1 rounded-lg border border-border/80 bg-muted/30 p-1 shadow-sm">
          <CalendarRange
            className="ml-1.5 h-3.5 w-3.5 shrink-0 text-muted-foreground"
            aria-hidden
          />
          <label className="flex items-center gap-1.5 pl-0.5">
            <span className="sr-only">Submitted from date</span>
            <input
              type="date"
              className="h-7 w-[8.25rem] rounded-md border-0 bg-transparent px-1.5 text-xs text-foreground outline-none focus-visible:ring-1 focus-visible:ring-ring/40 [color-scheme:light]"
              value={dateFrom}
              max={dateTo || undefined}
              onChange={(e) => onDateFromChange(e.target.value)}
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
              onChange={(e) => onDateToChange(e.target.value)}
              aria-label="Submitted to date"
            />
          </label>
          {hasDateFilter ? (
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-7 w-7 shrink-0 text-muted-foreground hover:text-foreground"
              onClick={onClearDateRange}
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
    </header>
  );
}

export default function DataExplorer() {
  const { activeStudy, activeStudyId } = useStudy();
  const [searchParams, setSearchParams] = useSearchParams();
  const projectIdFromUrl = searchParams.get("projectId") || "";
  const dateFrom = searchParams.get("dateFrom") || "";
  const dateTo = searchParams.get("dateTo") || "";

  const projectsQuery = useGetProjects(
    activeStudyId ? { studyId: activeStudyId } : undefined,
    { query: { enabled: Boolean(activeStudyId) } as never },
  );
  const projects = projectsQuery.data ?? [];

  const selectedProjectId = useMemo(() => {
    if (projectIdFromUrl && projects.some((project) => project.id === projectIdFromUrl)) {
      return projectIdFromUrl;
    }
    if (projectIdFromUrl && projectsQuery.isLoading) return projectIdFromUrl;
    return projects[0]?.id ?? "";
  }, [projectIdFromUrl, projects, projectsQuery.isLoading]);

  useEffect(() => {
    if (!activeStudyId || projectsQuery.isLoading || projects.length === 0) return;
    if (projectIdFromUrl && projects.some((project) => project.id === projectIdFromUrl)) {
      return;
    }
    const fallback = projects[0]?.id;
    if (!fallback) return;
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.set("projectId", fallback);
        return next;
      },
      { replace: true },
    );
  }, [
    activeStudyId,
    projectIdFromUrl,
    projects,
    projectsQuery.isLoading,
    setSearchParams,
  ]);

  const setProjectId = (id: string) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      if (id) next.set("projectId", id);
      else next.delete("projectId");
      return next;
    });
  };

  const syncDateParams = (nextFrom: string, nextTo: string) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      if (nextFrom) next.set("dateFrom", nextFrom);
      else next.delete("dateFrom");
      if (nextTo) next.set("dateTo", nextTo);
      else next.delete("dateTo");
      return next;
    });
  };

  return (
    <Layout>
      <RequireActiveStudy
        title="Select a study"
        description="Data Explorer shows form submissions for the active study workspace."
      >
        <DataExplorerChrome
          studyName={activeStudy?.name}
          projects={projects}
          selectedProjectId={selectedProjectId}
          onProjectChange={setProjectId}
          projectsLoading={projectsQuery.isLoading}
          dateFrom={dateFrom}
          dateTo={dateTo}
          onDateFromChange={(value) => syncDateParams(value, dateTo)}
          onDateToChange={(value) => syncDateParams(dateFrom, value)}
          onClearDateRange={() => syncDateParams("", "")}
        />

        <div className="flex-1 min-h-0 overflow-hidden bg-muted/30 p-3 md:p-4 flex flex-col">
          {projectsQuery.isLoading ? (
            <p className="p-6 text-sm text-muted-foreground">Loading forms…</p>
          ) : projects.length === 0 ? (
            <div className="flex flex-1 items-center justify-center rounded-lg border bg-card p-8 text-center">
              <div className="max-w-md space-y-2">
                <p className="font-medium">No forms in this study</p>
                <p className="text-sm text-muted-foreground">
                  Sync from Kobo and assign forms on Studies, then open Data Explorer
                  again.
                </p>
              </div>
            </div>
          ) : selectedProjectId ? (
            <SubmissionsGrid key={selectedProjectId} projectId={selectedProjectId} />
          ) : (
            <p className="p-6 text-sm text-muted-foreground">Select a form to explore.</p>
          )}
        </div>
      </RequireActiveStudy>
    </Layout>
  );
}
