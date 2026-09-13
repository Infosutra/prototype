/**
 * Minimal Phase 3 execute preview: enqueue type=execute, poll GET /jobs/:id,
 * render ExecuteResult JSON (tables / pre). Not SpecPreview HTML.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useSearch, useLocation } from "wouter";
import { Layout } from "@/components/layout/Layout";
import { Header } from "@/components/layout/Header";
import { Button } from "@/components/ui/button";
import { RequireActiveStudy } from "@/components/study/RequireActiveStudy";
import { useStudy } from "@/components/study/StudyProvider";

type JobStatus = {
  jobId: string;
  type: string;
  status: string;
  studyId?: string | null;
  result?: ExecuteResult | null;
  error?: string | null;
};

type ExecuteResult = {
  reportId?: string;
  title?: string;
  window?: { from?: string; to?: string };
  sections?: Array<{
    id: string;
    title: string;
    components: Array<{
      id: string;
      type: string;
      data?: unknown;
      error?: string;
    }>;
  }>;
  artifacts?: { pdf?: string };
};

const GOLDEN_SPEC = {
  specVersion: "1.0",
  title: "Preview execute",
  sections: [
    {
      id: "s1",
      title: "Counts",
      components: [
        {
          id: "s1c1",
          type: "kpi_group",
          query: {
            entity: "submission",
            window: "execution_date",
            measures: [
              { id: "total", fn: "count" },
              { id: "clean", fn: "countWhere", field: "isClean", eq: true },
              { id: "flagged", fn: "countWhere", field: "isClean", eq: false },
            ],
          },
          display: {
            items: [
              { label: "Total", field: "total" },
              { label: "Clean", field: "clean" },
              { label: "Flagged", field: "flagged" },
            ],
          },
        },
      ],
    },
  ],
};

function useQueryParam(name: string): string | null {
  const search = useSearch();
  return useMemo(() => {
    const params = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
    return params.get(name);
  }, [search, name]);
}

async function createExecuteJob(studyId: string, executionDate: string): Promise<string> {
  const resp = await fetch("/api/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      type: "execute",
      studyId,
      payload: {
        spec: GOLDEN_SPEC,
        window: { preset: "execution_date", executionDate },
      },
    }),
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(text || `HTTP ${resp.status}`);
  }
  const body = (await resp.json()) as { jobId: string };
  return body.jobId;
}

async function fetchJob(jobId: string): Promise<JobStatus> {
  const resp = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`);
  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status}`);
  }
  return (await resp.json()) as JobStatus;
}

function ComponentView({
  component,
}: {
  component: NonNullable<ExecuteResult["sections"]>[number]["components"][number];
}) {
  if (component.error) {
    return (
      <p className="text-sm text-destructive">
        {component.id}: {component.error}
      </p>
    );
  }
  const data = component.data;
  if (component.type === "kpi_group" && data && typeof data === "object" && !Array.isArray(data)) {
    const entries = Object.entries(data as Record<string, unknown>);
    return (
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="text-left border-b">
            <th className="py-1 pr-4">Metric</th>
            <th className="py-1">Value</th>
          </tr>
        </thead>
        <tbody>
          {entries.map(([k, v]) => (
            <tr key={k} className="border-b border-border/60">
              <td className="py-1 pr-4">{k}</td>
              <td className="py-1 font-mono">{String(v)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }
  if (Array.isArray(data) && data.length > 0 && typeof data[0] === "object") {
    const rows = data as Record<string, unknown>[];
    const keys = Object.keys(rows[0]);
    return (
      <div className="overflow-x-auto">
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="text-left border-b">
              {keys.map((k) => (
                <th key={k} className="py-1 pr-3">
                  {k}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i} className="border-b border-border/60">
                {keys.map((k) => (
                  <td key={k} className="py-1 pr-3 font-mono">
                    {String(row[k] ?? "")}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  return (
    <pre className="text-xs bg-muted/40 p-3 rounded overflow-auto max-h-64">
      {JSON.stringify(data, null, 2)}
    </pre>
  );
}

export default function ReportExecutePreview() {
  const { activeStudyId } = useStudy();
  const jobFromUrl = useQueryParam("job");
  const [, setLocation] = useLocation();
  const [jobId, setJobId] = useState<string | null>(jobFromUrl);
  const [job, setJob] = useState<JobStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [executionDate, setExecutionDate] = useState("2026-09-12");

  useEffect(() => {
    setJobId(jobFromUrl);
  }, [jobFromUrl]);

  const poll = useCallback(async (id: string) => {
    const status = await fetchJob(id);
    setJob(status);
    return status;
  }, []);

  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    let delay = 2000;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const tick = async () => {
      try {
        const status = await poll(jobId);
        if (cancelled) return;
        if (status.status === "pending" || status.status === "processing") {
          timer = setTimeout(tick, delay);
          delay = Math.min(delay * 1.5, 10000);
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      }
    };
    void tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [jobId, poll]);

  const runExecute = async () => {
    if (!activeStudyId) return;
    setBusy(true);
    setError(null);
    setJob(null);
    try {
      const id = await createExecuteJob(activeStudyId, executionDate);
      setJobId(id);
      setLocation(`/reports/execute-preview?job=${encodeURIComponent(id)}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const result = job?.result;

  return (
    <Layout>
      <Header
        title="Execute preview"
        description="Enqueue an execute job and render the hydrated ExecuteResult JSON."
      />
      <RequireActiveStudy>
        <div className="p-4 md:p-6 space-y-4 max-w-4xl">
          <div className="flex flex-wrap items-end gap-3">
            <label className="text-sm space-y-1">
              <span className="text-muted-foreground">Execution date</span>
              <input
                className="block border rounded px-2 py-1.5 text-sm bg-background"
                value={executionDate}
                onChange={(e) => setExecutionDate(e.target.value)}
              />
            </label>
            <Button size="sm" disabled={!activeStudyId || busy} onClick={() => void runExecute()}>
              {busy ? "Enqueueing…" : "Run execute job"}
            </Button>
            {jobId ? (
              <span className="text-xs text-muted-foreground font-mono">job={jobId}</span>
            ) : null}
          </div>

          {error ? <p className="text-sm text-destructive">{error}</p> : null}
          {job?.error ? <p className="text-sm text-destructive">{job.error}</p> : null}
          {job && (job.status === "pending" || job.status === "processing") ? (
            <p className="text-sm text-muted-foreground">Status: {job.status}…</p>
          ) : null}

          {result ? (
            <div className="space-y-6">
              <div>
                <h2 className="text-lg font-medium">{result.title ?? "Result"}</h2>
                {result.window ? (
                  <p className="text-sm text-muted-foreground">
                    Window {result.window.from} → {result.window.to}
                  </p>
                ) : null}
                {result.artifacts?.pdf ? (
                  <a className="text-sm underline" href={result.artifacts.pdf}>
                    PDF download
                  </a>
                ) : null}
              </div>
              {(result.sections ?? []).map((section) => (
                <section key={section.id} className="space-y-3">
                  <h3 className="text-base font-medium border-b pb-1">{section.title}</h3>
                  {section.components.map((c) => (
                    <div key={c.id} className="space-y-1">
                      <p className="text-xs text-muted-foreground font-mono">
                        {c.id} · {c.type}
                      </p>
                      <ComponentView component={c} />
                    </div>
                  ))}
                </section>
              ))}
            </div>
          ) : null}
        </div>
      </RequireActiveStudy>
    </Layout>
  );
}
