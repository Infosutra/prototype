import React, { useState } from "react";
import { Link } from "wouter";
import { useQueryClient } from "@tanstack/react-query";
import {
  getGetProjectQueryKey,
  getGetSubmissionsQueryKey,
  useGetProject,
  useGetSubmissions,
  useUpdateProject,
} from "@workspace/api-client-react";
import { Layout } from "@/components/layout/Layout";
import { Header } from "@/components/layout/Header";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { RefreshCw, Eye, Table, AlertCircle, ChevronDown, ChevronLeft, ChevronRight } from "lucide-react";
import { useFormRouteId } from "@/lib/use-form-route-id";
import { useRunProjectSync } from "@/components/study/useActiveStudySync";

const PAGE_SIZE = 25;

const DQA_FILTERS = [
  { id: "all", label: "All" },
  { id: "flagged", label: "Flagged" },
  { id: "red", label: "RED" },
  { id: "amber", label: "AMBER" },
  { id: "clean", label: "Clean" },
] as const;

function formatDate(value: string | null | undefined): string {
  return value ? new Date(value).toLocaleString() : "Not available";
}

function DqaBadge({
  severity,
  red,
  amber,
}: {
  severity?: string | null;
  red?: number;
  amber?: number;
}) {
  if (severity === "red") {
    return (
      <Badge variant="destructive" className="uppercase text-[10px]">
        RED{red ? ` · ${red}` : ""}
      </Badge>
    );
  }
  if (severity === "amber") {
    return (
      <Badge variant="secondary" className="uppercase text-[10px] bg-amber-100 text-amber-900 dark:bg-amber-950/60 dark:text-amber-200">
        AMBER{amber ? ` · ${amber}` : ""}
      </Badge>
    );
  }
  return (
    <Badge variant="outline" className="uppercase text-[10px] text-muted-foreground">
      Clean
    </Badge>
  );
}

