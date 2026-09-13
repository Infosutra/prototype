import React, { useEffect, useRef, useState } from "react";
import { Link } from "wouter";
import { useQueryClient } from "@tanstack/react-query";
import {
  getGetReportTemplateQueryKey,
  getListReportTemplatesQueryKey,
  useCreateReportTemplate,
  useDeleteReportTemplate,
  useGetReportTemplate,
  useListReportTemplates,
  useRestoreReportTemplateVersion,
  type ReportTemplateOut,
} from "@workspace/api-client-react";
import { Layout } from "@/components/layout/Layout";
import { Header } from "@/components/layout/Header";
import {
  createPlanJob,
  pollPlanJob,
  SectionCards,
  type PlanJudgement,
  type PlanUnmapped,
} from "@/components/reports/SectionCards";
import { RequireActiveStudy } from "@/components/study/RequireActiveStudy";
import { useStudy } from "@/components/study/StudyProvider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { FileText, MessageSquarePlus, Plus, Trash2 } from "lucide-react";

export default function ReportTemplates() {
  const { activeStudyId } = useStudy();
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [name, setName] = useState("");
  const [kind, setKind] = useState("adhoc");
  const [prompt, setPrompt] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isPlanning, setIsPlanning] = useState(false);
  const [plannedSpec, setPlannedSpec] = useState<Record<string, unknown> | null>(null);
  const [unmapped, setUnmapped] = useState<PlanUnmapped[]>([]);
  const [judgement, setJudgement] = useState<PlanJudgement | null>(null);
  const planAbortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const id = params.get("id");
    if (!id) return;
    setSelectedId(id);
    setIsCreating(false);
  }, []);

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

  const createMutation = useCreateReportTemplate({
    mutation: {
      onSuccess: async (result) => {
        if (result.status !== "ok" || !result.template) {
          setError(result.reason || "Could not save template");
          return;
        }
        await queryClient.invalidateQueries({ queryKey: getListReportTemplatesQueryKey() });
        setIsCreating(false);
        setSelectedId(result.template.id);
        setPlannedSpec(null);
        setUnmapped([]);
        setJudgement(null);
        setError(null);
      },
      onError: (err) => setError(err.message),
    },
  });

  const deleteMutation = useDeleteReportTemplate({
    mutation: {
      onSuccess: async () => {
        await queryClient.invalidateQueries({ queryKey: getListReportTemplatesQueryKey() });
        setSelectedId(null);
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
      },
    },
  });

  const startCreate = () => {
    planAbortRef.current?.abort();
    setIsCreating(true);
    setSelectedId(null);
    setName("");
    setKind("adhoc");
    setPrompt("");
    setPlannedSpec(null);
    setUnmapped([]);
    setJudgement(null);
    setError(null);
    setIsPlanning(false);
  };

  const selectTemplate = (row: ReportTemplateOut) => {
    planAbortRef.current?.abort();
    setIsCreating(false);
    setSelectedId(row.id);
    setPlannedSpec(null);
    setUnmapped([]);
    setJudgement(null);
    setError(null);
    setIsPlanning(false);
  };

  const runPlan = async () => {
    if (!activeStudyId) {
      setError("Select an active study first.");
      return;
    }
    if (!prompt.trim()) {
      setError("Describe the report first.");
      return;
    }
    planAbortRef.current?.abort();
    const controller = new AbortController();
    planAbortRef.current = controller;
    setIsPlanning(true);
    setError(null);
    try {
      const jobId = await createPlanJob(activeStudyId, prompt.trim());
      const result = await pollPlanJob(jobId, { signal: controller.signal });
      setPlannedSpec(result.spec);
      setUnmapped(result.unmapped);
      setJudgement(result.judgement);
      if (!name.trim() && typeof result.spec.title === "string") {
        setName(result.spec.title);
      }
    } catch (err) {
      if ((err as Error).message !== "Planning cancelled") {
        setError((err as Error).message || "Planning failed");
      }
    } finally {
      setIsPlanning(false);
    }
  };

  const saveTemplate = () => {
    if (!activeStudyId || !plannedSpec) return;
    if (!name.trim()) {
      setError("Name is required");
      return;
    }
    createMutation.mutate({
      data: {
        name: name.trim(),
        studyId: activeStudyId,
        reportKind: kind,
        prompt: prompt.trim(),
        spec: plannedSpec,
      },
    });
  };

  const previewHref =
    plannedSpec || detail?.spec
      ? `/reports/execute-preview?studyId=${encodeURIComponent(activeStudyId || "")}`
      : null;

  return (
    <Layout>
      <RequireActiveStudy>
        <Header
          title="Report templates"
          description="Author a ReportSpec with a plan job, review section cards, then save."
          action={
            <div className="flex gap-2">
              <Button variant="outline" asChild>
                <Link href="/report-composer">
                  <MessageSquarePlus className="mr-2 h-4 w-4" />
                  Compose
                </Link>
              </Button>
              <Button onClick={startCreate}>
                <Plus className="mr-2 h-4 w-4" />
                Create template
              </Button>
            </div>
          }
        />

        <div className="grid gap-6 lg:grid-cols-[240px_1fr]">
          <aside className="space-y-2">
            {templates.map((row) => (
              <button
                key={row.id}
                type="button"
                onClick={() => selectTemplate(row)}
                className={`w-full rounded-md border px-3 py-2 text-left text-sm ${
                  selected?.id === row.id && !isCreating
                    ? "border-foreground/30 bg-muted"
                    : "border-transparent hover:bg-muted/60"
                }`}
              >
                <div className="font-medium">{row.name}</div>
                <div className="text-xs text-muted-foreground">{row.reportKind}</div>
              </button>
            ))}
            {!templates.length ? (
              <p className="text-sm text-muted-foreground">No templates yet.</p>
            ) : null}
          </aside>

          <section className="space-y-4">
            {isCreating ? (
              <>
                <div className="grid gap-3 sm:grid-cols-2">
                  <div>
                    <Label htmlFor="tpl-name">Name</Label>
                    <Input
                      id="tpl-name"
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      placeholder="Daily field snapshot"
                    />
                  </div>
                  <div>
                    <Label htmlFor="tpl-kind">Kind</Label>
                    <Input id="tpl-kind" value={kind} onChange={(e) => setKind(e.target.value)} />
                  </div>
                </div>
                <div>
                  <Label htmlFor="tpl-prompt">Describe the report</Label>
                  <Textarea
                    id="tpl-prompt"
                    rows={5}
                    value={prompt}
                    onChange={(e) => setPrompt(e.target.value)}
                    placeholder="Today's submissions KPIs, enumerator table, and open red flags…"
                  />
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button onClick={runPlan} disabled={isPlanning || !activeStudyId}>
                    {isPlanning ? "Planning…" : "Plan"}
                  </Button>
                  <Button
                    variant="secondary"
                    onClick={saveTemplate}
                    disabled={!plannedSpec || createMutation.isPending}
                  >
                    Save template
                  </Button>
                  {previewHref && plannedSpec ? (
                    <Button variant="outline" asChild>
                      <Link href={previewHref}>Preview (execute job)</Link>
                    </Button>
                  ) : null}
                </div>
                {error ? <p className="text-sm text-destructive whitespace-pre-wrap">{error}</p> : null}
                {plannedSpec ? (
                  <SectionCards spec={plannedSpec} unmapped={unmapped} judgement={judgement} />
                ) : (
                  <p className="text-sm text-muted-foreground">
                    Plan to review section cards (structure only — no numbers).
                  </p>
                )}
              </>
            ) : selected ? (
              <>
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h2 className="text-lg font-semibold">{selected.name}</h2>
                    <p className="text-sm text-muted-foreground">{selected.promptText}</p>
                    <div className="mt-2 flex gap-2">
                      <Badge variant="secondary">{selected.reportKind}</Badge>
                      <Badge variant="outline">v{selected.currentVersion}</Badge>
                    </div>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => deleteMutation.mutate({ templateId: selected.id })}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
                {detail?.spec ? <SectionCards spec={detail.spec as Record<string, unknown>} /> : null}
                {detail?.versions?.length ? (
                  <div className="space-y-2">
                    <p className="text-sm font-medium">Versions</p>
                    {detail.versions.map((version) => (
                      <div
                        key={version.id}
                        className="flex items-center justify-between gap-2 text-sm"
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
                                templateId: selected.id,
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
                ) : null}
                {previewHref ? (
                  <Button variant="outline" asChild>
                    <Link href={previewHref}>
                      <FileText className="mr-2 h-4 w-4" />
                      Preview execute
                    </Link>
                  </Button>
                ) : null}
              </>
            ) : (
              <p className="text-sm text-muted-foreground">
                Select a template or create one from an English description.
              </p>
            )}
          </section>
        </div>
      </RequireActiveStudy>
    </Layout>
  );
}
