/**
 * Shared helpers: plan job enqueue/poll + section cards for ReportSpec review.
 */
import React from "react";

export type PlanUnmapped = { userIntent: string; reason: string };
export type PlanJudgement = { faithful: boolean; issues: string[] };
export type PlanResult = {
  spec: Record<string, unknown>;
  unmapped: PlanUnmapped[];
  judgement: PlanJudgement;
};

type JobStatus = {
  jobId: string;
  type: string;
  status: string;
  result?: PlanResult | null;
  error?: string | null;
};

type SpecQuery = {
  entity?: string;
  window?: string;
  groupBy?: string[];
  measures?: Array<{ fn?: string }>;
};

type SpecComponent = {
  id?: string;
  type?: string;
  query?: SpecQuery;
};

type SpecSection = {
  id?: string;
  title?: string;
  components?: SpecComponent[];
};

export async function createPlanJob(
  studyId: string,
  instructions: string,
  currentSpec?: Record<string, unknown> | null,
): Promise<string> {
  const resp = await fetch("/api/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      type: "plan",
      studyId,
      payload: {
        instructions,
        ...(currentSpec ? { currentSpec } : {}),
      },
    }),
  });
  if (!resp.ok) {
    throw new Error((await resp.text()) || `HTTP ${resp.status}`);
  }
  const body = (await resp.json()) as { jobId: string };
  return body.jobId;
}

export async function pollPlanJob(
  jobId: string,
  opts: { signal?: AbortSignal; intervalMs?: number } = {},
): Promise<PlanResult> {
  const interval = opts.intervalMs ?? 800;
  for (;;) {
    if (opts.signal?.aborted) {
      throw new Error("Planning cancelled");
    }
    const resp = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`, {
      signal: opts.signal,
    });
    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status}`);
    }
    const body = (await resp.json()) as JobStatus;
    if (body.status === "completed") {
      if (!body.result?.spec) {
        throw new Error("Plan job completed without a spec");
      }
      return {
        spec: body.result.spec,
        unmapped: body.result.unmapped ?? [],
        judgement: body.result.judgement ?? { faithful: true, issues: [] },
      };
    }
    if (body.status === "failed") {
      throw new Error(body.error || "Plan job failed");
    }
    await new Promise((r) => setTimeout(r, interval));
  }
}

function querySummary(query: SpecQuery | undefined): string {
  if (!query) return "static / narrative";
  const parts: string[] = [];
  if (query.entity) parts.push(query.entity);
  if (query.window) parts.push(query.window);
  if (query.groupBy?.length) parts.push(`by ${query.groupBy.join(", ")}`);
  if (query.measures?.length) {
    parts.push(query.measures.map((m) => m.fn || "measure").join("+"));
  }
  return parts.join(" · ") || "query";
}

export function SectionCards({
  spec,
  unmapped,
  judgement,
}: {
  spec: Record<string, unknown> | null | undefined;
  unmapped?: PlanUnmapped[];
  judgement?: PlanJudgement | null;
}) {
  const sections = (Array.isArray(spec?.sections) ? spec?.sections : []) as SpecSection[];
  const title = typeof spec?.title === "string" ? spec.title : "Untitled report";

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-base font-semibold text-foreground">{title}</h3>
        {typeof spec?.subtitle === "string" && spec.subtitle ? (
          <p className="text-sm text-muted-foreground">{spec.subtitle}</p>
        ) : null}
      </div>

      {(unmapped?.length ?? 0) > 0 ? (
        <div className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-950 dark:text-amber-100">
          <p className="font-medium">Could not map {unmapped!.length} request(s)</p>
          <ul className="mt-1 list-disc space-y-1 pl-5">
            {unmapped!.map((item, i) => (
              <li key={`${item.userIntent}-${i}`}>
                <span className="font-medium">{item.userIntent}</span>
                {item.reason ? ` — ${item.reason}` : ""}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {judgement && judgement.faithful === false ? (
        <div className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm">
          <p className="font-medium">Judge flagged faithfulness issues</p>
          <ul className="mt-1 list-disc pl-5">
            {(judgement.issues || []).map((issue, i) => (
              <li key={i}>{issue}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {sections.length === 0 ? (
        <p className="text-sm text-muted-foreground">No sections yet.</p>
      ) : (
        <div className="space-y-3">
          {sections.map((section, idx) => {
            const components = section.components ?? [];
            const primary = components[0];
            const type = primary?.type || "section";
            const summary = querySummary(primary?.query);
            return (
              <div
                key={section.id || `section-${idx}`}
                className="border-b border-border/70 pb-3 last:border-0"
              >
                <div className="flex items-baseline justify-between gap-3">
                  <p className="font-medium text-foreground">
                    {section.title || section.id || `Section ${idx + 1}`}
                  </p>
                  <p className="text-xs uppercase tracking-wide text-muted-foreground">{type}</p>
                </div>
                <p className="mt-1 text-sm text-muted-foreground">{summary}</p>
                {components.length > 1 ? (
                  <p className="mt-1 text-xs text-muted-foreground">
                    +{components.length - 1} more component
                    {components.length - 1 === 1 ? "" : "s"}
                  </p>
                ) : null}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
