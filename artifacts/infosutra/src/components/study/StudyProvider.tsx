import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { studiesApi, type Study } from "@/lib/studies-api";

const STORAGE_KEY = "infosutra.activeStudyId";

type StudyContextValue = {
  studies: Study[];
  activeStudy: Study | null;
  activeStudyId: string | null;
  setActiveStudyId: (id: string | null) => void;
  isLoading: boolean;
  error: string | null;
  refetch: () => void;
};

const StudyContext = createContext<StudyContextValue | null>(null);

export function StudyProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient();
  const [activeStudyId, setActiveStudyIdState] = useState<string | null>(() => {
    if (typeof window === "undefined") return null;
    return localStorage.getItem(STORAGE_KEY);
  });

  const studiesQuery = useQuery({
    queryKey: ["studies"],
    queryFn: () => studiesApi.list(),
  });

  const studies = studiesQuery.data ?? [];

  // Prefer a valid stored study; otherwise pick the first study so the app
  // operates study-first (workspace), not form-first.
  useEffect(() => {
    if (!studies.length) {
      if (activeStudyId) {
        setActiveStudyIdState(null);
        localStorage.removeItem(STORAGE_KEY);
      }
      return;
    }
    if (activeStudyId && studies.some((s) => s.id === activeStudyId)) return;
    const preferred = studies[0];
    setActiveStudyIdState(preferred.id);
    localStorage.setItem(STORAGE_KEY, preferred.id);
  }, [studies, activeStudyId]);

  const setActiveStudyId = useCallback((id: string | null) => {
    setActiveStudyIdState(id);
    if (id) localStorage.setItem(STORAGE_KEY, id);
    else localStorage.removeItem(STORAGE_KEY);
  }, []);

  const activeStudy = useMemo(
    () => studies.find((s) => s.id === activeStudyId) ?? null,
    [studies, activeStudyId],
  );

  const value: StudyContextValue = {
    studies,
    activeStudy,
    activeStudyId,
    setActiveStudyId,
    isLoading: studiesQuery.isLoading,
    error: studiesQuery.error ? (studiesQuery.error as Error).message : null,
    refetch: () => {
      queryClient.invalidateQueries({ queryKey: ["studies"] });
    },
  };

  return <StudyContext.Provider value={value}>{children}</StudyContext.Provider>;
}

export function useStudy() {
  const ctx = useContext(StudyContext);
  if (!ctx) {
    throw new Error("useStudy must be used within StudyProvider");
  }
  return ctx;
}

/** Safe for components that may render outside provider during tests. */
export function useOptionalStudy() {
  return useContext(StudyContext);
}
