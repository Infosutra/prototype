/** Study API helpers (not yet in generated client). */

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `HTTP ${response.status}`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export type StudyProject = {
  id: string;
  uid: string;
  name: string;
  toolCode?: string | null;
  submissionCount: number;
  syncStatus: string;
};

export type Study = {
  id: string;
  name: string;
  description?: string | null;
  startDate?: string | null;
  endDate?: string | null;
  timezone: string;
  targets: Record<string, number>;
  formMap: Array<{ toolCode?: string; projectUid: string; label?: string }>;
  dayNumber?: number | null;
  projectCount: number;
  submissionCount: number;
  projects: StudyProject[];
  createdAt?: string | null;
  updatedAt?: string | null;
};

export type StudyInput = {
  name: string;
  description?: string | null;
  startDate?: string | null;
  endDate?: string | null;
  timezone?: string;
  targets?: Record<string, number>;
  formMap?: Array<{ toolCode?: string; projectUid: string; label?: string }>;
};

export const studiesApi = {
  list: () => api<Study[]>("/api/studies"),
  get: (id: string) => api<Study>(`/api/studies/${encodeURIComponent(id)}`),
  create: (data: StudyInput) =>
    api<Study>("/api/studies", { method: "POST", body: JSON.stringify(data) }),
  update: (id: string, data: Partial<StudyInput>) =>
    api<Study>(`/api/studies/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    }),
  remove: (id: string) =>
    api<{ success: boolean }>(`/api/studies/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),
  assignProject: (studyId: string, projectId: string, toolCode?: string) =>
    api<Study>(`/api/studies/${encodeURIComponent(studyId)}/projects`, {
      method: "POST",
      body: JSON.stringify({ projectId, toolCode }),
    }),
  unassignProject: (studyId: string, projectId: string) =>
    api<Study>(
      `/api/studies/${encodeURIComponent(studyId)}/projects/${encodeURIComponent(projectId)}`,
      { method: "DELETE" },
    ),
};
