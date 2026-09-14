import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  getGetReportTemplateQueryKey,
  getListReportTemplatesQueryKey,
  useDeleteReportTemplate,
  useListReportTemplates,
  useRestoreReportTemplateVersion,
  useUpdateReportTemplate,
  useUpdateReportTemplatePrompt,
  type ReportTemplateOut,
} from "@workspace/api-client-react";
import { Layout } from "@/components/layout/Layout";
import { Header } from "@/components/layout/Header";
import { ExecuteResultPreview } from "@/components/reports/ExecuteResultPreview";
import { SectionCards } from "@/components/reports/SectionCards";
import { RequireActiveStudy } from "@/components/study/RequireActiveStudy";
import { useStudy } from "@/components/study/StudyProvider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Check,
  ChevronDown,
  ChevronRight,
  Code2,
  Eye,
  FileJson2,
  History,
  Loader2,
  Plus,
  Send,
  Trash2,
} from "lucide-react";
import {
  createSpecExecuteJob,
  createTemplateDraft,
  getTemplateAuthor,
  pollExecuteJob,
  streamAuthorTurn,
  type AuthorMessage,
  type AuthorQuestion,
  type AuthorStep,
  type ExecuteJobStatus,
  type TemplateAuthorDetail,
} from "@/lib/report-authoring";

function mergeStep(steps: AuthorStep[], incoming: AuthorStep): AuthorStep[] {
  const index = steps.findIndex((row) => row.id === incoming.id);
  if (index < 0) return [...steps, incoming];
  const next = [...steps];
  next[index] = { ...next[index], ...incoming };
  return next;
}

/** Drop trailing question prompts already shown on the option card. */
function assistantTextWithoutQuestionEcho(
  content: string,
  pending: AuthorQuestion[],
): string {
  let out = content.trimEnd();
  for (const question of pending) {
    const prompt = String(question.prompt || "").trim();
    if (!prompt) continue;
    if (out.endsWith(prompt)) {
      out = out.slice(0, -prompt.length).trimEnd();
      continue;
    }
    // Older turns sometimes put a blank line before the confirm prompt.
    const spaced = `\n\n${prompt}`;
    if (out.endsWith(spaced)) {
      out = out.slice(0, -spaced.length).trimEnd();
    }
  }
  return out;
}

function studyExecutionDate(study: {
  startDate?: string | null;
  dayNumber?: number | null;
} | null): string | undefined {
  if (!study?.startDate || study.dayNumber == null || study.dayNumber < 1) return undefined;
  const parts = study.startDate.slice(0, 10).split("-").map(Number);
  if (parts.length !== 3 || parts.some((n) => !Number.isFinite(n))) return undefined;
  const [y, m, d] = parts;
  const date = new Date(Date.UTC(y, m - 1, d));
  date.setUTCDate(date.getUTCDate() + (study.dayNumber - 1));
  return date.toISOString().slice(0, 10);
}

function ProgressTrail({
  steps,
  live,
}: {
  steps: AuthorStep[];
  live?: boolean;
}) {
  const [open, setOpen] = useState(true);
  useEffect(() => {
    if (live) setOpen(true);
  }, [live]);
  if (!steps.length) return null;
  const running = steps.some((step) => step.status === "running");
  const failed = steps.some((step) => step.status === "error");
  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger className="flex w-full items-center gap-2 rounded-md border border-border/70 bg-muted/40 px-3 py-2 text-left text-xs text-muted-foreground hover:bg-muted/70">
        {running ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin shrink-0" />
        ) : (
          <Check className="h-3.5 w-3.5 shrink-0" />
        )}
        <span className="flex-1 font-medium text-foreground">
          {running ? "Working" : failed ? "Stopped with an error" : "Done"}
        </span>
        {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
      </CollapsibleTrigger>
      <CollapsibleContent className="mt-1 space-y-1 border-l border-border/70 ml-3 pl-3 py-1">
        {steps.map((step) => (
          <div key={step.id} className="text-xs">
            <div className="flex items-center gap-2 text-foreground">
              {step.status === "running" ? (
                <Loader2 className="h-3 w-3 animate-spin shrink-0" />
              ) : step.status === "error" ? (
                <span className="text-destructive">!</span>
              ) : (
                <Check className="h-3 w-3 shrink-0 text-muted-foreground" />
              )}
              <span>{step.title}</span>
            </div>
            {step.detail ? (
              <p className="ml-5 mt-0.5 text-muted-foreground whitespace-pre-wrap">{step.detail}</p>
            ) : null}
          </div>
        ))}
      </CollapsibleContent>
    </Collapsible>
  );
}

