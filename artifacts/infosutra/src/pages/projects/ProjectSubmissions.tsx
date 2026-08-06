import React, { useState } from "react";
import { Link } from "wouter";
import { useGetProject, useGetSubmissions } from "@workspace/api-client-react";
import { Layout } from "@/components/layout/Layout";
import { Header } from "@/components/layout/Header";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ArrowLeft, ChevronLeft, ChevronRight, Eye, LayoutList, Table2 } from "lucide-react";
import { SubmissionsGrid } from "./SubmissionsGrid";
import { useFormRouteId } from "@/lib/use-form-route-id";

const PAGE_SIZE = 25;

type ViewMode = "table" | "list";

function initialView(): ViewMode {
  if (typeof window === "undefined") return "table";
  return new URLSearchParams(window.location.search).get("view") === "list" ? "list" : "table";
}

export default function ProjectSubmissions() {
  const projectId = useFormRouteId("submissions");
  const [view, setView] = useState<ViewMode>(initialView);
  const [page, setPage] = useState(1);
  const projectQuery = useGetProject(projectId);
  const submissionsQuery = useGetSubmissions({
    projectId,
    page,
    limit: PAGE_SIZE,
  });
  const result = submissionsQuery.data;

  const changeView = (next: ViewMode) => {
    setView(next);
    if (typeof window !== "undefined") {
      const url = new URL(window.location.href);
      url.searchParams.set("view", next);
      window.history.replaceState({}, "", url);
    }
  };

  return (
    <Layout>
      <Header
        title={projectQuery.data ? `${projectQuery.data.name} data` : "Submissions"}
        description={
          view === "table"
            ? "All forms in one table — coloured cells carry DQA flags"
            : "Browse submitted forms one by one"
        }
        action={
          <Link href={`/forms/${projectId}`}>
            <Button variant="outline" size="sm">
              <ArrowLeft className="mr-2 h-4 w-4" />
              <span className="hidden sm:inline">Project details</span>
              <span className="sm:hidden">Project</span>
            </Button>
          </Link>
        }
      />
      <div className="flex-1 overflow-auto bg-muted/30 p-4 md:p-6">
        <div className="mb-4 inline-flex rounded-md border bg-card p-1">
          <button
            type="button"
            onClick={() => changeView("table")}
            className={`inline-flex items-center gap-2 rounded px-3 py-1.5 text-sm ${
              view === "table" ? "bg-primary text-primary-foreground" : "text-muted-foreground"
            }`}
          >
            <Table2 className="h-4 w-4" />
            Table view
          </button>
          <button
            type="button"
            onClick={() => changeView("list")}
            className={`inline-flex items-center gap-2 rounded px-3 py-1.5 text-sm ${
              view === "list" ? "bg-primary text-primary-foreground" : "text-muted-foreground"
            }`}
          >
            <LayoutList className="h-4 w-4" />
            Form list
          </button>
        </div>

        {view === "table" ? (
          <SubmissionsGrid projectId={projectId} />
        ) : (
          <Card className="overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] text-left text-sm">
                <thead className="bg-muted text-xs uppercase text-muted-foreground">
                  <tr>
                    <th className="px-4 py-3 font-medium">Submission</th>
                    <th className="px-4 py-3 font-medium">Submitted</th>
                    <th className="px-4 py-3 font-medium">Enumerator</th>
                    <th className="px-4 py-3 font-medium">Location</th>
                    <th className="px-4 py-3 font-medium">Status</th>
                    <th className="px-4 py-3 text-right font-medium">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {(result?.data ?? []).map((submission) => (
                    <tr key={submission.id} className="transition-colors hover:bg-muted/50">
                      <td className="px-4 py-3 font-medium">{submission.displayId}</td>
                      <td className="px-4 py-3 text-muted-foreground">{new Date(submission.submittedAt).toLocaleString()}</td>
                      <td className="px-4 py-3">{submission.enumerator}</td>
                      <td className="px-4 py-3">{submission.location ?? "—"}</td>
                      <td className="px-4 py-3 capitalize">{submission.status}</td>
                      <td className="px-4 py-3 text-right">
                        <Link href={`/submissions/${encodeURIComponent(submission.id)}`}>
                          <Button variant="ghost" size="sm">
                            <Eye className="mr-2 h-4 w-4" />
                            View
                          </Button>
                        </Link>
                      </td>
                    </tr>
                  ))}
                  {!submissionsQuery.isLoading && (result?.data.length ?? 0) === 0 && (
                    <tr>
                      <td colSpan={6} className="px-4 py-12 text-center text-muted-foreground">
                        No submissions found.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            <div className="flex items-center justify-between border-t p-4">
              <p className="text-sm text-muted-foreground">
                Page {result?.page ?? page} of {Math.max(result?.totalPages ?? 1, 1)}
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
                  disabled={!result || page >= result.totalPages || submissionsQuery.isFetching}
                  onClick={() => setPage((value) => value + 1)}
                >
                  Next
                  <ChevronRight className="ml-1 h-4 w-4" />
                </Button>
              </div>
            </div>
          </Card>
        )}
      </div>
    </Layout>
  );
}
