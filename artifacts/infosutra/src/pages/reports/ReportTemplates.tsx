import React, { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "wouter";
import { useQueryClient } from "@tanstack/react-query";
import {
  getGetReportTemplateQueryKey,
  getListReportTemplatesQueryKey,
  useCreateReportTemplate,
  useDeleteReportTemplate,
  useExecuteReportTemplate,
  useGetReportTemplate,
  useListReportTemplates,
  usePreviewReportTemplate,
  useUpdateReportTemplatePrompt,
  type CreateReportTemplateInput,
  type ExecutedReportOut,
  type ReportOut,
  type ReportTemplateOut,
  type TemplatePlanResultOut,
} from "@workspace/api-client-react";
import { Layout } from "@/components/layout/Layout";
import { Header } from "@/components/layout/Header";
import { RequireActiveStudy } from "@/components/study/RequireActiveStudy";
import { useStudy } from "@/components/study/StudyProvider";
import { reportDownloadUrl, reportPreviewUrl } from "@/lib/report-urls";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import {
  ExternalLink,
  FileText,
  History,
  MessageSquarePlus,
  Play,
  Plus,
  Trash2,
} from "lucide-react";

function planError(result: TemplatePlanResultOut | undefined): string | null {
  if (!result || result.status === "ok") return null;

  if (result.status === "clarification" && result.question) {
    return (
      `${result.question}\n\n` +
      "What to do: answer that in the prompt above, then click Plan and save again."
    );
  }

  if (result.status === "unsupported") {
    return (
      `${result.reason || "That request isn't supported for report templates."}\n\n` +
      "What to do: try a different prompt that uses available study data (KPIs, tables, coverage)."
    );
  }

  // invalid / error — almost always a planner/model failure, not bad user wording
  const head =
    result.reason ||
    "The planner couldn't produce a valid report specification.";
  const detail = result.errors?.[0]?.message;
  const action =
    "What to do: you don't need to change a clear prompt — click Plan and save again. " +
    "If it keeps failing, slightly rephrase (for example “Show total submissions today as a KPI”).";
  return detail ? `${head}\n\nDetails: ${detail}\n\n${action}` : `${head}\n\n${action}`;
}

function ThinkingBlock({ lines }: { lines: string[] }) {
  if (!lines.length) return null;
  return (
    <div className="border-l-2 border-border pl-3">
      <p className="text-xs font-semibold text-muted-foreground">Thinking</p>
      <div className="mt-1.5 space-y-1">
        {lines.map((line, index) => (
          <p
            key={`${index}-${line}`}
            className={
              index === lines.length - 1
                ? "text-xs text-foreground/80"
                : "text-xs text-muted-foreground"
            }
          >
            {line}
          </p>
        ))}
      </div>
    </div>
  );
}

async function streamCreateReportTemplate(
  payload: CreateReportTemplateInput,
  handlers: {
    signal?: AbortSignal;
    onProgress?: (message: string, phase?: string) => void;
  } = {},
): Promise<TemplatePlanResultOut> {
  const response = await fetch("/api/report-templates/create/stream", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify(payload),
    signal: handlers.signal,
  });

  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const errBody = await response.json();
      detail =
        (typeof errBody?.detail === "string" && errBody.detail) ||
        (typeof errBody?.message === "string" && errBody.message) ||
        detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }

  if (!response.body) {
    throw new Error("Create stream returned an empty body");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalResult: TemplatePlanResultOut | null = null;
  let streamError: string | null = null;

  const dispatchEvent = (eventName: string, dataRaw: string) => {
    let data: Record<string, unknown> = {};
    try {
      data = JSON.parse(dataRaw) as Record<string, unknown>;
    } catch {
      return;
    }
    if (eventName === "progress") {
      handlers.onProgress?.(
        String(data.message || ""),
        typeof data.phase === "string" ? data.phase : undefined,
      );
      return;
    }
    if (eventName === "result") {
      finalResult = data as TemplatePlanResultOut;
      return;
    }
    if (eventName === "error") {
      streamError = String(data.message || "Create stream failed");
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
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
      if (dataLines.length) dispatchEvent(eventName, dataLines.join("\n"));
    }
  }

  if (streamError) throw new Error(streamError);
  if (!finalResult) throw new Error("Create stream ended without a result");
  return finalResult;
}

