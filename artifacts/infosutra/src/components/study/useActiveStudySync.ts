import { useCallback, useState, useSyncExternalStore } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  getGetDashboardActivityQueryKey,
  getGetDashboardSummaryQueryKey,
  getGetDqaByProjectQueryKey,
  getGetProjectsQueryKey,
  getGetStudiesQueryKey,
  getGetSubmissionTrendsQueryKey,
  getGetSubmissionsQueryKey,
  syncProject,
  syncProjects,
} from "@workspace/api-client-react";
import { pollJobResult, type SyncResultSummary } from "@/lib/jobs";
import { useStudy } from "@/components/study/StudyProvider";

/** Max time the Sync button stays disabled if a request never settles. */
const SYNC_UI_TIMEOUT_MS = 10 * 60 * 1000;

let syncBusy = false;
const busyListeners = new Set<() => void>();

function emitBusy() {
  busyListeners.forEach((listener) => listener());
}

function setSyncBusy(next: boolean) {
  if (syncBusy === next) return;
  syncBusy = next;
  emitBusy();
}

function subscribeBusy(listener: () => void) {
  busyListeners.add(listener);
  return () => {
    busyListeners.delete(listener);
  };
}

/** Shared busy flag for all Sync-from-Kobo buttons. */
export function useSyncProjectsPending(): boolean {
  return useSyncExternalStore(subscribeBusy, () => syncBusy, () => false);
}

function invalidateAfterSync(
  queryClient: ReturnType<typeof useQueryClient>,
  studyId: string | null | undefined,
) {
  void queryClient.invalidateQueries({ queryKey: getGetProjectsQueryKey() });
  if (studyId) {
    void queryClient.invalidateQueries({
      queryKey: getGetProjectsQueryKey({ studyId }),
    });
  }
  void queryClient.invalidateQueries({ queryKey: getGetStudiesQueryKey() });
  void queryClient.invalidateQueries({ queryKey: getGetDashboardSummaryQueryKey() });
  void queryClient.invalidateQueries({ queryKey: getGetDashboardActivityQueryKey() });
  void queryClient.invalidateQueries({ queryKey: getGetSubmissionTrendsQueryKey() });
  void queryClient.invalidateQueries({ queryKey: getGetDqaByProjectQueryKey() });
  void queryClient.invalidateQueries({ queryKey: getGetSubmissionsQueryKey() });
}

async function waitForSyncJob(jobId: string): Promise<SyncResultSummary> {
  return pollJobResult<SyncResultSummary>(jobId, {
    intervalMs: 1000,
    timeoutMs: SYNC_UI_TIMEOUT_MS,
  });
}

/** Run a study sync via job enqueue + poll; no-ops if one is already busy. */
export function useRunStudySync() {
  const queryClient = useQueryClient();
  const isPending = useSyncProjectsPending();
  const [error, setError] = useState<Error | null>(null);
  const [data, setData] = useState<SyncResultSummary | undefined>(undefined);

  const run = useCallback(
    async (studyId: string) => {
      if (!studyId || syncBusy) return undefined;
      setSyncBusy(true);
      setError(null);
      const safety = window.setTimeout(() => setSyncBusy(false), SYNC_UI_TIMEOUT_MS);
      try {
        const created = await syncProjects({ studyId });
        const result = await waitForSyncJob(created.jobId);
        setData(result);
        invalidateAfterSync(queryClient, studyId);
        return result;
      } catch (err) {
        const next = err instanceof Error ? err : new Error(String(err));
        setError(next);
        throw next;
      } finally {
        window.clearTimeout(safety);
        setSyncBusy(false);
      }
    },
    [queryClient],
  );

  const reset = useCallback(() => {
    setError(null);
    setData(undefined);
  }, []);

  return { run, isPending, error, data, reset };
}

/** Single-form sync via job enqueue + poll. */
export function useRunProjectSync() {
  const queryClient = useQueryClient();
  const isPending = useSyncProjectsPending();
  const [error, setError] = useState<Error | null>(null);

  const run = useCallback(
    async (projectId: string, studyId?: string | null) => {
      if (!projectId || syncBusy) return undefined;
      setSyncBusy(true);
      setError(null);
      const safety = window.setTimeout(() => setSyncBusy(false), SYNC_UI_TIMEOUT_MS);
      try {
        const created = await syncProject(projectId);
        const result = await waitForSyncJob(created.jobId);
        invalidateAfterSync(queryClient, studyId);
        return result;
      } catch (err) {
        const next = err instanceof Error ? err : new Error(String(err));
        setError(next);
        throw next;
      } finally {
        window.clearTimeout(safety);
        setSyncBusy(false);
      }
    },
    [queryClient],
  );

  return { run, isPending, error };
}

/** Shared Kobo sync for the active study (sidebar status + Forms/Studies). */
export function useActiveStudySync() {
  const { activeStudyId } = useStudy();
  const { run, isPending } = useRunStudySync();

  const trigger = () => {
    if (!activeStudyId) return;
    void run(activeStudyId);
  };

  return { trigger, isPending };
}
