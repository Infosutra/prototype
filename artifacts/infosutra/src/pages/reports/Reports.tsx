import React, { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "wouter";
import { useQueryClient } from "@tanstack/react-query";
import {
  getGetReportsQueryKey,
  useDeleteReport,
  useGetReports,
  useListReportTemplates,
  type ReportOut,
} from "@workspace/api-client-react";
import { Layout } from "@/components/layout/Layout";
import { Header } from "@/components/layout/Header";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  FileBarChart,
  Download,
  Trash2,
  Sparkles,
  ExternalLink,
  AlertCircle,
  CheckCircle2,
  Loader2,
} from "lucide-react";
import { useStudy } from "@/components/study/StudyProvider";
import { RequireActiveStudy } from "@/components/study/RequireActiveStudy";
import { formatReportDatetime } from "@/lib/datetime";
import { reportDownloadUrl, reportPreviewUrl } from "@/lib/report-urls";
import { pollExecuteJob } from "@/lib/report-authoring";

async function readError(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
    if (typeof body?.message === "string") return body.message;
  } catch {
    /* ignore */
  }
  return response.statusText || `HTTP ${response.status}`;
}

export default function Reports() {
  const { activeStudy, activeStudyId } = useStudy();
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [selectedTemplateId, setSelectedTemplateId] = useState<string>("");
  const [generating, setGenerating] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  const listQuery = useGetReports(
    { studyId: activeStudyId || undefined },
    { query: { enabled: Boolean(activeStudyId) } as never },
  );

  const templatesQuery = useListReportTemplates(
    { studyId: activeStudyId || undefined },
    { query: { enabled: Boolean(activeStudyId) } as never },
  );

  const templates = (templatesQuery.data ?? []).filter(
    (row) => row.status !== "draft" && (row.versionCount ?? 0) > 0,
  );
  const templateId = useMemo(() => {
    if (selectedTemplateId && templates.some((t) => t.id === selectedTemplateId)) {
      return selectedTemplateId;
    }
    return templates[0]?.id ?? "";
  }, [selectedTemplateId, templates]);

  const remove = useDeleteReport({
    mutation: {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: getGetReportsQueryKey() }),
      onError: (err) => setError(err.message),
    },
  });

  const reports = listQuery.data ?? [];
  const hasTemplates = templates.length > 0;

  const onGenerate = async () => {
    if (!activeStudyId || !templateId || generating) return;

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setGenerating(true);
    setError(null);
    setSuccess(null);
    setStatus("Queuing report…");

    try {
      const response = await fetch("/api/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          type: "execute",
          studyId: activeStudyId,
          payload: {
            templateId,
            window: { preset: "execution_date" },
          },
        }),
        signal: controller.signal,
      });
      if (!response.ok) throw new Error(await readError(response));
      const body = (await response.json()) as { jobId: string };
      if (!body.jobId) throw new Error("No job id returned");

      setStatus("Generating report…");
      const job = await pollExecuteJob(body.jobId, { signal: controller.signal });
      if (controller.signal.aborted) return;

      if (job.status === "failed") {
        setStatus(null);
        setError(job.error || "Report generation failed");
        return;
      }

      const title = job.result?.title?.trim();
      setStatus(null);
      setSuccess(title ? `“${title}” is ready to download.` : "Report is ready to download.");
      await queryClient.invalidateQueries({ queryKey: getGetReportsQueryKey() });
    } catch (err) {
      if ((err as Error).name === "AbortError") return;
      setStatus(null);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (abortRef.current === controller) {
        setGenerating(false);
      }
    }
  };

  return (
    <Layout>
      <Header
        title="Reports"
        description={
          activeStudy
            ? `${activeStudy.name}${
                activeStudy.dayNumber != null ? ` · Day ${activeStudy.dayNumber}` : ""
              } — generate from a saved template`
            : "Generate reports from user-authored templates"
        }
        action={
          <div className="flex flex-wrap gap-2 items-center">
            <Button size="sm" variant="outline" asChild>
              <Link href="/report-templates">Templates</Link>
            </Button>
            {hasTemplates ? (
              <>
                <select
                  className="h-9 rounded-md border bg-background px-2 text-sm"
                  value={templateId}
                  onChange={(e) => setSelectedTemplateId(e.target.value)}
                  disabled={generating}
                >
                  {templates.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name}
                    </option>
                  ))}
                </select>
                <Button
                  size="sm"
                  className="bg-primary text-primary-foreground"
                  disabled={!activeStudyId || !templateId || generating}
                  onClick={() => void onGenerate()}
                >
                  {generating ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <Sparkles className="mr-2 h-4 w-4" />
                  )}
                  {generating ? "Generating…" : "Generate"}
                </Button>
              </>
            ) : null}
          </div>
        }
      />
      <div className="flex-1 overflow-auto p-4 md:p-6 bg-muted/30">
        <RequireActiveStudy
          title="Select a study for reports"
          description="Reports are generated for the active study from a saved template."
        >
        {(error || listQuery.error) && (
          <div className="mb-4 flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive max-w-3xl mx-auto">
            <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
            <span>{error || (listQuery.error as Error)?.message}</span>
          </div>
        )}

        {status && (
          <div className="mb-4 flex items-start gap-2 rounded-md border border-border bg-muted/40 p-3 text-sm max-w-3xl mx-auto">
            <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-muted-foreground" />
            <span>{status}</span>
          </div>
        )}

        {success && !status && !error && (
          <div className="mb-4 flex items-start gap-2 rounded-md border border-green-200 bg-green-50 p-3 text-sm text-green-800 dark:border-green-900 dark:bg-green-950/30 dark:text-green-300 max-w-3xl mx-auto">
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{success}</span>
          </div>
        )}

        <div className="grid grid-cols-1 gap-4 max-w-3xl mx-auto">
          {!hasTemplates && !templatesQuery.isLoading && (
            <Card>
              <CardContent className="flex flex-col items-center gap-3 p-10 text-center">
                <FileBarChart className="w-8 h-8 text-muted-foreground" />
                <div>
                  <h3 className="font-semibold">No report templates yet</h3>
                  <p className="mt-1 text-sm text-muted-foreground">
                    Author and save a template before Generate or schedule can run.
                  </p>
                </div>
                <div className="flex gap-2">
                  <Button size="sm" asChild>
                    <Link href="/report-templates">Create template</Link>
                  </Button>
                </div>
              </CardContent>
            </Card>
          )}

          {listQuery.isLoading && (
            <p className="text-sm text-muted-foreground text-center py-12">Loading reports…</p>
          )}

          {!listQuery.isLoading && hasTemplates && reports.length === 0 && !generating && (
            <Card>
              <CardContent className="flex flex-col items-center gap-3 p-10 text-center">
                <FileBarChart className="w-8 h-8 text-muted-foreground" />
                <div>
                  <h3 className="font-semibold">No reports yet</h3>
                  <p className="mt-1 text-sm text-muted-foreground">
                    Choose a saved template and click Generate. The new report will appear here
                    when it finishes.
                  </p>
                </div>
              </CardContent>
            </Card>
          )}

          {reports.map((report: ReportOut) => (
            <Card key={report.id} className="overflow-hidden">
              <CardContent className="p-5 flex flex-col md:flex-row gap-4 md:items-center">
                <div className="w-11 h-11 rounded-lg bg-muted flex items-center justify-center shrink-0">
                  <FileBarChart className="w-5 h-5 text-muted-foreground" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex flex-wrap items-center gap-2 mb-1">
                    <h3 className="font-semibold truncate">{report.title}</h3>
                    <Badge variant="outline" className="uppercase text-[10px]">
                      {report.status}
                    </Badge>
                    <Badge variant="outline" className="text-[10px]">
                      {report.reportType || "report"}
                    </Badge>
                  </div>
                  <p className="text-sm text-muted-foreground">
                    {report.reportDate || "—"}
                    {report.promptName ? ` · ${report.promptName}` : ""}
                    {report.fileSizeKb != null ? ` · ${report.fileSizeKb} KB` : ""}
                    {report.generatedAt
                      ? ` · ${formatReportDatetime(report.generatedAt)}`
                      : ""}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2 justify-end">
                  <Button variant="outline" size="sm" asChild>
                    <a href={reportPreviewUrl(report.id)} target="_blank" rel="noreferrer">
                      <ExternalLink className="w-4 h-4 mr-1.5" />
                      Preview
                    </a>
                  </Button>
                  <Button variant="outline" size="sm" asChild>
                    <a href={reportDownloadUrl(report.id, "pdf")} download>
                      <Download className="w-4 h-4 mr-1.5" />
                      PDF
                    </a>
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-destructive"
                    disabled={remove.isPending}
                    onClick={() => remove.mutate({ reportId: report.id })}
                  >
                    <Trash2 className="w-4 h-4" />
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>

        <p className="text-xs text-muted-foreground text-center mt-8 max-w-xl mx-auto">
          Schedules require a template and enqueue execute then email. Configure under Studies.
        </p>
        </RequireActiveStudy>
      </div>
    </Layout>
  );
}
