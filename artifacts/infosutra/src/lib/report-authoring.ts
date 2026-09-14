export type AuthorStep = {
  id: string;
  title: string;
  status: "running" | "done" | "error";
  detail?: string;
};

export type AuthorQuestion = {
  id: string;
  kind: string;
  prompt: string;
  options?: Array<{ id?: string; label?: string; value?: string }>;
  fieldKey?: string;
};

export type AuthorMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  createdAt?: string;
  steps?: AuthorStep[];
};

export type AuthoringState = {
  status?: string;
  messages?: AuthorMessage[];
  pendingQuestions?: AuthorQuestion[];
  promptText?: string;
};

export type TemplateAuthorDetail = {
  id: string;
  name: string;
  description?: string;
  studyId?: string;
  reportKind?: string;
  status?: string;
  versionCount?: number;
  currentVersion?: number;
  promptText?: string;
  defaultExecutionDate?: string | null;
  spec?: Record<string, unknown>;
  workingSpec?: Record<string, unknown> | null;
  authoring?: AuthoringState | null;
  versions?: Array<{
    id: string;
    version: number;
    source: string;
    notes?: string;
  }>;
};

export type ExecuteJobStatus = {
  jobId: string;
  type: string;
  status: string;
  result?: {
    reportId?: string;
    title?: string;
    window?: { from?: string; to?: string };
    sections?: Array<{
      id: string;
      title: string;
      components: Array<{
        id: string;
        type: string;
        data?: unknown;
        error?: string;
      }>;
    }>;
  } | null;
  error?: string | null;
};

async function readError(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
    if (typeof body?.message === "string") return body.message;
  } catch {
    /* ignore */
  }
  return `HTTP ${response.status}`;
}

export async function createTemplateDraft(studyId: string): Promise<TemplateAuthorDetail> {
  const response = await fetch("/api/report-templates/draft", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ studyId, name: "Untitled template" }),
  });
  if (!response.ok) throw new Error(await readError(response));
  return response.json() as Promise<TemplateAuthorDetail>;
}

export async function getTemplateAuthor(templateId: string): Promise<TemplateAuthorDetail> {
  const response = await fetch(`/api/report-templates/${encodeURIComponent(templateId)}`);
  if (!response.ok) throw new Error(await readError(response));
  return response.json() as Promise<TemplateAuthorDetail>;
}

export async function streamAuthorTurn(
  templateId: string,
  payload: { message: string; questionId?: string; value?: string },
  handlers: {
    signal?: AbortSignal;
    onStep?: (step: AuthorStep) => void;
    onAssistant?: (text: string, steps?: AuthorStep[]) => void;
    onQuestions?: (questions: AuthorQuestion[]) => void;
    onSpec?: (spec: Record<string, unknown>) => void;
  } = {},
): Promise<{ status?: string; name?: string }> {
  const response = await fetch(
    `/api/report-templates/${encodeURIComponent(templateId)}/author/stream`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      },
      body: JSON.stringify(payload),
      signal: handlers.signal,
    },
  );
  if (!response.ok) throw new Error(await readError(response));
  if (!response.body) throw new Error("Authoring stream returned an empty body");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let streamError: string | null = null;
  let done: { status?: string; name?: string } = {};

  const dispatch = (eventName: string, dataRaw: string) => {
    let data: Record<string, unknown> = {};
    try {
      data = JSON.parse(dataRaw) as Record<string, unknown>;
    } catch {
      return;
    }
    if (eventName === "step") {
      handlers.onStep?.({
        id: String(data.id || "step"),
        title: String(data.title || "Working"),
        status: (data.status as AuthorStep["status"]) || "running",
        detail: data.detail ? String(data.detail) : undefined,
      });
      return;
    }
    if (eventName === "assistant") {
      handlers.onAssistant?.(String(data.text || ""), data.steps as AuthorStep[] | undefined);
      return;
    }
    if (eventName === "questions") {
      handlers.onQuestions?.((data.questions as AuthorQuestion[]) || []);
      return;
    }
    if (eventName === "spec" && data.spec && typeof data.spec === "object") {
      handlers.onSpec?.(data.spec as Record<string, unknown>);
      return;
    }
    if (eventName === "done") {
      done = { status: data.status ? String(data.status) : undefined, name: data.templateName ? String(data.templateName) : undefined };
      return;
    }
    if (eventName === "error") {
      streamError = String(data.message || "Authoring stream failed");
    }
  };

  while (true) {
    const { done: finished, value } = await reader.read();
    if (finished) break;
    buffer += decoder.decode(value, { stream: true });
    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) >= 0) {
      const chunk = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      let eventName = "message";
      const dataLines: string[] = [];
      for (const line of chunk.split("\n")) {
        if (line.startsWith("event:")) eventName = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
      }
      if (dataLines.length) dispatch(eventName, dataLines.join("\n"));
    }
  }

  if (streamError) throw new Error(streamError);
  return done;
}

export async function createSpecExecuteJob(
  studyId: string,
  spec: Record<string, unknown>,
  opts: { title?: string; executionDate?: string | null } = {},
): Promise<string> {
  const window: Record<string, string> = { preset: "execution_date" };
  if (opts.executionDate) window.executionDate = opts.executionDate;
  const response = await fetch("/api/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      type: "execute",
      studyId,
      payload: {
        spec,
        title: opts.title,
        window,
        // Live authoring preview — do not create a Reports-tab row.
        preview: true,
      },
    }),
  });
  if (!response.ok) throw new Error(await readError(response));
  const body = (await response.json()) as { jobId: string };
  return body.jobId;
}

export async function pollExecuteJob(
  jobId: string,
  opts: { signal?: AbortSignal; intervalMs?: number; timeoutMs?: number } = {},
): Promise<ExecuteJobStatus> {
  const interval = opts.intervalMs ?? 700;
  const timeoutMs = opts.timeoutMs ?? 3 * 60 * 1000;
  const started = Date.now();
  for (;;) {
    if (opts.signal?.aborted) throw new DOMException("Aborted", "AbortError");
    if (Date.now() - started > timeoutMs) {
      throw new Error("Timed out waiting for the execute job");
    }
    const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`, {
      signal: opts.signal,
    });
    if (!response.ok) throw new Error(await readError(response));
    const body = (await response.json()) as ExecuteJobStatus;
    if (body.status === "completed" || body.status === "failed") return body;
    await new Promise((r) => setTimeout(r, interval));
  }
}
