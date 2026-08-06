/** DQA Daily / reports API helpers (not yet in generated client). */

export type Report = {
  id: string;
  title: string;
  description: string;
  status: string;
  format: string;
  reportType?: string;
  studyId?: string | null;
  reportDate?: string | null;
  promptId?: string | null;
  promptName?: string | null;
  projectIds: string[];
  projectNames: string[];
  downloadUrl?: string | null;
  pageCount?: number | null;
  fileSizeKb?: number | null;
  generatedAt?: string | null;
  createdAt: string;
};

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    let detail = await response.text();
    try {
      const parsed = JSON.parse(detail);
      detail = parsed.detail || parsed.error || parsed.message || detail;
    } catch {
      /* keep text */
    }
    throw new Error(detail || `HTTP ${response.status}`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const reportsApi = {
  list: (params?: { studyId?: string; reportType?: string }) => {
    const q = new URLSearchParams();
    if (params?.studyId) q.set("studyId", params.studyId);
    if (params?.reportType) q.set("reportType", params.reportType);
    const suffix = q.toString() ? `?${q}` : "";
    return api<Report[]>(`/api/reports${suffix}`);
  },
  generateDqaDaily: (body: {
    studyId?: string;
    reportDate?: string;
    sendEmail?: boolean;
    runAi?: boolean;
  }) =>
    api<Report>("/api/reports/dqa-daily", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  generateDqaFinal: (body: {
    studyId?: string;
    sendEmail?: boolean;
    runAi?: boolean;
  }) =>
    api<Report>("/api/reports/dqa-final", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  remove: (id: string) =>
    api<{ success: boolean }>(`/api/reports/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),
  share: (id: string, recipients: string[]) =>
    api<{ success: boolean; recipientsCount: number; message: string }>(
      `/api/reports/${encodeURIComponent(id)}/share`,
      {
        method: "POST",
        body: JSON.stringify({
          recipients,
          subject: "DQA Daily",
          message: null,
        }),
      },
    ),
  downloadUrl: (id: string, format: "pdf" | "docx" = "pdf") =>
    `/api/reports/${encodeURIComponent(id)}/download?format=${format}`,
  previewUrl: (id: string) => `/api/reports/${encodeURIComponent(id)}/preview`,
};
