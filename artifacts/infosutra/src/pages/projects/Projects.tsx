import React, { useMemo, useState } from "react";
import { Link } from "wouter";
import { useQueryClient } from "@tanstack/react-query";
import {
  getGetProjectsQueryKey,
  useGetProjects,
  useSyncProjects,
} from "@workspace/api-client-react";
import { Layout } from "@/components/layout/Layout";
import { Header } from "@/components/layout/Header";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Search, RefreshCw, ArrowRight, Clock, AlertCircle, CircleHelp } from "lucide-react";
import { useStudy } from "@/components/study/StudyProvider";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

type Scope = "study" | "unassigned";

/** Forms (Kobo instruments) belonging to the active study workspace. */
export default function FormsPage() {
  const [searchTerm, setSearchTerm] = useState("");
  const { activeStudy, activeStudyId } = useStudy();
  const [scope, setScope] = useState<Scope>(activeStudyId ? "study" : "unassigned");
  const queryClient = useQueryClient();
  const projectsQuery = useGetProjects();
  const syncProjects = useSyncProjects({
    mutation: {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: getGetProjectsQueryKey() });
        queryClient.invalidateQueries({ queryKey: ["studies"] });
        setScope("unassigned");
      },
    },
  });

  const allForms = projectsQuery.data ?? [];
  const unassignedCount = allForms.filter((p) => !p.studyId).length;
  const studyCount = activeStudyId
    ? allForms.filter((p) => p.studyId === activeStudyId).length
    : 0;

  const scopedForms = useMemo(() => {
    if (scope === "unassigned") return allForms.filter((p) => !p.studyId);
    if (scope === "study" && activeStudyId) {
      return allForms.filter((p) => p.studyId === activeStudyId);
    }
    return [];
  }, [allForms, scope, activeStudyId]);

  const filteredForms = scopedForms.filter(
    (p) =>
      p.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      (p.sector ?? "").toLowerCase().includes(searchTerm.toLowerCase()) ||
      p.uid.toLowerCase().includes(searchTerm.toLowerCase()) ||
      (p.toolCode ?? "").toLowerCase().includes(searchTerm.toLowerCase()),
  );

  return (
    <Layout>
      <Header
        title="Forms"
        description={
          activeStudy
            ? `${activeStudy.name} — Kobo forms in this study (sync, then assign tool codes)`
            : "Kobo forms — sync from Kobo, then assign them to a study"
        }
        action={
          <>
            <Dialog>
              <DialogTrigger asChild>
                <Button variant="outline" size="sm" aria-label="Study workspace help">
                  <CircleHelp className="mr-2 h-4 w-4" />
                  Help
                </Button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>Study workspace flow</DialogTitle>
                  <DialogDescription>
                    How Kobo forms connect to a study workspace.
                  </DialogDescription>
                </DialogHeader>
                <ol className="list-decimal pl-5 space-y-2 text-sm text-muted-foreground">
                  <li>Create or select a study (sidebar / Studies)</li>
                  <li>Create instruments in KoboToolbox, then sync them here</li>
                  <li>
                    Assign each form to the study with a tool code (T1 / T2 / T3) on{" "}
                    <Link href="/studies" className="underline text-primary">
                      Studies
                    </Link>
                  </li>
                </ol>
              </DialogContent>
            </Dialog>
            <Button
              onClick={() => {
                if (!activeStudyId) return;
                syncProjects.mutate({ params: { studyId: activeStudyId } });
              }}
              disabled={syncProjects.isPending || !activeStudyId}
              className="bg-primary text-primary-foreground"
            >
              <RefreshCw className={`w-4 h-4 mr-2 ${syncProjects.isPending ? "animate-spin" : ""}`} />
              Sync from Kobo
            </Button>
          </>
        }
      />

      <div className="flex-1 overflow-auto p-4 md:p-6 bg-muted/30">
        <div className="flex flex-col sm:flex-row gap-3 mb-6">
          <div className="relative flex-1 max-w-md">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <Input
              placeholder="Search forms, tools, UIDs..."
              className="pl-9"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
            />
          </div>
          <div className="flex flex-wrap gap-1.5">
            <Button
              size="sm"
              variant={scope === "study" ? "default" : "outline"}
              disabled={!activeStudyId}
              onClick={() => setScope("study")}
            >
              This study ({studyCount})
            </Button>
            <Button
              size="sm"
              variant={scope === "unassigned" ? "default" : "outline"}
              onClick={() => setScope("unassigned")}
            >
              Unassigned ({unassignedCount})
            </Button>
          </div>
        </div>

        {(projectsQuery.error || syncProjects.error) && (
          <div className="mb-6 flex items-start gap-3 rounded-md border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              <p className="font-medium">Unable to load Kobo forms</p>
              <p>{(syncProjects.error ?? projectsQuery.error)?.message}</p>
              <Link href="/settings" className="mt-1 inline-block underline">
                Check Kobo credentials
              </Link>
            </div>
          </div>
        )}

        {syncProjects.data && (
          <div
            className={`mb-6 rounded-md border p-4 text-sm ${
              syncProjects.data.success
                ? "border-green-200 bg-green-50 text-green-800 dark:border-green-900 dark:bg-green-950/30 dark:text-green-300"
                : "border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-300"
            }`}
          >
            Synced {syncProjects.data.projectsSynced} form(s) and fetched{" "}
            {syncProjects.data.submissionsFetched} submissions ({syncProjects.data.newSubmissions}{" "}
            new).
            {syncProjects.data.errors.length > 0 &&
              ` ${syncProjects.data.errors.length} form(s) failed.`}
            {unassignedCount > 0 && (
              <span>
                {" "}
                {unassignedCount} unassigned —{" "}
                <Link href="/studies" className="underline font-medium">
                  assign to your study
                </Link>
                .
              </span>
            )}
          </div>
        )}

        {projectsQuery.isLoading && (
          <div className="py-16 text-center text-sm text-muted-foreground">Loading forms…</div>
        )}

        {!projectsQuery.isLoading && !projectsQuery.error && filteredForms.length === 0 && (
          <Card className="p-10 text-center">
            <h3 className="font-semibold">
              {scope === "unassigned"
                ? "No unassigned forms"
                : "No forms in this study yet"}
            </h3>
            <p className="mt-2 text-sm text-muted-foreground">
              {scope === "study"
                ? "Sync from Kobo, then assign forms to this study on the Studies page."
                : "All synced forms are already in a study, or nothing has been synced yet."}
            </p>
            <div className="mt-4 flex justify-center gap-2">
              <Link href="/studies">
                <Button variant="outline">Open Studies</Button>
              </Link>
              <Link href="/settings">
                <Button variant="outline">Open Settings</Button>
              </Link>
            </div>
          </Card>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {filteredForms.map((form) => (
            <Link key={form.id} href={`/forms/${form.id}`} className="block h-full">
              <Card className="flex h-full flex-col overflow-hidden cursor-pointer hover:border-primary/50 transition-colors">
                <div className="p-5 flex-1">
                  <div className="flex justify-between items-start mb-3">
                    <div className="flex flex-wrap gap-1.5">
                      {form.toolCode ? (
                        <Badge
                          variant="outline"
                          className="bg-primary/10 text-primary border-primary/20 font-mono"
                        >
                          {form.toolCode}
                        </Badge>
                      ) : (
                        <Badge variant="outline" className="text-muted-foreground">
                          Unassigned
                        </Badge>
                      )}
                      <Badge
                        variant="outline"
                        className={
                          form.status === "deployed"
                            ? "bg-green-100 text-green-800 border-green-200 dark:bg-green-900/30 dark:text-green-400 dark:border-green-800"
                            : form.status === "draft"
                              ? "bg-gray-100 text-gray-800 border-gray-200 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-700"
                              : "bg-orange-100 text-orange-800 border-orange-200 dark:bg-orange-900/30 dark:text-orange-400 dark:border-orange-800"
                        }
                      >
                        {form.status}
                      </Badge>
                    </div>
                    <span className="text-xs font-mono text-muted-foreground flex items-center gap-1">
                      <Clock className="w-3 h-3" />
                      {form.lastSyncAt ? new Date(form.lastSyncAt).toLocaleDateString() : "Never"}
                    </span>
                  </div>

                  <h3 className="font-semibold text-lg leading-tight mb-1">{form.name}</h3>
                  <div className="text-xs text-muted-foreground mb-4">
                    {[form.sector, form.country].filter(Boolean).join(" • ")}
                    {(form.sector || form.country) && " • "}
                    UID: <span className="font-mono">{form.uid}</span>
                  </div>

                  <div className="grid grid-cols-3 gap-2 border-t pt-4">
                    <div className="flex flex-col">
                      <span className="text-xs text-muted-foreground mb-1">Submissions</span>
                      <span className="font-mono font-medium">
                        {form.submissionCount.toLocaleString()}
                      </span>
                    </div>
                    <div className="flex flex-col">
                      <span className="text-xs text-muted-foreground mb-1">Tool</span>
                      <span className="font-mono font-medium">{form.toolCode || "—"}</span>
                    </div>
                    <div className="flex flex-col">
                      <span className="text-xs text-muted-foreground mb-1">Staff</span>
                      <span className="font-mono font-medium">{form.enumeratorCount}</span>
                    </div>
                  </div>
                </div>
                <div className="bg-muted/50 p-3 border-t flex items-center justify-between text-sm">
                  <span>View form</span>
                  <ArrowRight className="w-4 h-4" />
                </div>
              </Card>
            </Link>
          ))}
        </div>
      </div>
    </Layout>
  );
}