export default function ReportTemplates() {
  const { activeStudyId } = useStudy();
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [name, setName] = useState("");
  const [kind, setKind] = useState("adhoc");
  const [prompt, setPrompt] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<ExecutedReportOut | null>(null);
  const [savedReport, setSavedReport] = useState<ReportOut | null>(null);
  const [activeTab, setActiveTab] = useState("prompt");
  const [editedPrompt, setEditedPrompt] = useState<string | null>(null);
  const [isPlanning, setIsPlanning] = useState(false);
  const [progressLines, setProgressLines] = useState<string[]>([]);
  const [previewDate, setPreviewDate] = useState<string>("");
  const planAbortRef = useRef<AbortController | null>(null);

  const listQuery = useListReportTemplates();
  const templates = listQuery.data ?? [];
  const selected = isCreating
    ? null
    : templates.find((row) => row.id === selectedId) ??
      (selectedId === null ? templates[0] ?? null : null);
  const templateId = selected?.id ?? "";

  const detailQuery = useGetReportTemplate(templateId, {
    query: { enabled: Boolean(templateId) } as never,
  });
  const detail = detailQuery.data;

  useEffect(() => {
    if (!detail || isCreating) return;
    setPreviewDate((current) => current || detail.defaultExecutionDate || "");
  }, [detail, isCreating]);

  const promptValue = isCreating
    ? prompt
    : editedPrompt ?? detail?.promptText ?? selected?.promptText ?? "";
  const effectivePreviewDate =
    previewDate || detail?.defaultExecutionDate || selected?.defaultExecutionDate || "";

  const startCreate = () => {
    planAbortRef.current?.abort();
    setIsCreating(true);
    setSelectedId(null);
    setName("");
    setKind("adhoc");
    setPrompt("");
    setEditedPrompt(null);
    setPreview(null);
    setSavedReport(null);
    setActiveTab("prompt");
    setError(null);
    setIsPlanning(false);
    setProgressLines([]);
  };

  const selectTemplate = (row: ReportTemplateOut) => {
    planAbortRef.current?.abort();
    setIsCreating(false);
    setSelectedId(row.id);
    setName("");
    setPrompt("");
    setPreview(null);
    setSavedReport(null);
    setEditedPrompt(null);
    setActiveTab("prompt");
    setError(null);
    setIsPlanning(false);
    setProgressLines([]);
    setPreviewDate(row.defaultExecutionDate || "");
  };

  const createTemplate = useCreateReportTemplate({
    mutation: {
      onError: (err) => setError(err.message),
    },
  });

  const applyCreateSuccess = async (result: TemplatePlanResultOut) => {
    const message = planError(result);
    if (message) {
      setError(message);
      return;
    }
    setIsCreating(false);
    setName("");
    setPrompt("");
    setError(null);
    setProgressLines([]);
    if (result.template?.id) setSelectedId(result.template.id);
    await queryClient.invalidateQueries({ queryKey: getListReportTemplatesQueryKey() });
  };

  const handlePlanAndSave = async () => {
    if (!name.trim() || !prompt.trim() || isPlanning) return;
    setError(null);
    setIsPlanning(true);
    setProgressLines(["Preparing the report planner…"]);
    planAbortRef.current?.abort();
    const controller = new AbortController();
    planAbortRef.current = controller;

    const payload: CreateReportTemplateInput = {
      name: name.trim(),
      prompt: prompt.trim(),
      reportKind: kind,
      studyId: activeStudyId || undefined,
    };

    try {
      const result = await streamCreateReportTemplate(payload, {
        signal: controller.signal,
        onProgress: (message) => {
          if (!message) return;
          setProgressLines((prev) =>
            prev[prev.length - 1] === message ? prev : [...prev, message].slice(-12),
          );
        },
      });
      await applyCreateSuccess(result);
    } catch (err) {
      if (controller.signal.aborted) {
        setProgressLines([]);
        return;
      }
      const message = err instanceof Error ? err.message : "Planning failed";
      const canFallback =
        /404|Failed to fetch|NetworkError|stream/i.test(message) || message.includes("HTTP 404");
      if (canFallback) {
        setProgressLines((prev) => [...prev, "Stream unavailable — retrying without stream…"]);
        try {
          const result = await createTemplate.mutateAsync({ data: payload });
          await applyCreateSuccess(result);
          return;
        } catch (fallbackErr) {
          setError(fallbackErr instanceof Error ? fallbackErr.message : "Planning failed");
          return;
        }
      }
      setError(message);
    } finally {
      if (planAbortRef.current === controller) {
        setIsPlanning(false);
      }
    }
  };
  const updatePrompt = useUpdateReportTemplatePrompt({
    mutation: {
      onSuccess: async (result) => {
        const message = planError(result);
        if (message) {
          setError(message);
          return;
        }
        setError(null);
        setEditedPrompt(null);
        await queryClient.invalidateQueries({ queryKey: getListReportTemplatesQueryKey() });
        if (templateId) {
          await queryClient.invalidateQueries({ queryKey: getGetReportTemplateQueryKey(templateId) });
        }
      },
      onError: (err) => setError(err.message),
    },
  });

  const previewTemplate = usePreviewReportTemplate({
    mutation: {
      onSuccess: (result) => {
        setPreview(result);
        setSavedReport(null);
        setError(null);
      },
      onError: (err) => setError(err.message),
    },
  });

  const executeTemplate = useExecuteReportTemplate({
    mutation: {
      onSuccess: (result) => {
        setPreview(result.preview);
        setSavedReport(result.report);
        setActiveTab("preview");
        setError(null);
      },
      onError: (err) => setError(err.message),
    },
  });

  const removeTemplate = useDeleteReportTemplate({
    mutation: {
      onSuccess: async () => {
        setSelectedId(null);
        setPreview(null);
        setSavedReport(null);
        await queryClient.invalidateQueries({ queryKey: getListReportTemplatesQueryKey() });
      },
      onError: (err) => setError(err.message),
    },
  });

  const runPreview = () => {
    if (!templateId) return;
    previewTemplate.mutate({
      templateId,
      data: {
        studyId: activeStudyId || undefined,
        runAi: false,
        executionDate: effectivePreviewDate || undefined,
      },
    });
  };

  const handleTabChange = (tab: string) => {
    setActiveTab(tab);
    if (tab === "preview" && !isCreating) runPreview();
  };

  const specJson = useMemo(
    () => JSON.stringify(detail?.spec ?? {}, null, 2),
    [detail?.spec],
  );

  const showDetail = isCreating || Boolean(selected);

  return (
    <Layout>
      <Header
        title="Report templates"
        description="Define a report in natural language, inspect the generated specification, and preview it against the active study."
        action={
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="outline" asChild>
              <Link href="/report-composer">
                <MessageSquarePlus className="mr-2 h-4 w-4" />
                Compose
              </Link>
            </Button>
            <Button
              size="sm"
              className="bg-primary text-primary-foreground"
              onClick={startCreate}
            >
              <Plus className="mr-2 h-4 w-4" />
              New template
            </Button>
          </div>
        }
      />
      <div className="flex-1 overflow-auto bg-muted/30 p-4 md:p-6">
        <RequireActiveStudy
          title="Select a study to preview templates"
          description="Templates can be authored globally; preview and execute use the active study."
        >
          {(error || listQuery.error) && (
            <div className="mb-4 whitespace-pre-wrap rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
              {error || listQuery.error?.message}
            </div>
          )}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
            <Card className="h-fit">
              <CardContent className="p-2">
                {listQuery.isLoading ? (
                  <p className="p-3 text-sm text-muted-foreground">Loading templates…</p>
                ) : templates.length === 0 && !isCreating ? (
                  <p className="p-3 text-sm text-muted-foreground">No templates yet.</p>
                ) : (
                  <ul className="space-y-1">
                    {isCreating ? (
                      <li>
                        <div className="w-full rounded-md bg-muted px-3 py-2 text-left text-sm font-medium">
                          <span className="block truncate">New template</span>
                          <span className="mt-1 flex flex-wrap gap-1">
                            <Badge variant="outline" className="text-[10px] uppercase">
                              {kind}
                            </Badge>
                            <span className="text-[11px] text-muted-foreground">Draft</span>
                          </span>
                        </div>
                      </li>
                    ) : null}
                    {templates.map((row: ReportTemplateOut) => (
                      <li key={row.id}>
                        <button
                          type="button"
                          onClick={() => selectTemplate(row)}
                          className={`w-full rounded-md px-3 py-2 text-left text-sm ${
                            !isCreating && row.id === templateId
                              ? "bg-muted font-medium"
                              : "hover:bg-muted/60"
                          }`}
                        >
                          <span className="block truncate">{row.name}</span>
                          <span className="mt-1 flex flex-wrap gap-1">
                            <Badge variant="outline" className="text-[10px] uppercase">
                              {row.reportKind}
                            </Badge>
                            {row.isSystem ? (
                              <Badge variant="secondary" className="text-[10px]">
                                System
                              </Badge>
                            ) : null}
                            <span className="text-[11px] text-muted-foreground">
                              v{row.currentVersion}
                            </span>
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>

            {!showDetail ? (
              <Card>
                <CardContent className="p-10 text-center text-sm text-muted-foreground">
                  Create a template from a prompt, or compose one conversationally.
                </CardContent>
              </Card>
            ) : (
              <Card>
                <CardContent className="space-y-4 p-5">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0 flex-1 space-y-3">
                      {isCreating ? (
                        <>
                          <div className="space-y-1.5">
                            <Label htmlFor="tpl-name">Name</Label>
                            <Input
                              id="tpl-name"
                              value={name}
                              onChange={(event) => setName(event.target.value)}
                              placeholder="Untitled template"
                            />
                          </div>
                          <div className="space-y-1.5">
                            <Label htmlFor="tpl-kind">Kind</Label>
                            <select
                              id="tpl-kind"
                              className="h-9 w-full max-w-xs rounded-md border bg-background px-2 text-sm"
                              value={kind}
                              onChange={(event) => setKind(event.target.value)}
                            >
                              <option value="adhoc">Ad hoc</option>
                              <option value="daily">Daily</option>
                              <option value="final">Final</option>
                            </select>
                          </div>
                        </>
                      ) : (
                        <>
                          <h2 className="text-lg font-semibold">
                            {detail?.name || selected?.name}
                          </h2>
                          <p className="text-sm text-muted-foreground">
                            {detail?.description || selected?.description || "—"}
                          </p>
                          <div className="flex flex-wrap items-end gap-2 pt-1">
                            <div className="space-y-1">
                              <Label htmlFor="tpl-report-date" className="text-xs">
                                Report date
                              </Label>
                              <Input
                                id="tpl-report-date"
                                type="date"
                                className="h-9 w-44"
                                value={effectivePreviewDate}
                                onChange={(event) => setPreviewDate(event.target.value)}
                              />
                            </div>
                            {detail?.defaultExecutionDate ? (
                              <p className="pb-2 text-xs text-muted-foreground">
                                From prompt: {detail.defaultExecutionDate}
                              </p>
                            ) : (
                              <p className="pb-2 text-xs text-muted-foreground">
                                Leave blank to use today in the study timezone.
                              </p>
                            )}
                          </div>
                        </>
                      )}
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {isCreating ? (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => {
                            setIsCreating(false);
                            setError(null);
                          }}
                        >
                          Cancel
                        </Button>
                      ) : (
                        <>
                          <Button
                            size="sm"
                            disabled={!templateId || executeTemplate.isPending}
                            onClick={() =>
                              executeTemplate.mutate({
                                templateId,
                                data: {
                                  studyId: activeStudyId || undefined,
                                  runAi: true,
                                  executionDate: effectivePreviewDate || undefined,
                                },
                              })
                            }
                          >
                            <Play className="mr-2 h-4 w-4" />
                            {executeTemplate.isPending ? "Saving…" : "Execute"}
                          </Button>
                          {selected && !selected.isSystem ? (
                            <Button
                              size="sm"
                              variant="ghost"
                              className="text-destructive"
                              onClick={() => {
                                if (confirm(`Delete template “${selected.name}”?`)) {
                                  removeTemplate.mutate({ templateId: selected.id });
                                }
                              }}
                            >
                              <Trash2 className="h-4 w-4" />
                            </Button>
                          ) : null}
                        </>
                      )}
                    </div>
                  </div>

                  <Tabs value={activeTab} onValueChange={handleTabChange}>
                    <TabsList>
                      <TabsTrigger value="prompt">Prompt</TabsTrigger>
                      <TabsTrigger
                        value="preview"
                        disabled={isCreating || !templateId || executeTemplate.isPending}
                      >
                        {previewTemplate.isPending ? "Previewing…" : "Preview"}
                      </TabsTrigger>
                      <TabsTrigger value="versions" disabled={isCreating}>
                        <History className="mr-1 h-3 w-3" />
                        Versions
                      </TabsTrigger>
                      <TabsTrigger value="spec" disabled={isCreating}>
                        Specification
                      </TabsTrigger>
                    </TabsList>
                    <TabsContent value="prompt" className="space-y-3 pt-3">
                      {isCreating ? (
                        <>
                          <Label htmlFor="tpl-prompt">What should the report contain?</Label>
                          <Textarea
                            id="tpl-prompt"
                            rows={12}
                            value={prompt}
                            onChange={(event) => setPrompt(event.target.value)}
                            placeholder="Today's intake by tool, enumerators to back-check, and coverage against plan."
                          />
                          <Button
                            size="sm"
                            disabled={!name.trim() || !prompt.trim() || isPlanning}
                            onClick={() => void handlePlanAndSave()}
                          >
                            <FileText className="mr-2 h-4 w-4" />
                            {isPlanning ? "Planning…" : "Plan and save"}
                          </Button>
                          {isPlanning ? <ThinkingBlock lines={progressLines} /> : null}
                        </>
                      ) : (
                        <>
                          <Textarea
                            rows={12}
                            value={promptValue}
                            onChange={(event) => setEditedPrompt(event.target.value)}
                          />
                          <Button
                            size="sm"
                            disabled={!editedPrompt || updatePrompt.isPending}
                            onClick={() =>
                              updatePrompt.mutate({
                                templateId,
                                data: {
                                  prompt: promptValue,
                                  notes: "Edited in the templates page.",
                                },
                              })
                            }
                          >
                            {updatePrompt.isPending ? "Re-planning…" : "Re-plan and save version"}
                          </Button>
                        </>
                      )}
                    </TabsContent>
                    <TabsContent value="preview" className="pt-3">
                      {previewTemplate.isPending && !preview ? (
                        <p className="text-sm text-muted-foreground">Generating preview…</p>
                      ) : preview ? (
                        <div className="space-y-6">
                          {savedReport ? (
                            <div className="flex flex-wrap items-center gap-2 rounded-md border bg-muted/40 px-3 py-2 text-sm">
                              <FileText className="h-4 w-4 text-muted-foreground" />
                              <span>
                                Saved as <span className="font-medium">{savedReport.title}</span>
                              </span>
                              <Button size="sm" variant="outline" asChild>
                                <a
                                  href={reportPreviewUrl(savedReport.id)}
                                  target="_blank"
                                  rel="noreferrer"
                                >
                                  <ExternalLink className="mr-1 h-3.5 w-3.5" />
                                  Open report
                                </a>
                              </Button>
                              <Button size="sm" variant="ghost" asChild>
                                <a href={reportDownloadUrl(savedReport.id, "pdf")} download>
                                  PDF
                                </a>
                              </Button>
                              <Button size="sm" variant="ghost" asChild>
                                <Link href="/reports">Reports</Link>
                              </Button>
                            </div>
                          ) : null}
                          {previewTemplate.isPending ? (
                            <p className="text-xs text-muted-foreground">Refreshing preview…</p>
                          ) : null}
                          <iframe
                            title="Server-rendered preview"
                            className="h-[min(70vh,720px)] w-full rounded-md border bg-white"
                            srcDoc={preview.html}
                          />
                        </div>
                      ) : (
                        <p className="text-sm text-muted-foreground">
                          Open this tab to run the template against the active study. Execute still
                          saves a report and shows the result here.
                        </p>
                      )}
                    </TabsContent>
                    <TabsContent value="versions" className="space-y-3 pt-3">
                      {(detail?.versions ?? []).map((version) => (
                        <div key={version.id} className="rounded-md border p-3 text-sm">
                          <div className="mb-1 flex flex-wrap items-center gap-2">
                            <span className="font-medium">v{version.version}</span>
                            <Badge variant="outline" className="text-[10px]">
                              {version.source}
                            </Badge>
                            <span className="text-xs text-muted-foreground">
                              {new Date(version.createdAt).toLocaleString()}
                            </span>
                          </div>
                          {version.notes ? (
                            <p className="text-xs text-muted-foreground">{version.notes}</p>
                          ) : null}
                          <ul className="mt-2 list-disc pl-5 text-xs text-muted-foreground">
                            {(version.changes ?? []).map((change) => (
                              <li key={change}>{change}</li>
                            ))}
                          </ul>
                        </div>
                      ))}
                    </TabsContent>
                    <TabsContent value="spec" className="pt-3">
                      <pre className="max-h-[520px] overflow-auto rounded-md border bg-card p-3 text-xs">
                        {specJson}
                      </pre>
                    </TabsContent>
                  </Tabs>
                </CardContent>
              </Card>
            )}
          </div>
        </RequireActiveStudy>
      </div>
    </Layout>
  );
}
