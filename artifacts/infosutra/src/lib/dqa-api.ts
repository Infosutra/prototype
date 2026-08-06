/** Lightweight fetch helpers for DQA endpoints (not yet in generated client). */

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

export type DqaSummary = {
  projectId: string | null;
  totalSubmissions: number;
  flaggedSubmissions: number;
  flaggedPct: number;
  redFlags: number;
  amberFlags: number;
  byRule: Array<{ ruleId: string; title: string; severity: string; count: number }>;
};

export type DqaFlag = {
  id: string;
  submissionId: string;
  projectId: string;
  ruleId: string;
  severity: string;
  title: string;
  message: string;
  details?: Record<string, unknown> | null;
  evaluatedAt: string;
  enumerator?: string | null;
  projectName?: string | null;
  koboId?: string | null;
  submittedAt?: string | null;
};

export type EnumeratorStat = {
  enumerator: string;
  submissions: number;
  flagged: number;
  flaggedPct: number;
  redFlags: number;
  amberFlags: number;
  medianDurationMinutes?: number | null;
};

export type FormField = {
  name: string;
  type: string;
  label: string;
  listName?: string | null;
  choices: Array<{ name: string; label: string }>;
};

export type RulePack = {
  projectId: string;
  pack: {
    id?: string;
    project_uids?: string[];
    join_key?: string;
    fields?: Record<string, string>;
    thresholds?: Record<string, number>;
    rules?: Array<Record<string, unknown>>;
    [key: string]: unknown;
  };
};

export type TriangulationLink = {
  submissionId?: string | null;
  koboId?: string | null;
  enumerator?: string | null;
  submittedAt?: string | null;
  projectName?: string | null;
};

export type TriangulationPracticeStat = {
  id: string;
  label: string;
  claimedCount: number;
  observedCount: number;
  n: number;
  claimedPct: number;
  observedPct: number;
  concordancePct: number;
  gapPct: number;
};

export type TriangulationView = {
  id: string;
  title: string;
  description?: string | null;
  mismatchCount: number;
  practices?: TriangulationPracticeStat[];
  rows: Array<{
    udise: string;
    schoolName?: string | null;
    facility?: TriangulationLink | null;
    teacher?: TriangulationLink | null;
    parent?: TriangulationLink | null;
    teacherHasCwd?: boolean | null;
    parentReportsDisability?: boolean | null;
    claimedPractices?: string[];
    observedPractices?: string[];
    practiceGap?: number | null;
    schoolMeetings?: number | null;
    schoolCwdDiscussed?: boolean | null;
    schoolGovernanceActive?: boolean | null;
    parentAttendedPta?: boolean | null;
    parentCwdIssues?: boolean | null;
    mismatch: boolean;
  }>;
};

export type ProjectDqaStat = {
  projectId: string;
  projectName: string;
  totalSubmissions: number;
  cleanSubmissions: number;
  amberSubmissions: number;
  redSubmissions: number;
  redFlags: number;
  amberFlags: number;
  flaggedPct: number;
};

export type GridColumn = {
  key: string;
  code: string;
  label: string;
  type: string;
  filled: number;
  flagged: number;
  extra: boolean;
};

export type GridFlagRef = {
  id: string;
  ruleId: string;
  severity: string;
  title: string;
  message: string;
};

export type GridCell = {
  value: string;
  severity?: "red" | "amber" | null;
  flags: GridFlagRef[];
};

export type GridRow = {
  submissionId: string;
  displayId: string;
  koboId?: string | null;
  enumerator: string;
  submittedAt: string;
  status: string;
  location?: string | null;
  severity?: "red" | "amber" | null;
  redFlags: number;
  amberFlags: number;
  cells: Record<string, GridCell>;
  rowFlags: GridFlagRef[];
};

export type SubmissionGrid = {
  projectId: string;
  projectName: string;
  labelLanguage?: string | null;
  columns: GridColumn[];
  rows: GridRow[];
  total: number;
  page: number;
  limit: number;
  totalPages: number;
};

export const dqaApi = {
  summary: (projectId?: string, studyId?: string) => {
    const q = new URLSearchParams();
    if (projectId) q.set("projectId", projectId);
    if (studyId) q.set("studyId", studyId);
    const qs = q.toString();
    return api<DqaSummary>(`/api/dqa/summary${qs ? `?${qs}` : ""}`);
  },
  byProject: (studyId?: string) =>
    api<ProjectDqaStat[]>(
      `/api/dqa/by-project${studyId ? `?studyId=${encodeURIComponent(studyId)}` : ""}`,
    ),
  flags: (params?: {
    projectId?: string;
    studyId?: string;
    submissionId?: string;
    ruleId?: string;
    severity?: string;
  }) => {
    const q = new URLSearchParams();
    if (params?.projectId) q.set("projectId", params.projectId);
    if (params?.studyId) q.set("studyId", params.studyId);
    if (params?.submissionId) q.set("submissionId", params.submissionId);
    if (params?.ruleId) q.set("ruleId", params.ruleId);
    if (params?.severity) q.set("severity", params.severity);
    const qs = q.toString();
    return api<DqaFlag[]>(`/api/dqa/flags${qs ? `?${qs}` : ""}`);
  },
  enumerators: (projectId?: string, studyId?: string) => {
    const q = new URLSearchParams();
    if (projectId) q.set("projectId", projectId);
    if (studyId) q.set("studyId", studyId);
    const qs = q.toString();
    return api<EnumeratorStat[]>(`/api/dqa/enumerators${qs ? `?${qs}` : ""}`);
  },
  recompute: (projectId?: string) =>
    api<{ projectId: string | null; submissions: number; flaggedSubmissions: number; flags: number }>(
      `/api/dqa/recompute${projectId ? `?projectId=${encodeURIComponent(projectId)}` : ""}`,
      { method: "POST" },
    ),
  triangulation: (viewId = "TR-5", studyId?: string) => {
    const q = new URLSearchParams();
    if (studyId) q.set("studyId", studyId);
    const qs = q.toString();
    return api<TriangulationView>(
      `/api/dqa/triangulation/${encodeURIComponent(viewId)}${qs ? `?${qs}` : ""}`,
    );
  },
  formFields: (projectId: string) => api<FormField[]>(`/api/projects/${projectId}/form-fields`),
  dataGrid: (
    projectId: string,
    params?: { page?: number; limit?: number; severity?: string; enumerator?: string },
  ) => {
    const q = new URLSearchParams();
    if (params?.page) q.set("page", String(params.page));
    if (params?.limit) q.set("limit", String(params.limit));
    if (params?.severity) q.set("severity", params.severity);
    if (params?.enumerator) q.set("enumerator", params.enumerator);
    const qs = q.toString();
    return api<SubmissionGrid>(
      `/api/projects/${projectId}/data-grid${qs ? `?${qs}` : ""}`,
    );
  },
  getRulePack: (projectId: string) => api<RulePack>(`/api/projects/${projectId}/rule-pack`),
  putRulePack: (projectId: string, pack: RulePack["pack"]) =>
    api<RulePack>(`/api/projects/${projectId}/rule-pack`, {
      method: "PUT",
      body: JSON.stringify({ pack }),
    }),
};
