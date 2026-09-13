/** Shared job polling for long-running API work (plan, sync, execute). */

import { getJob, type JobStatusOut } from "@workspace/api-client-react";

/** Job artifact shape written by the kobo_sync worker (camelCase). */
export type SyncResultSummary = {
  success: boolean;
  projectsSynced: number;
  submissionsFetched: number;
  newSubmissions: number;
  deletedSubmissions?: number;
  syncedAt: string;
  errors: string[];
};

export async function pollJob(
  jobId: string,
  opts: { signal?: AbortSignal; intervalMs?: number; timeoutMs?: number } = {},
): Promise<JobStatusOut> {
  const interval = opts.intervalMs ?? 800;
  const timeoutMs = opts.timeoutMs ?? 10 * 60 * 1000;
  const started = Date.now();

  for (;;) {
    if (opts.signal?.aborted) {
      throw new Error("Job polling cancelled");
    }
    if (Date.now() - started > timeoutMs) {
      throw new Error("Timed out waiting for job to finish");
    }
    const body = await getJob(jobId, { signal: opts.signal });
    if (body.status === "completed" || body.status === "failed") {
      return body;
    }
    await new Promise((r) => setTimeout(r, interval));
  }
}

export async function pollJobResult<T>(
  jobId: string,
  opts?: { signal?: AbortSignal; intervalMs?: number; timeoutMs?: number },
): Promise<T> {
  const body = await pollJob(jobId, opts);
  if (body.status === "failed") {
    throw new Error(body.error || "Job failed");
  }
  return body.result as T;
}
