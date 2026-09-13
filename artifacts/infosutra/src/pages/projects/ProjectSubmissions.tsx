import { useEffect } from "react";
import { useFormRouteId } from "@/lib/use-form-route-id";
import { useStudy } from "@/components/study/StudyProvider";

/** Legacy `/forms/:id/submissions` → Data Explorer with that form selected. */
export default function ProjectSubmissions() {
  const projectId = useFormRouteId("submissions");
  const { activeStudyId } = useStudy();

  useEffect(() => {
    if (!projectId) return;
    const params = new URLSearchParams();
    params.set("projectId", projectId);
    if (activeStudyId) params.set("study", activeStudyId);
    const base = String(import.meta.env.BASE_URL || "/").replace(/\/$/, "");
    window.location.replace(`${base}/data?${params.toString()}`);
  }, [projectId, activeStudyId]);

  return (
    <div className="flex flex-1 items-center justify-center p-8 text-sm text-muted-foreground">
      Opening Data Explorer…
    </div>
  );
}
