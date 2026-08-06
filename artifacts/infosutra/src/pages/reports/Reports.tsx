import React, { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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
} from "lucide-react";
import { useStudy } from "@/components/study/StudyProvider";
import { RequireActiveStudy } from "@/components/study/RequireActiveStudy";
import { formatReportDatetime } from "@/lib/datetime";
import { reportsApi, type Report } from "@/lib/reports-api";

export default function Reports() {
  const { activeStudy, activeStudyId } = useStudy();
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);

  const listQuery = useQuery({
    queryKey: ["reports", activeStudyId],
    queryFn: () =>
      reportsApi.list({
        studyId: activeStudyId || undefined,
      }),
    enabled: Boolean(activeStudyId),
  });

  const generateDaily = useMutation({
    mutationFn: () =>
      reportsApi.generateDqaDaily({
        studyId: activeStudyId || undefined,
        runAi: true,
        sendEmail: false,
      }),
    onSuccess: () => {
      setError(null);
      queryClient.invalidateQueries({ queryKey: ["reports"] });
    },
    onError: (err: Error) => setError(err.message),
  });

  const generateFinal = useMutation({
    mutationFn: () =>
      reportsApi.generateDqaFinal({
        studyId: activeStudyId || undefined,
        runAi: true,
        sendEmail: false,
      }),
    onSuccess: () => {
      setError(null);
      queryClient.invalidateQueries({ queryKey: ["reports"] });
    },
    onError: (err: Error) => setError(err.message),
  });

  const remove = useMutation({
    mutationFn: (id: string) => reportsApi.remove(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["reports"] }),
    onError: (err: Error) => setError(err.message),
  });

  const reports = (listQuery.data ?? []).filter(
    (r) => r.reportType === "daily_dqa" || r.reportType === "final_dqa" || !r.reportType,
  );
  const busy = generateDaily.isPending || generateFinal.isPending;

  return (
    <Layout>
      <Header
        title="Reports"
        description={
          activeStudy
            ? `${activeStudy.name}${
                activeStudy.dayNumber != null ? ` · Day ${activeStudy.dayNumber}` : ""
              } — DQA Daily & Final`
            : "DQA Daily and Final analytical reports"
        }
        action={
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="outline"
              disabled={!activeStudyId || busy}
              onClick={() => generateDaily.mutate()}
            >
              <Sparkles className={`w-4 h-4 mr-2 ${generateDaily.isPending ? "animate-pulse" : ""}`} />
              {generateDaily.isPending ? "Generating…" : "DQA Daily"}
            </Button>
            <Button
              size="sm"
              className="bg-primary text-primary-foreground"
              disabled={!activeStudyId || busy}
              onClick={() => generateFinal.mutate()}
            >
              <FileBarChart className={`w-4 h-4 mr-2 ${generateFinal.isPending ? "animate-pulse" : ""}`} />
              {generateFinal.isPending ? "Generating…" : "Final DQA"}
            </Button>
          </div>
        }
      />
      <div className="flex-1 overflow-auto p-4 md:p-6 bg-muted/30">
        <RequireActiveStudy
          title="Select a study for reports"
          description="DQA Daily and Final reports are generated for the active study workspace."
        >
        {(error || listQuery.error) && (
          <div className="mb-4 flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive max-w-3xl mx-auto">
            <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
            <span>{error || (listQuery.error as Error)?.message}</span>
          </div>
        )}

        {(generateDaily.data || generateFinal.data) && (
          <div className="mb-4 rounded-md border border-green-200 bg-green-50 text-green-800 dark:border-green-900 dark:bg-green-950/30 dark:text-green-300 p-3 text-sm max-w-3xl mx-auto">
            Generated {(generateFinal.data || generateDaily.data)?.title}. Preview or download PDF.
          </div>
        )}

        <div className="grid grid-cols-1 gap-4 max-w-3xl mx-auto">
          {listQuery.isLoading && (
            <p className="text-sm text-muted-foreground text-center py-12">Loading reports…</p>
          )}

          {!listQuery.isLoading && reports.length === 0 && (
            <Card>
              <CardContent className="flex flex-col items-center gap-3 p-10 text-center">
                <FileBarChart className="w-8 h-8 text-muted-foreground" />
                <div>
                  <h3 className="font-semibold">No DQA reports yet</h3>
                  <p className="mt-1 text-sm text-muted-foreground">
                    Generate a Daily report for field ops, or a Final close-out with TR-1 / TR-3 / TR-5
                    triangulation.
                  </p>
                </div>
              </CardContent>
            </Card>
          )}

          {reports.map((report: Report) => (
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
                    {report.fileSizeKb != null ? ` · ${report.fileSizeKb} KB` : ""}
                    {report.generatedAt
                      ? ` · ${formatReportDatetime(report.generatedAt)}`
                      : ""}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2 justify-end">
                  <Button variant="outline" size="sm" asChild>
                    <a href={reportsApi.previewUrl(report.id)} target="_blank" rel="noreferrer">
                      <ExternalLink className="w-4 h-4 mr-1.5" />
                      Preview
                    </a>
                  </Button>
                  <Button variant="outline" size="sm" asChild>
                    <a href={reportsApi.downloadUrl(report.id, "pdf")} download>
                      <Download className="w-4 h-4 mr-1.5" />
                      PDF
                    </a>
                  </Button>
                  <Button variant="outline" size="sm" asChild>
                    <a href={reportsApi.downloadUrl(report.id, "docx")} download>
                      <Download className="w-4 h-4 mr-1.5" />
                      DOCX
                    </a>
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-destructive"
                    disabled={remove.isPending}
                    onClick={() => remove.mutate(report.id)}
                  >
                    <Trash2 className="w-4 h-4" />
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>

        <p className="text-xs text-muted-foreground text-center mt-8 max-w-xl mx-auto">
          Scheduled DQA Daily email is under Settings. Final reports are generated on demand.
        </p>
        </RequireActiveStudy>
      </div>
    </Layout>
  );
}