export default function ProjectDetail() {
  const projectId = useFormRouteId();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [dqaFilter, setDqaFilter] = useState<string>("all");
  const projectQuery = useGetProject(projectId);
  const submissionsQuery = useGetSubmissions({
    projectId,
    page,
    limit: PAGE_SIZE,
    dqa: dqaFilter === "all" ? undefined : dqaFilter,
  });
  const syncProject = useRunProjectSync();
  const updateProject = useUpdateProject({
    mutation: {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: getGetProjectQueryKey(projectId) });
        queryClient.invalidateQueries({ queryKey: ["getSubmission"] });
      },
    },
  });
  const project = projectQuery.data;
  const [detailsOpen, setDetailsOpen] = useState(false);
  const result = submissionsQuery.data;
  const total = result?.total ?? 0;
  const totalPages = Math.max(result?.totalPages ?? 1, 1);
  const from = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
  const to = Math.min(page * PAGE_SIZE, total);

  const onSync = () => {
    void syncProject.run(projectId, projectQuery.data?.studyId).then(() => {
      void queryClient.invalidateQueries({ queryKey: getGetProjectQueryKey(projectId) });
      void queryClient.invalidateQueries({ queryKey: getGetSubmissionsQueryKey() });
    });
  };

  if (projectQuery.isLoading) {
    return <Layout><div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">Loading project…</div></Layout>;
  }

  if (!project || projectQuery.error) {
    return (
      <Layout>
        <div className="flex flex-1 items-center justify-center p-6">
          <Card className="max-w-lg p-6 text-center">
            <AlertCircle className="mx-auto mb-3 h-6 w-6 text-destructive" />
            <h2 className="font-semibold">Project unavailable</h2>
            <p className="mt-2 text-sm text-muted-foreground">{projectQuery.error?.message ?? "This Kobo project was not found."}</p>
          </Card>
        </div>
      </Layout>
    );
  }
  
  return (
    <Layout>
      <Header 
        title={project.name} 
        description={`Last synced: ${formatDate(project.lastSyncAt)}`}
        action={
          <div className="flex gap-2">
            <Button size="sm" variant="outline" asChild>
              <Link href={`/dqa?projectId=${projectId}&tab=rules`}>DQA rules</Link>
            </Button>
            <Button size="sm" disabled={syncProject.isPending} onClick={onSync} className="bg-primary text-primary-foreground">
              <RefreshCw className={`w-4 h-4 mr-2 ${syncProject.isPending ? "animate-spin" : ""}`} />
              {syncProject.isPending ? "Syncing…" : "Sync Data"}
            </Button>
          </div>
        }
      />
      <div className="flex-1 overflow-auto p-4 md:p-6 bg-muted/30">
        
        <Collapsible open={detailsOpen} onOpenChange={setDetailsOpen} className="mb-6">
          <CollapsibleTrigger asChild>
            <Button variant="outline" size="sm" className="w-full sm:w-auto justify-between gap-2">
              Form details
              <ChevronDown
                className={`h-4 w-4 shrink-0 transition-transform ${detailsOpen ? "rotate-180" : ""}`}
              />
            </Button>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <div className="grid grid-cols-1 gap-4 mt-3 sm:grid-cols-2 xl:grid-cols-4">
              {[
                ["Status", project.status],
                ["Questions", project.questionCount.toLocaleString()],
                ["Owner", project.owner ?? "Not available"],
                ["Last edited by", project.lastEditedBy ?? "Not available"],
                ["Last modified", formatDate(project.lastModifiedAt)],
                ["Latest submission", formatDate(project.lastSubmissionAt)],
                ["Sector", project.sector ?? "Not specified"],
                ["Country", project.country ?? "Not specified"],
                [
                  "Current version",
                  project.currentVersionNumber != null
                    ? `Version ${project.currentVersionNumber}`
                    : "Not available",
                ],
                [
                  "Deployed version",
                  project.deployedVersionNumber != null
                    ? `Version ${project.deployedVersionNumber}`
                    : "Not deployed",
                ],
                ["Submissions", project.submissionCount.toLocaleString()],
              ].map(([label, value]) => (
                <Card key={label}>
                  <CardContent className="p-4 min-h-20">
                    <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">{label}</p>
                    <p className={`mt-2 font-semibold ${label === "Status" ? "capitalize" : ""}`}>{value}</p>
                  </CardContent>
                </Card>
              ))}
            </div>
          </CollapsibleContent>
        </Collapsible>

        <Card className="mb-6">
          <CardContent className="p-4 text-sm">
            <div className="flex flex-wrap items-center gap-3">
              <Label htmlFor="label-language" className="shrink-0">
                Preview language
              </Label>
              <Select
                value={project.labelLanguage}
                disabled={updateProject.isPending}
                onValueChange={(value) => {
                  updateProject.mutate({
                    projectId,
                    data: { labelLanguage: value },
                  });
                }}
              >
                <SelectTrigger id="label-language" className="w-[220px]">
                  <SelectValue placeholder="Select language" />
                </SelectTrigger>
                <SelectContent>
                  {project.availableLabelLanguages.map((language) => (
                    <SelectItem key={language} value={language}>
                      {language}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </CardContent>
        </Card>

        {/* Submissions */}
        <Card>
          <CardHeader className="py-4 border-b flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <CardTitle className="text-sm font-semibold">Submissions</CardTitle>
              <p className="text-xs text-muted-foreground mt-1">
                {total === 0 ? "No matching submissions" : `${from}–${to} of ${total.toLocaleString()}`}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Select
                value={dqaFilter}
                onValueChange={(value) => {
                  setDqaFilter(value);
                  setPage(1);
                }}
              >
                <SelectTrigger className="h-8 w-[150px]" aria-label="DQA flag filter">
                  <SelectValue placeholder="DQA flags" />
                </SelectTrigger>
                <SelectContent>
                  {DQA_FILTERS.map((item) => (
                    <SelectItem key={item.id} value={item.id}>
                      {item.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Link href={`/data?projectId=${encodeURIComponent(projectId)}`}>
                <Button variant="ghost" size="sm" className="h-8 text-xs">
                  Open in Data Explorer <Table className="w-4 h-4 ml-2" />
                </Button>
              </Link>
            </div>
          </CardHeader>
          <div className="overflow-x-auto">
            <table className="w-full text-sm text-left">
              <thead className="bg-muted text-muted-foreground text-xs uppercase">
                <tr>
                  <th className="px-4 py-3 font-medium">ID</th>
                  <th className="px-4 py-3 font-medium">Date</th>
                  <th className="px-4 py-3 font-medium">Enumerator</th>
                  <th className="px-4 py-3 font-medium">Location</th>
                  <th className="px-4 py-3 font-medium">DQA</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3 font-medium text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {(result?.data ?? []).map((sub) => (
                  <tr key={sub.id} className="hover:bg-muted/50 transition-colors">
                    <td className="px-4 py-3 font-medium">{sub.displayId}</td>
                    <td className="px-4 py-3 text-muted-foreground">{new Date(sub.submittedAt).toLocaleString()}</td>
                    <td className="px-4 py-3">{sub.enumerator}</td>
                    <td className="px-4 py-3">{sub.location ?? "—"}</td>
                    <td className="px-4 py-3">
                      <DqaBadge severity={sub.dqaSeverity} red={sub.redFlags} amber={sub.amberFlags} />
                    </td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium uppercase tracking-wider
                        ${sub.status === 'validated' ? 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400' : 
                          sub.status === 'pending' ? 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400' : 
                          'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400'}`}>
                        {sub.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <Link href={`/submissions/${encodeURIComponent(sub.id)}`}>
                        <Button variant="ghost" size="sm" className="h-8">
                          <Eye className="mr-2 h-4 w-4 text-muted-foreground" />
                          View
                        </Button>
                      </Link>
                    </td>
                  </tr>
                ))}
                {submissionsQuery.isLoading && (
                  <tr>
                    <td colSpan={7} className="px-4 py-8 text-center text-muted-foreground">
                      Loading submissions…
                    </td>
                  </tr>
                )}
                {!submissionsQuery.isLoading && (result?.data.length ?? 0) === 0 && (
                  <tr>
                    <td colSpan={7} className="px-4 py-8 text-center text-muted-foreground">
                      {dqaFilter === "all"
                        ? "No submissions stored for this project."
                        : "No submissions match this DQA filter."}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-between border-t p-4">
            <p className="text-sm text-muted-foreground">
              Page {result?.page ?? page} of {totalPages}
            </p>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={page <= 1 || submissionsQuery.isFetching}
                onClick={() => setPage((value) => Math.max(1, value - 1))}
              >
                <ChevronLeft className="mr-1 h-4 w-4" />
                Previous
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={page >= totalPages || submissionsQuery.isFetching}
                onClick={() => setPage((value) => value + 1)}
              >
                Next
                <ChevronRight className="ml-1 h-4 w-4" />
              </Button>
            </div>
          </div>
        </Card>

      </div>
    </Layout>
  );
}
