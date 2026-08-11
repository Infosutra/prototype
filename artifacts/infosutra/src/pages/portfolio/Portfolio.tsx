import React, { useMemo } from "react";
import { Link } from "wouter";
import {
  useGetDqaByProject,
  useGetStudies,
} from "@workspace/api-client-react";
import { Layout } from "@/components/layout/Layout";
import { Header } from "@/components/layout/Header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Library, FolderGit2, Database, ShieldAlert } from "lucide-react";
import { useStudy } from "@/components/study/StudyProvider";

export default function Portfolio() {
  const { setActiveStudyId } = useStudy();
  const studiesQuery = useGetStudies();
  // Intentionally unscoped — Portfolio is the cross-study exception.
  const dqaQuery = useGetDqaByProject();

  const studies = studiesQuery.data ?? [];
  const dqaByProject = dqaQuery.data ?? [];

  const dqaByStudy = useMemo(() => {
    const projectToStudy = new Map<string, string>();
    for (const study of studies) {
      for (const project of study.projects ?? []) {
        projectToStudy.set(project.id, study.id);
      }
    }
    const buckets = new Map<
      string,
      { total: number; clean: number; amber: number; red: number; flags: number }
    >();
    for (const row of dqaByProject) {
      const studyId = projectToStudy.get(row.projectId);
      if (!studyId) continue;
      const bucket = buckets.get(studyId) ?? {
        total: 0,
        clean: 0,
        amber: 0,
        red: 0,
        flags: 0,
      };
      bucket.total += row.totalSubmissions;
      bucket.clean += row.cleanSubmissions;
      bucket.amber += row.amberSubmissions;
      bucket.red += row.redSubmissions;
      bucket.flags += row.redFlags + row.amberFlags;
      buckets.set(studyId, bucket);
    }
    return buckets;
  }, [studies, dqaByProject]);

  const totals = useMemo(() => {
    return studies.reduce(
      (acc, study) => {
        acc.studies += 1;
        acc.forms += study.projectCount ?? study.projects?.length ?? 0;
        acc.submissions += study.submissionCount ?? 0;
        return acc;
      },
      { studies: 0, forms: 0, submissions: 0 },
    );
  }, [studies]);

  const isLoading = studiesQuery.isLoading || dqaQuery.isLoading;
  const error = studiesQuery.error?.message || dqaQuery.error?.message;

  return (
    <Layout>
      <Header
        title="Portfolio"
        description="Cross-study overview — the deliberate exception to study scoping"
      />
      <div className="flex-1 overflow-auto p-4 md:p-6 bg-muted/30 space-y-6">
        {error && (
          <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
            {error}
          </div>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <Card>
            <CardContent className="p-4 flex items-center gap-3">
              <Library className="h-5 w-5 text-primary" />
              <div>
                <p className="text-xs uppercase tracking-wider text-muted-foreground">Studies</p>
                <p className="text-2xl font-semibold font-mono">
                  {isLoading ? "…" : totals.studies.toLocaleString()}
                </p>
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-4 flex items-center gap-3">
              <FolderGit2 className="h-5 w-5 text-primary" />
              <div>
                <p className="text-xs uppercase tracking-wider text-muted-foreground">Forms</p>
                <p className="text-2xl font-semibold font-mono">
                  {isLoading ? "…" : totals.forms.toLocaleString()}
                </p>
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-4 flex items-center gap-3">
              <Database className="h-5 w-5 text-primary" />
              <div>
                <p className="text-xs uppercase tracking-wider text-muted-foreground">Submissions</p>
                <p className="text-2xl font-semibold font-mono">
                  {isLoading ? "…" : totals.submissions.toLocaleString()}
                </p>
              </div>
            </CardContent>
          </Card>
        </div>

        <Card>
          <CardHeader className="py-4 border-b">
            <CardTitle className="text-sm font-semibold flex items-center">
              <ShieldAlert className="w-4 h-4 mr-2 text-primary" />
              Studies
            </CardTitle>
          </CardHeader>
          <div className="overflow-x-auto">
            <table className="w-full text-sm text-left">
              <thead className="bg-muted text-muted-foreground text-xs uppercase">
                <tr>
                  <th className="px-4 py-3 font-medium">Study</th>
                  <th className="px-4 py-3 font-medium text-right">Forms</th>
                  <th className="px-4 py-3 font-medium text-right">Submissions</th>
                  <th className="px-4 py-3 font-medium text-right">DQA clean</th>
                  <th className="px-4 py-3 font-medium text-right">Flags</th>
                  <th className="px-4 py-3 font-medium">Kobo</th>
                  <th className="px-4 py-3 font-medium text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border bg-card">
                {studies.map((study) => {
                  const dqa = dqaByStudy.get(study.id);
                  const cleanPct =
                    dqa && dqa.total
                      ? Math.round((dqa.clean / dqa.total) * 100)
                      : null;
                  return (
                    <tr key={study.id} className="hover:bg-muted/50 transition-colors">
                      <td className="px-4 py-3">
                        <div className="font-medium">{study.name}</div>
                        {study.dayNumber != null && (
                          <div className="text-xs text-muted-foreground">Day {study.dayNumber}</div>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right font-mono">
                        {(study.projectCount ?? study.projects?.length ?? 0).toLocaleString()}
                      </td>
                      <td className="px-4 py-3 text-right font-mono">
                        {(study.submissionCount ?? 0).toLocaleString()}
                      </td>
                      <td className="px-4 py-3 text-right font-mono">
                        {cleanPct == null ? "—" : `${cleanPct}%`}
                      </td>
                      <td className="px-4 py-3 text-right font-mono">
                        {dqa?.flags?.toLocaleString() ?? "—"}
                      </td>
                      <td className="px-4 py-3">
                        <Badge variant="outline" className="text-[10px] uppercase">
                          {study.credential?.connected ? "Connected" : "Not connected"}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 text-right">
                        <Link href="/">
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => setActiveStudyId(study.id)}
                          >
                            Open workspace
                          </Button>
                        </Link>
                      </td>
                    </tr>
                  );
                })}
                {!isLoading && studies.length === 0 && (
                  <tr>
                    <td colSpan={7} className="px-4 py-8 text-center text-muted-foreground">
                      No studies yet.{" "}
                      <Link href="/studies" className="text-primary underline">
                        Create one
                      </Link>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
    </Layout>
  );
}
