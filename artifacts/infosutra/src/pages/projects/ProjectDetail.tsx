import React from "react";
import { Link } from "wouter";
import { useQueryClient } from "@tanstack/react-query";
import {
  getGetProjectQueryKey,
  getGetSubmissionsQueryKey,
  useGetProject,
  useGetSubmissions,
  useSyncProject,
  useUpdateProject,
} from "@workspace/api-client-react";
import { Layout } from "@/components/layout/Layout";
import { Header } from "@/components/layout/Header";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { RefreshCw, Eye, Table, AlertCircle } from "lucide-react";
import { useFormRouteId } from "@/lib/use-form-route-id";

function formatDate(value: string | null | undefined): string {
  return value ? new Date(value).toLocaleString() : "Not available";
}

export default function ProjectDetail() {
  const projectId = useFormRouteId();
  const queryClient = useQueryClient();
  const projectQuery = useGetProject(projectId);
  const submissionsQuery = useGetSubmissions({
    projectId,
    page: 1,
    limit: 10,
  });
  const syncProject = useSyncProject({
    mutation: {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: getGetProjectQueryKey(projectId) });
        queryClient.invalidateQueries({ queryKey: getGetSubmissionsQueryKey({ projectId, page: 1, limit: 10 }) });
      },
    },
  });
  const updateProject = useUpdateProject({
    mutation: {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: getGetProjectQueryKey(projectId) });
        queryClient.invalidateQueries({ queryKey: ["getSubmission"] });
      },
    },
  });
  const project = projectQuery.data;

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
            <Button size="sm" disabled={syncProject.isPending} onClick={() => syncProject.mutate({ projectId })} className="bg-primary text-primary-foreground">
              <RefreshCw className={`w-4 h-4 mr-2 ${syncProject.isPending ? "animate-spin" : ""}`} />
              {syncProject.isPending ? "Syncing…" : "Sync Data"}
            </Button>
          </div>
        }
      />
      <div className="flex-1 overflow-auto p-4 md:p-6 bg-muted/30">
        
        <div className="grid grid-cols-1 gap-4 mb-6 sm:grid-cols-2 xl:grid-cols-4">
          {[
            ["Status", project.status],
            ["Questions", project.questionCount.toLocaleString()],
            ["Owner", project.owner ?? "Not available"],
            ["Last edited by", project.lastEditedBy ?? "Not available"],
            ["Last modified", formatDate(project.lastModifiedAt)],
            ["Latest submission", formatDate(project.lastSubmissionAt)],
            ["Sector", project.sector ?? "Not specified"],
            ["Country", project.country ?? "Not specified"],
          ].map(([label, value]) => (
            <Card key={label}>
              <CardContent className="p-4 min-h-20">
                <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">{label}</p>
                <p className={`mt-2 font-semibold ${label === "Status" ? "capitalize" : ""}`}>{value}</p>
              </CardContent>
            </Card>
          ))}
        </div>

        <Card className="mb-6">
          <CardHeader className="py-4 border-b">
            <CardTitle className="text-sm font-semibold">Kobo Form</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4 p-4 text-sm md:grid-cols-3">
            <div><p className="text-xs text-muted-foreground">Current Version</p><p className="mt-1 text-lg font-semibold">{project.currentVersionNumber != null ? `Version ${project.currentVersionNumber}` : "Not available"}</p></div>
            <div><p className="text-xs text-muted-foreground">Deployed Version</p><p className="mt-1 text-lg font-semibold">{project.deployedVersionNumber != null ? `Version ${project.deployedVersionNumber}` : "Not deployed"}</p></div>
            <div><p className="text-xs text-muted-foreground">Submissions</p><p className="mt-1 text-lg font-semibold">{project.submissionCount.toLocaleString()}</p></div>
            <div className="md:col-span-3 border-t pt-4 space-y-2 max-w-sm">
              <Label htmlFor="label-language">Preview language</Label>
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
                <SelectTrigger id="label-language">
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
              <p className="text-xs text-muted-foreground">
                Controls question and choice labels when viewing submission data.
              </p>
            </div>
            {project.description && <p className="md:col-span-3 border-t pt-4 text-muted-foreground">{project.description}</p>}
          </CardContent>
        </Card>

        {/* Data Preview */}
        <Card>
          <CardHeader className="py-4 border-b flex flex-row items-center justify-between">
            <CardTitle className="text-sm font-semibold">Recent Submissions</CardTitle>
            <Link href={`/forms/${projectId}/submissions?view=table`}>
              <Button variant="ghost" size="sm" className="h-8 text-xs">
                All data as table <Table className="w-4 h-4 ml-2" />
              </Button>
            </Link>
          </CardHeader>
          <div className="overflow-x-auto">
            <table className="w-full text-sm text-left">
              <thead className="bg-muted text-muted-foreground text-xs uppercase">
                <tr>
                  <th className="px-4 py-3 font-medium">ID</th>
                  <th className="px-4 py-3 font-medium">Date</th>
                  <th className="px-4 py-3 font-medium">Enumerator</th>
                  <th className="px-4 py-3 font-medium">Location</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3 font-medium text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {(submissionsQuery.data?.data ?? []).map(sub => (
                  <tr key={sub.id} className="hover:bg-muted/50 transition-colors">
                    <td className="px-4 py-3 font-medium">{sub.displayId}</td>
                    <td className="px-4 py-3 text-muted-foreground">{new Date(sub.submittedAt).toLocaleString()}</td>
                    <td className="px-4 py-3">{sub.enumerator}</td>
                    <td className="px-4 py-3">{sub.location ?? "—"}</td>
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
                {!submissionsQuery.isLoading && (submissionsQuery.data?.data.length ?? 0) === 0 && (
                  <tr><td colSpan={6} className="px-4 py-8 text-center text-muted-foreground">No submissions stored for this project.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </Card>

      </div>
    </Layout>
  );
}
