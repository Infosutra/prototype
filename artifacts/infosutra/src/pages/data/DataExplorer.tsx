import React, { useEffect, useMemo } from "react";
import { Link, useSearchParams } from "wouter";
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
import { Menu, Settings2 } from "lucide-react";
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
  formName,
  formTitle,
  projectId,
  projects,
  selectedProjectId,
  onProjectChange,
  projectsLoading,
}: {
  studyName?: string;
  formName?: string;
  formTitle?: string;
  projectId: string;
  projects: { id: string; name: string; toolCode?: string | null }[];
  selectedProjectId: string;
  onProjectChange: (id: string) => void;
  projectsLoading: boolean;
}) {
  const { setOpen } = useMobileNav();
  const crumb = [studyName, shortFormName(formName)].filter(Boolean).join(" / ");

  return (
    <header className="min-h-14 shrink-0 flex items-center justify-between gap-3 px-4 md:px-6 py-2 bg-card border-b border-border z-10">
      <div className="flex items-start gap-2 min-w-0 flex-1">
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="md:hidden shrink-0 -ml-1 mt-0.5"
          onClick={() => setOpen(true)}
          aria-label="Open navigation"
        >
          <Menu className="h-5 w-5" />
        </Button>
        <div className="flex flex-col min-w-0 gap-1">
          <p
            className="text-[11px] text-muted-foreground truncate"
            title={formTitle ? `${studyName ?? ""} / ${formTitle}` : undefined}
          >
            {crumb || "Study / Form"}
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-base md:text-lg font-semibold tracking-tight text-foreground">
              Data Explorer
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
      </div>
      {projectId ? (
        <Link href={`/forms/${projectId}`}>
          <Button variant="outline" size="sm">
            <Settings2 className="mr-2 h-4 w-4" />
            <span className="hidden sm:inline">Form settings</span>
            <span className="sm:hidden">Settings</span>
          </Button>
        </Link>
      ) : null}
    </header>
  );
}

export default function DataExplorer() {
  const { activeStudy, activeStudyId } = useStudy();
  const [searchParams, setSearchParams] = useSearchParams();
  const projectIdFromUrl = searchParams.get("projectId") || "";

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

  const selectedProject = projects.find((project) => project.id === selectedProjectId);

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

  return (
    <Layout>
      <RequireActiveStudy
        title="Select a study"
        description="Data Explorer shows form submissions for the active study workspace."
      >
        <DataExplorerChrome
          studyName={activeStudy?.name}
          formName={selectedProject?.name}
          formTitle={selectedProject?.name}
          projectId={selectedProjectId}
          projects={projects}
          selectedProjectId={selectedProjectId}
          onProjectChange={setProjectId}
          projectsLoading={projectsQuery.isLoading}
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