function isFreeTextOption(value: string, label: string): boolean {
  const hay = `${value} ${label}`.toLowerCase();
  return (
    /\b(clarify|retry|explain)\b/.test(hay) ||
    /i'?ll clarify|i'?ll explain|something else|tell me more/.test(hay)
  );
}

export default function ReportTemplates() {
  const { activeStudyId, activeStudy } = useStudy();
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<TemplateAuthorDetail | null>(null);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [liveSteps, setLiveSteps] = useState<AuthorStep[]>([]);
  const [liveAssistant, setLiveAssistant] = useState("");
  const [pendingQuestions, setPendingQuestions] = useState<AuthorQuestion[]>([]);
  const [awaitingClarifyFor, setAwaitingClarifyFor] = useState<string | null>(null);
  const [previewBusy, setPreviewBusy] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewResult, setPreviewResult] = useState<ExecuteJobStatus["result"]>(null);
  const abortRef = useRef<AbortController | null>(null);
  const previewAbortRef = useRef<AbortController | null>(null);
  const chatEndRef = useRef<HTMLDivElement | null>(null);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);
  const lastPreviewKeyRef = useRef<string>("");

  const listQuery = useListReportTemplates(
    { studyId: activeStudyId || undefined },
    { query: { enabled: Boolean(activeStudyId) } as never },
  );
  const templates = listQuery.data ?? [];
  const selected =
    templates.find((row) => row.id === selectedId) ??
    (selectedId === null ? templates[0] ?? null : null);
  const templateId = selected?.id || selectedId || "";

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const id = params.get("id");
    if (id) setSelectedId(id);
  }, []);

  useEffect(() => {
    if (!templateId) {
      setDetail(null);
      setPreviewResult(null);
      setPreviewError(null);
      lastPreviewKeyRef.current = "";
      return;
    }
    let cancelled = false;
    getTemplateAuthor(templateId)
      .then((row) => {
        if (cancelled) return;
        setDetail(row);
        setPendingQuestions(row.authoring?.pendingQuestions ?? []);
        setError(null);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [templateId]);

  const messages: AuthorMessage[] = detail?.authoring?.messages ?? [];
  const workingSpec =
    detail?.workingSpec ||
    (detail?.spec && Object.keys(detail.spec).length ? detail.spec : null);
  const hasUnsavedSpecChanges = useMemo(() => {
    if (!workingSpec) return false;
    // Never published — first save should create v1.
    if (!detail?.currentVersion) return true;
    const published = detail.spec;
    if (!published || !Object.keys(published).length) return true;
    return JSON.stringify(workingSpec) !== JSON.stringify(published);
  }, [workingSpec, detail?.currentVersion, detail?.spec]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, liveSteps, liveAssistant, pendingQuestions.length]);

  const runInlinePreview = useCallback(
    async (spec: Record<string, unknown>, title?: string, force = false) => {
      if (!activeStudyId || !spec || !Object.keys(spec).length) return;
      const key = JSON.stringify(spec);
      if (!force && key === lastPreviewKeyRef.current) return;
      lastPreviewKeyRef.current = key;
      previewAbortRef.current?.abort();
      const controller = new AbortController();
      previewAbortRef.current = controller;
      setPreviewBusy(true);
      setPreviewError(null);
      try {
        const executionDate =
          detail?.defaultExecutionDate || studyExecutionDate(activeStudy) || undefined;
        const jobId = await createSpecExecuteJob(activeStudyId, spec, {
          title: title || detail?.name,
          executionDate,
        });
        const job = await pollExecuteJob(jobId, { signal: controller.signal });
        if (controller.signal.aborted) return;
        if (job.status === "failed") {
          setPreviewResult(null);
          setPreviewError(job.error || "Preview failed");
          return;
        }
        setPreviewResult(job.result ?? null);
      } catch (err) {
        if ((err as Error).name === "AbortError") {
          // Aborted with no replacement (e.g. cleared by tab click) — allow a later retry.
          if (previewAbortRef.current === controller) {
            lastPreviewKeyRef.current = "";
          }
          return;
        }
        setPreviewResult(null);
        setPreviewError(err instanceof Error ? err.message : String(err));
      } finally {
        if (previewAbortRef.current === controller) {
          setPreviewBusy(false);
        }
      }
    },
    [activeStudyId, activeStudy, detail?.defaultExecutionDate, detail?.name],
  );

  useEffect(() => {
    if (!workingSpec || busy) return;
    void runInlinePreview(workingSpec, detail?.name);
  }, [workingSpec, busy, detail?.name, runInlinePreview]);

  // If preview was cleared/aborted (re-clicking the same template) while the spec
  // is unchanged, the effect above will not re-fire — kick a refresh.
  useEffect(() => {
    if (!workingSpec || busy || previewBusy || previewResult || previewError) return;
    const key = JSON.stringify(workingSpec);
    if (lastPreviewKeyRef.current === key) return;
    void runInlinePreview(workingSpec, detail?.name, true);
  }, [
    workingSpec,
    busy,
    previewBusy,
    previewResult,
    previewError,
    detail?.name,
    runInlinePreview,
  ]);

  const deleteMutation = useDeleteReportTemplate({
    mutation: {
      onSuccess: async () => {
        await queryClient.invalidateQueries({ queryKey: getListReportTemplatesQueryKey() });
        setSelectedId(null);
        setDetail(null);
        setPreviewResult(null);
      },
    },
  });

  const restoreMutation = useRestoreReportTemplateVersion({
    mutation: {
      onSuccess: async () => {
        if (!templateId) return;
        await queryClient.invalidateQueries({
          queryKey: getGetReportTemplateQueryKey(templateId),
        });
        const row = await getTemplateAuthor(templateId);
        setDetail(row);
        lastPreviewKeyRef.current = "";
      },
    },
  });

  const saveMutation = useUpdateReportTemplatePrompt({
    mutation: {
      onSuccess: async (result) => {
        if (result.status !== "ok") {
          setError(result.reason || "Could not save version");
          return;
        }
        setError(null);
        await queryClient.invalidateQueries({ queryKey: getListReportTemplatesQueryKey() });
        if (templateId) {
          const row = await getTemplateAuthor(templateId);
          setDetail(row);
        }
      },
      onError: (err) => setError(err.message),
    },
  });

  const renameMutation = useUpdateReportTemplate({
    mutation: {
      onSuccess: async () => {
        await queryClient.invalidateQueries({ queryKey: getListReportTemplatesQueryKey() });
      },
    },
  });

  const startDraft = async () => {
    if (!activeStudyId) {
      setError("Select an active study first.");
      return;
    }
    setError(null);
    try {
      const created = await createTemplateDraft(activeStudyId);
      await queryClient.invalidateQueries({ queryKey: getListReportTemplatesQueryKey() });
      setSelectedId(created.id);
      setDetail(created);
      setPendingQuestions(created.authoring?.pendingQuestions ?? []);
      setPreviewResult(null);
      setPreviewError(null);
      lastPreviewKeyRef.current = "";
      setDraft("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const send = async (text: string, answer?: { questionId?: string; value?: string }) => {
    const content = text.trim();
    if (!templateId || !content || busy) return;
    const questionId = answer?.questionId || awaitingClarifyFor || undefined;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setBusy(true);
    setError(null);
    setLiveSteps([]);
    setLiveAssistant("");
    setAwaitingClarifyFor(null);
    // Hide the previous question card immediately so it cannot stick under a new turn.
    setPendingQuestions([]);
    setDetail((prev) =>
      prev
        ? {
            ...prev,
            authoring: {
              ...prev.authoring,
              messages: [
                ...(prev.authoring?.messages ?? []),
                {
                  id: `local-${Date.now()}`,
                  role: "user",
                  content,
                  createdAt: new Date().toISOString(),
                },
              ],
            },
          }
        : prev,
    );
    setDraft("");
    try {
      let latestSpec: Record<string, unknown> | null = null;
      await streamAuthorTurn(
        templateId,
        {
          message: content,
          questionId,
          // Only send a canned option value when the user clicked a real choice.
          // Free-text clarifications should use the typed message as the answer.
          value: answer?.value,
        },
        {
          signal: controller.signal,
          onStep: (step) => setLiveSteps((rows) => mergeStep(rows, step)),
          onAssistant: (msg) => setLiveAssistant(msg),
          onQuestions: setPendingQuestions,
          onSpec: (spec) => {
            latestSpec = spec;
            setDetail((prev) => (prev ? { ...prev, workingSpec: spec, spec } : prev));
          },
        },
      );
      const row = await getTemplateAuthor(templateId);
      setDetail(row);
      setPendingQuestions(row.authoring?.pendingQuestions ?? []);
      await queryClient.invalidateQueries({ queryKey: getListReportTemplatesQueryKey() });
      const spec =
        latestSpec ||
        row.workingSpec ||
        (row.spec && Object.keys(row.spec).length ? row.spec : null);
      if (spec) {
        void runInlinePreview(spec, row.name, true);
      }
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        setError(err instanceof Error ? err.message : String(err));
      }
    } finally {
      setBusy(false);
      setLiveSteps([]);
      setLiveAssistant("");
    }
  };

  const beginClarify = (question: AuthorQuestion) => {
    setAwaitingClarifyFor(question.id || null);
    requestAnimationFrame(() => {
      composerRef.current?.focus();
    });
  };

  const chooseOption = (question: AuthorQuestion, option: NonNullable<AuthorQuestion["options"]>[number]) => {
    const value = String(option.value ?? option.id ?? "").trim();
    const label = String(option.label || value);
    if (isFreeTextOption(value, label)) {
      beginClarify(question);
      return;
    }
    void send(label, {
      questionId: question.id,
      value,
    });
  };

  const saveVersion = () => {
    if (!templateId || !workingSpec || !hasUnsavedSpecChanges) return;
    const prompt =
      detail?.authoring?.promptText ||
      messages
        .filter((row) => row.role === "user")
        .map((row) => row.content)
        .join("\n");
    saveMutation.mutate({
      templateId,
      data: {
        prompt: prompt || "Authored in chat",
        spec: workingSpec,
        commit: true,
        notes: "Saved from authoring chat",
      },
    });
  };

  return (
    <Layout>
      <RequireActiveStudy>
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        <Header
          title="Report templates"
          description="Chat to draft a spec. The live preview on the right updates after each reply so you can see how it maps."
          action={
            <Button onClick={() => void startDraft()} disabled={!activeStudyId}>
              <Plus className="mr-2 h-4 w-4" />
              New template
            </Button>
          }
        />

        <div className="flex min-h-0 flex-1 gap-3 overflow-hidden p-3 md:p-4">
          <aside className="hidden w-[200px] shrink-0 space-y-1 overflow-y-auto lg:block">
            {templates.map((row: ReportTemplateOut) => (
              <button
                key={row.id}
                type="button"
                onClick={() => {
                  const reselectSame = templateId === row.id;
                  abortRef.current?.abort();
                  setPendingQuestions([]);
                  setAwaitingClarifyFor(null);
                  setLiveSteps([]);
                  setLiveAssistant("");
                  setPreviewError(null);
                  setError(null);
                  if (reselectSame) {
                    // Same tab again: load/spec effects do not re-fire — force a fresh preview.
                    setPreviewResult(null);
                    lastPreviewKeyRef.current = "";
                    if (workingSpec) {
                      void runInlinePreview(workingSpec, row.name, true);
                    } else {
                      previewAbortRef.current?.abort();
                    }
                    return;
                  }
                  previewAbortRef.current?.abort();
                  setPreviewResult(null);
                  lastPreviewKeyRef.current = "";
                  setSelectedId(row.id);
                }}
                className={`w-full rounded-md border px-3 py-2 text-left text-sm ${
                  templateId === row.id
                    ? "border-foreground/30 bg-muted"
                    : "border-transparent hover:bg-muted/60"
                }`}
              >
                <div className="font-medium truncate">{row.name}</div>
                <div className="text-xs text-muted-foreground">
                  {row.status === "draft" ? "Draft" : `v${row.currentVersion}`}
                </div>
              </button>
            ))}
            {!templates.length ? (
              <p className="text-sm text-muted-foreground px-1">
                No templates yet. Start a chat to create one.
              </p>
            ) : null}
          </aside>

          <ResizablePanelGroup
            direction="horizontal"
            autoSaveId="report-template-authoring"
            className="min-h-0 h-full min-w-0 flex-1 rounded-lg border"
          >
            <ResizablePanel defaultSize={58} minSize={28} className="min-w-0 min-h-0">
              <section className="flex h-full min-h-0 flex-col">
                <div className="border-b px-3 py-2 lg:hidden">
                  <select
                    className="h-9 w-full rounded-md border bg-background px-2 text-sm"
                    value={templateId}
                    onChange={(e) => {
                      const id = e.target.value;
                      if (!id) return;
                      abortRef.current?.abort();
                      previewAbortRef.current?.abort();
                      setSelectedId(id);
                      setAwaitingClarifyFor(null);
                      setPreviewResult(null);
                      setPreviewError(null);
                      lastPreviewKeyRef.current = "";
                      setError(null);
                    }}
                  >
                    {!templates.length ? (
                      <option value="">No templates</option>
                    ) : null}
                    {templates.map((row) => (
                      <option key={row.id} value={row.id}>
                        {row.name}
                      </option>
                    ))}
                  </select>
                </div>
                {!templateId ? (
                  <div className="flex flex-1 items-center justify-center p-8 text-sm text-muted-foreground">
                    Start a new template to begin the authoring chat.
                  </div>
                ) : (
                  <>
                    <div className="flex-1 space-y-4 overflow-y-auto p-4">
                      {messages.map((message, messageIndex) => {
                        const isLastAssistant =
                          message.role === "assistant" &&
                          messageIndex ===
                            messages.reduce(
                              (last, row, index) => (row.role === "assistant" ? index : last),
                              -1,
                            );
                        const content =
                          message.role === "assistant" && isLastAssistant
                            ? assistantTextWithoutQuestionEcho(
                                message.content,
                                pendingQuestions,
                              )
                            : message.content;
                        const isUser = message.role === "user";
                        return (
                          <div
                            key={message.id}
                            className={`flex ${isUser ? "justify-end" : "justify-start"}`}
                          >
                            <div
                              className={`max-w-[88%] space-y-2 ${
                                isUser ? "items-end" : "items-start"
                              }`}
                            >
                              <p
                                className={`px-1 text-[10px] font-semibold uppercase tracking-wide ${
                                  isUser
                                    ? "text-right text-primary/70"
                                    : "text-left text-muted-foreground"
                                }`}
                              >
                                {isUser ? "You" : "Assistant"}
                              </p>
                              {isUser ? (
                                <div className="rounded-2xl rounded-br-md bg-primary px-3.5 py-2.5 text-sm text-primary-foreground whitespace-pre-wrap shadow-sm">
                                  {message.content}
                                </div>
                              ) : (
                                <div className="space-y-2 rounded-2xl rounded-bl-md border border-border/80 bg-muted/40 px-3.5 py-2.5 shadow-sm">
                                  {message.steps?.length ? (
                                    <ProgressTrail steps={message.steps} />
                                  ) : null}
                                  {content ? (
                                    <p className="text-sm whitespace-pre-wrap text-foreground">
                                      {content}
                                    </p>
                                  ) : null}
                                </div>
                              )}
                            </div>
                          </div>
                        );
                      })}
                      {busy ? (
                        <div className="flex justify-start">
                          <div className="max-w-[88%] space-y-2">
                            <p className="px-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                              Assistant
                            </p>
                            <div className="space-y-2 rounded-2xl rounded-bl-md border border-border/80 bg-muted/40 px-3.5 py-2.5 shadow-sm">
                              <ProgressTrail steps={liveSteps} live />
                              {liveAssistant ? (
                                <p className="text-sm whitespace-pre-wrap text-foreground">
                                  {liveAssistant}
                                  <span className="opacity-50">▌</span>
                                </p>
                              ) : null}
                            </div>
                          </div>
                        </div>
                      ) : null}
                      {!busy && pendingQuestions.length ? (
                        <div className="flex justify-start">
                          <div className="w-full max-w-[88%] space-y-2">
                            <p className="px-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                              Assistant
                            </p>
                            <div className="space-y-3 rounded-2xl rounded-bl-md border border-primary/25 bg-primary/5 p-3">
                          {pendingQuestions.map((question) => (
                            <div key={question.id} className="space-y-2">
                              <p className="text-sm">{question.prompt}</p>
                              {awaitingClarifyFor === question.id ? (
                                <p className="text-xs text-muted-foreground">
                                  Type your clarification below, then send.
                                </p>
                              ) : null}
                              <div className="flex flex-wrap gap-2">
                                {(question.options ?? []).map((option) => (
                                  <Button
                                    key={option.id || option.value}
                                    size="sm"
                                    variant={
                                      awaitingClarifyFor === question.id &&
                                      isFreeTextOption(
                                        String(option.value ?? option.id ?? ""),
                                        String(option.label || option.value || ""),
                                      )
                                        ? "default"
                                        : "outline"
                                    }
                                    disabled={busy}
                                    onClick={() => chooseOption(question, option)}
                                  >
                                    {option.label || option.value}
                                  </Button>
                                ))}
                              </div>
                            </div>
                          ))}
                            </div>
                          </div>
                        </div>
                      ) : null}
                      <div ref={chatEndRef} />
                    </div>
                    {error ? (
                      <div className="mx-4 mb-2 rounded-md border border-destructive/40 bg-destructive/5 p-2 text-sm text-destructive whitespace-pre-wrap">
                        {error}
                      </div>
                    ) : null}
                    <form
                      className="flex items-end gap-2 border-t p-3"
                      onSubmit={(event) => {
                        event.preventDefault();
                        void send(draft);
                      }}
                    >
                      <Textarea
                        ref={composerRef}
                        rows={2}
                        value={draft}
                        disabled={busy}
                        placeholder={
                          awaitingClarifyFor
                            ? "Type how to fix that piece, then press Send…"
                            : pendingQuestions.length
                              ? "Answer in the thread, or pick an option above…"
                              : "Describe the report, or refine the spec…"
                        }
                        onChange={(e) => setDraft(e.target.value)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter" && !event.shiftKey) {
                            event.preventDefault();
                            void send(draft);
                          }
                        }}
                      />
                      <Button type="submit" size="icon" disabled={busy || !draft.trim()}>
                        {busy ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Send className="h-4 w-4" />
                        )}
                      </Button>
                    </form>
                  </>
                )}
              </section>
            </ResizablePanel>

            <ResizableHandle withHandle className="bg-border" />

            <ResizablePanel defaultSize={42} minSize={22} className="min-w-0 min-h-0">
              <aside className="flex h-full min-h-0 flex-col overflow-hidden border-l">
                {detail ? (
                  <>
                    <div className="space-y-3 border-b p-3">
                      <div className="flex items-start gap-2">
                        <Input
                          value={detail.name}
                          onChange={(e) => setDetail({ ...detail, name: e.target.value })}
                          onBlur={() => {
                            if (!templateId || !detail.name.trim()) return;
                            renameMutation.mutate({
                              templateId,
                              data: { name: detail.name.trim() },
                            });
                          }}
                        />
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => deleteMutation.mutate({ templateId })}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <Badge variant="outline">{detail.status || "draft"}</Badge>
                        <Badge variant="secondary">{detail.reportKind || "adhoc"}</Badge>
                        {detail.currentVersion ? (
                          <Badge variant="outline">v{detail.currentVersion}</Badge>
                        ) : null}
                      </div>
                      <Button
                        size="sm"
                        onClick={saveVersion}
                        disabled={
                          !workingSpec ||
                          !hasUnsavedSpecChanges ||
                          saveMutation.isPending
                        }
                        title={
                          workingSpec && !hasUnsavedSpecChanges
                            ? "No changes since the current version"
                            : undefined
                        }
                      >
                        Save version
                      </Button>
                    </div>

                    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
                      <Tabs
                        defaultValue="preview"
                        className="flex min-h-0 flex-1 flex-col overflow-hidden"
                      >
                        <div className="shrink-0 border-b bg-muted/30 px-2 pt-2">
                          <TabsList className="grid h-auto w-full grid-cols-4 gap-1 rounded-lg border border-border/80 bg-background/80 p-1 shadow-sm">
                            <TabsTrigger
                              value="preview"
                              className="gap-1.5 px-2 py-2 text-xs font-medium data-[state=active]:bg-primary data-[state=active]:text-primary-foreground data-[state=active]:shadow-sm sm:text-sm"
                            >
                              <Eye className="hidden h-3.5 w-3.5 sm:block" />
                              Preview
                            </TabsTrigger>
                            <TabsTrigger
                              value="structure"
                              className="gap-1.5 px-2 py-2 text-xs font-medium data-[state=active]:bg-primary data-[state=active]:text-primary-foreground data-[state=active]:shadow-sm sm:text-sm"
                              disabled={!workingSpec}
                            >
                              <FileJson2 className="hidden h-3.5 w-3.5 sm:block" />
                              ReportSpec
                            </TabsTrigger>
                            <TabsTrigger
                              value="raw"
                              className="gap-1.5 px-2 py-2 font-mono text-xs font-semibold tracking-wide data-[state=active]:bg-primary data-[state=active]:text-primary-foreground data-[state=active]:shadow-sm sm:text-sm"
                              disabled={!workingSpec}
                            >
                              <Code2 className="hidden h-3.5 w-3.5 sm:block" />
                              RAW
                            </TabsTrigger>
                            <TabsTrigger
                              value="versions"
                              className="gap-1.5 px-2 py-2 text-xs font-medium data-[state=active]:bg-primary data-[state=active]:text-primary-foreground data-[state=active]:shadow-sm sm:text-sm"
                            >
                              <History className="hidden h-3.5 w-3.5 sm:block" />
                              Versions
                            </TabsTrigger>
                          </TabsList>
                        </div>

                        <TabsContent
                          value="preview"
                          className="mt-0 min-h-0 flex-1 overflow-y-auto p-3 data-[state=inactive]:hidden"
                        >
                          <div className="mb-3 flex items-center justify-end gap-2">
                            {previewBusy ? (
                              <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                                <Loader2 className="h-3 w-3 animate-spin" />
                                Updating…
                              </span>
                            ) : null}
                            {workingSpec ? (
                              <Button
                                type="button"
                                size="sm"
                                variant="ghost"
                                className="h-7 px-2 text-xs"
                                disabled={previewBusy}
                                onClick={() =>
                                  void runInlinePreview(workingSpec, detail?.name, true)
                                }
                              >
                                Refresh
                              </Button>
                            ) : null}
                          </div>

                          {!workingSpec ? (
                            <p className="text-sm text-muted-foreground">
                              After you describe the report, numbers from the study appear here.
                            </p>
                          ) : previewError ? (
                            <p className="text-sm text-destructive whitespace-pre-wrap">
                              {previewError}
                            </p>
                          ) : previewResult ? (
                            <ExecuteResultPreview result={previewResult} compact />
                          ) : previewBusy ? (
                            <p className="text-sm text-muted-foreground">
                              Running the working spec…
                            </p>
                          ) : (
                            <p className="text-sm text-muted-foreground">
                              Preview not loaded yet. Click the template again to refresh.
                            </p>
                          )}
                        </TabsContent>

                        <TabsContent
                          value="structure"
                          className="mt-0 min-h-0 flex-1 overflow-y-auto p-3 data-[state=inactive]:hidden"
                        >
                          {workingSpec ? (
                            <SectionCards spec={workingSpec} />
                          ) : (
                            <p className="text-sm text-muted-foreground">
                              No working spec yet.
                            </p>
                          )}
                        </TabsContent>

                        <TabsContent
                          value="raw"
                          className="mt-0 min-h-0 flex-1 overflow-y-auto p-3 data-[state=inactive]:hidden"
                        >
                          {workingSpec ? (
                            <pre className="overflow-auto rounded-md bg-muted/40 p-3 text-[11px]">
                              {JSON.stringify(workingSpec, null, 2)}
                            </pre>
                          ) : (
                            <p className="text-sm text-muted-foreground">
                              No working spec yet.
                            </p>
                          )}
                        </TabsContent>

                        <TabsContent
                          value="versions"
                          className="mt-0 min-h-0 flex-1 overflow-y-auto p-3 data-[state=inactive]:hidden"
                        >
                          {detail.versions?.length ? (
                            <div className="space-y-2">
                              {detail.versions.map((version) => (
                                <div
                                  key={version.id}
                                  className="flex items-center justify-between text-sm"
                                >
                                  <span>
                                    v{version.version} · {version.source}
                                  </span>
                                  {version.version !== detail.currentVersion ? (
                                    <Button
                                      size="sm"
                                      variant="outline"
                                      onClick={() =>
                                        restoreMutation.mutate({
                                          templateId,
                                          version: version.version,
                                        })
                                      }
                                    >
                                      Restore
                                    </Button>
                                  ) : null}
                                </div>
                              ))}
                            </div>
                          ) : (
                            <p className="text-sm text-muted-foreground">
                              No saved versions yet.
                            </p>
                          )}
                        </TabsContent>
                      </Tabs>
                    </div>
                  </>
                ) : (
                  <p className="p-4 text-sm text-muted-foreground">
                    Select a template to see its live preview.
                  </p>
                )}
              </aside>
            </ResizablePanel>
          </ResizablePanelGroup>
        </div>
        </div>
      </RequireActiveStudy>
    </Layout>
  );
}
