/**
 * Web preview for a persisted report — reuses ExecuteResultPreview.
 */
import React, { useEffect, useState } from "react";
import { Link, useParams } from "wouter";
import { Layout } from "@/components/layout/Layout";
import { Header } from "@/components/layout/Header";
import {
  ExecuteResultPreview,
  type ExecuteResult,
} from "@/components/reports/ExecuteResultPreview";
import { Button } from "@/components/ui/button";
import { AlertCircle, ArrowLeft, Download, Loader2 } from "lucide-react";
import { reportDownloadUrl } from "@/lib/report-urls";

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

export default function ReportPreview() {
  const params = useParams<{ reportId: string }>();
  const reportId = params.reportId || "";
  const [result, setResult] = useState<ExecuteResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);

  useEffect(() => {
    if (!reportId) {
      setError("Missing report id");
      setBusy(false);
      return;
    }
    let cancelled = false;
    setBusy(true);
    setError(null);
    void (async () => {
      try {
        const response = await fetch(
          `/api/reports/${encodeURIComponent(reportId)}/result`,
        );
        if (!response.ok) throw new Error(await readError(response));
        const body = (await response.json()) as ExecuteResult;
        if (!cancelled) setResult(body);
      } catch (err) {
        if (!cancelled) {
          setResult(null);
          setError(err instanceof Error ? err.message : String(err));
        }
      } finally {
        if (!cancelled) setBusy(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [reportId]);

  return (
    <Layout>
      <Header
        title={result?.title || "Report preview"}
        description={
          result?.window
            ? `Window ${result.window.from || "—"} → ${result.window.to || "—"}`
            : "Stored execute result for this report"
        }
        action={
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="outline" asChild>
              <Link href="/reports">
                <ArrowLeft className="mr-1.5 h-4 w-4" />
                Reports
              </Link>
            </Button>
            {reportId ? (
              <Button size="sm" variant="outline" asChild>
                <a href={reportDownloadUrl(reportId, "pdf")} download>
                  <Download className="mr-1.5 h-4 w-4" />
                  PDF
                </a>
              </Button>
            ) : null}
          </div>
        }
      />
      <div className="flex-1 overflow-auto bg-muted/30 p-4 md:p-6">
        <div className="mx-auto max-w-4xl space-y-4">
          {busy ? (
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading report…
            </p>
          ) : null}
          {error ? (
            <div className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{error}</span>
            </div>
          ) : null}
          {!busy && !error && result ? <ExecuteResultPreview result={result} /> : null}
        </div>
      </div>
    </Layout>
  );
}
