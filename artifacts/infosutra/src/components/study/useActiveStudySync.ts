import { useQueryClient } from "@tanstack/react-query";
import {
  getGetDashboardActivityQueryKey,
  getGetDashboardSummaryQueryKey,
  getGetDqaByProjectQueryKey,
  getGetProjectsQueryKey,
  getGetStudiesQueryKey,
  getGetSubmissionTrendsQueryKey,
  getGetSubmissionsQueryKey,
  useSyncProjects,
} from "@workspace/api-client-react";
import { useStudy } from "@/components/study/StudyProvider";

/** Fire-and-forget Kobo sync for the active study. */
export function useActiveStudySync() {
  const queryClient = useQueryClient();
  const { activeStudyId } = useStudy();
  const sync = useSyncProjects({
    mutation: {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: getGetProjectsQueryKey() });
        queryClient.invalidateQueries({ queryKey: getGetStudiesQueryKey() });
        queryClient.invalidateQueries({ queryKey: getGetDashboardSummaryQueryKey() });
        queryClient.invalidateQueries({ queryKey: getGetDashboardActivityQueryKey() });
        queryClient.invalidateQueries({ queryKey: getGetSubmissionTrendsQueryKey() });
        queryClient.invalidateQueries({ queryKey: getGetDqaByProjectQueryKey() });
        queryClient.invalidateQueries({ queryKey: getGetSubmissionsQueryKey() });
      },
    },
  });

  const trigger = () => {
    if (!activeStudyId || sync.isPending) return;
    sync.mutate({ params: { studyId: activeStudyId } });
  };

  return { trigger, isPending: sync.isPending };
}
