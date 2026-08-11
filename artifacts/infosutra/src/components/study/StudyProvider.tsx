import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "wouter";
import {
  getGetStudiesQueryKey,
  useGetStudies,
  type StudyOut,
} from "@workspace/api-client-react";

const STORAGE_KEY = "infosutra.activeStudyId";

type StudyContextValue = {
  studies: StudyOut[];
  activeStudy: StudyOut | null;
  activeStudyId: string | null;
  setActiveStudyId: (id: string | null) => void;
  isLoading: boolean;
  error: string | null;
  refetch: () => void;
};

const StudyContext = createContext<StudyContextValue | null>(null);

function readInitialStudyId(): string | null {
  if (typeof window === "undefined") return null;
  const fromUrl = new URLSearchParams(window.location.search).get("study");
  if (fromUrl) return fromUrl;
  return localStorage.getItem(STORAGE_KEY);
}

export function StudyProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const studyFromUrl = searchParams.get("study");

  const [activeStudyId, setActiveStudyIdState] = useState<string | null>(readInitialStudyId);

  const studiesQuery = useGetStudies();
  const studies = studiesQuery.data ?? [];

  const writeStudyParam = useCallback(
    (id: string | null) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (id) next.set("study", id);
          else next.delete("study");
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  // Shared URLs / browser back-forward: URL study wins when valid.
  useEffect(() => {
    if (!studyFromUrl || studyFromUrl === activeStudyId) return;
    if (studies.length > 0 && !studies.some((s) => s.id === studyFromUrl)) return;
    setActiveStudyIdState(studyFromUrl);
    localStorage.setItem(STORAGE_KEY, studyFromUrl);
  }, [studyFromUrl, studies, activeStudyId]);

  // Prefer a valid stored/URL study; otherwise pick the first study so the app
  // operates study-first (workspace), not form-first. Reflect selection in URL.
  useEffect(() => {
    if (!studies.length) {
      if (activeStudyId) {
        setActiveStudyIdState(null);
        localStorage.removeItem(STORAGE_KEY);
        if (studyFromUrl) writeStudyParam(null);
      }
      return;
    }

    if (activeStudyId && studies.some((s) => s.id === activeStudyId)) {
      localStorage.setItem(STORAGE_KEY, activeStudyId);
      if (studyFromUrl !== activeStudyId) writeStudyParam(activeStudyId);
      return;
    }

    const preferred =
      (studyFromUrl && studies.some((s) => s.id === studyFromUrl) ? studyFromUrl : null) ??
      studies[0].id;
    setActiveStudyIdState(preferred);
    localStorage.setItem(STORAGE_KEY, preferred);
    writeStudyParam(preferred);
  }, [studies, activeStudyId, studyFromUrl, writeStudyParam]);

  const setActiveStudyId = useCallback(
    (id: string | null) => {
      setActiveStudyIdState(id);
      if (id) localStorage.setItem(STORAGE_KEY, id);
      else localStorage.removeItem(STORAGE_KEY);
      writeStudyParam(id);
    },
    [writeStudyParam],
  );

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
      queryClient.invalidateQueries({ queryKey: getGetStudiesQueryKey() });
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
