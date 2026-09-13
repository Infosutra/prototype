import React, { useRef, useState } from "react";
import { Link, useLocation } from "wouter";
import { useQueryClient } from "@tanstack/react-query";
import {
  getGetReportConversationQueryKey,
  getListReportConversationsQueryKey,
  getListReportTemplatesQueryKey,
  useCreateReportConversation,
  useDeleteReportConversation,
  useGetReportConversation,
  useListReportConversations,
  useSaveReportConversationAsTemplate,
  useUpdateReportConversation,
  type ReportConversationOut,
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
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ExternalLink, MessageSquare, Pencil, Plus, Save, Send, Trash2 } from "lucide-react";

function formatUpdatedAt(value: string | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function ReportComposer() {
  const { activeStudyId } = useStudy();
  const queryClient = useQueryClient();
  const [location, setLocation] = useLocation();
  const conversationId = location.startsWith("/report-composer/")
    ? location.slice("/report-composer/".length)
    : "";

  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isPlanning, setIsPlanning] = useState(false);
  const [unmapped, setUnmapped] = useState<PlanUnmapped[]>([]);
  const [judgement, setJudgement] = useState<PlanJudgement | null>(null);
  const [saveOpen, setSaveOpen] = useState(false);
  const [saveName, setSaveName] = useState("");
  const [saveKind, setSaveKind] = useState("adhoc");
  const [renameOpen, setRenameOpen] = useState(false);
  const [renameTitle, setRenameTitle] = useState("");
  const planAbortRef = useRef<AbortController | null>(null);

  const listQuery = useListReportConversations(
    activeStudyId ? { studyId: activeStudyId } : undefined,
    { query: { enabled: Boolean(activeStudyId) } as never },
  );
  const conversations = listQuery.data ?? [];
  const detailQuery = useGetReportConversation(conversationId, {
    query: { enabled: Boolean(conversationId) } as never,
  });
  const conversation = detailQuery.data;

  const refresh = async (id: string) => {
    await queryClient.invalidateQueries({
      queryKey: getListReportConversationsQueryKey(
        activeStudyId ? { studyId: activeStudyId } : undefined,
      ),
    });
    await queryClient.invalidateQueries({ queryKey: getGetReportConversationQueryKey(id) });
  };

  const createConversation = useCreateReportConversation({
    mutation: {
      onSuccess: async (result) => {
        const id = result.conversation.id;
        setLocation(`/report-composer/${id}`);
        await refresh(id);
      },
      onError: (err) => setError(err.message),
    },
  });

  const deleteConversation = useDeleteReportConversation({
    mutation: {
      onSuccess: async () => {
        setLocation("/report-composer");
        await queryClient.invalidateQueries({
          queryKey: getListReportConversationsQueryKey(
            activeStudyId ? { studyId: activeStudyId } : undefined,
          ),
        });
      },
    },
  });

  const updateConversation = useUpdateReportConversation({
    mutation: {
      onSuccess: async () => {
        if (conversationId) await refresh(conversationId);
        setRenameOpen(false);
      },
    },
  });

  const saveAsTemplate = useSaveReportConversationAsTemplate({
    mutation: {
      onSuccess: async () => {
        setSaveOpen(false);
        await queryClient.invalidateQueries({ queryKey: getListReportTemplatesQueryKey() });
        if (conversationId) await refresh(conversationId);
      },
      onError: (err) => setError(err.message),
    },
  });

  const startNew = () => {
    if (!activeStudyId) return;
    createConversation.mutate({
      data: { studyId: activeStudyId, title: "Untitled report", message: "" },
    });
  };

  const sendTurn = async () => {
    const text = draft.trim();
    if (!text || !activeStudyId) return;
    setError(null);
    setIsPlanning(true);
    planAbortRef.current?.abort();
    const controller = new AbortController();
    planAbortRef.current = controller;

    try {
      let id = conversationId;
      if (!id) {
        const created = await createConversation.mutateAsync({
          data: { studyId: activeStudyId, title: "Untitled report", message: "" },
        });
        id = created.conversation.id;
        setLocation(`/report-composer/${id}`);
      }

      const currentSpec = (conversation?.spec as Record<string, unknown> | null) || null;
      const jobId = await createPlanJob(activeStudyId, text, currentSpec);
      const planned = await pollPlanJob(jobId, { signal: controller.signal });

      const resp = await fetch(`/api/report-conversations/${encodeURIComponent(id)}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          spec: planned.spec,
          unmapped: planned.unmapped,
          judgement: planned.judgement,
        }),
        signal: controller.signal,
      });
      if (!resp.ok) {
        throw new Error((await resp.text()) || `HTTP ${resp.status}`);
      }

      setUnmapped(planned.unmapped);
      setJudgement(planned.judgement);
      setDraft("");
      await refresh(id);
    } catch (err) {
      if ((err as Error).message !== "Planning cancelled") {
        setError((err as Error).message || "Turn failed");
      }
    } finally {
      setIsPlanning(false);
    }
  };

  const selectConversation = (row: ReportConversationOut) => {
    setLocation(`/report-composer/${row.id}`);
    setError(null);
    setUnmapped([]);
    setJudgement(null);
  };

  const workingSpec = (conversation?.spec as Record<string, unknown> | null) || null;
  const previewHref = workingSpec
    ? `/reports/execute-preview?studyId=${encodeURIComponent(activeStudyId || "")}`
    : null;

  return (
    <Layout>
      <RequireActiveStudy>
        <Header
          title="Report composer"
          description="Each message runs a plan job with the current spec, then shows section cards."
          action={
            <Button onClick={startNew} disabled={!activeStudyId}>
              <Plus className="mr-2 h-4 w-4" />
              New draft
            </Button>
          }
        />

        <div className="grid gap-6 lg:grid-cols-[240px_1fr]">
          <aside className="space-y-2">
            {conversations.map((row) => (
              <button
                key={row.id}
                type="button"
                onClick={() => selectConversation(row)}
                className={`w-full rounded-md border px-3 py-2 text-left text-sm ${
                  row.id === conversationId
                    ? "border-foreground/30 bg-muted"
                    : "border-transparent hover:bg-muted/60"
                }`}
              >
                <div className="flex items-center gap-2">
                  <MessageSquare className="h-3.5 w-3.5 text-muted-foreground" />
                  <span className="font-medium truncate">{row.title}</span>
                </div>
                <div className="mt-1 text-xs text-muted-foreground">
                  {formatUpdatedAt(row.updatedAt)}
                </div>
              </button>
            ))}
            {!conversations.length ? (
              <p className="text-sm text-muted-foreground">No drafts yet.</p>
            ) : null}
          </aside>

          <section className="space-y-4">
            {conversation ? (
              <>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <h2 className="text-lg font-semibold">{conversation.title}</h2>
                    <Badge variant="outline">{conversation.status}</Badge>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        setRenameTitle(conversation.title);
                        setRenameOpen(true);
                      }}
                    >
                      <Pencil className="mr-1 h-3.5 w-3.5" />
                      Rename
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        setSaveName(conversation.title);
                        setSaveOpen(true);
                      }}
                      disabled={!workingSpec}
                    >
                      <Save className="mr-1 h-3.5 w-3.5" />
                      Save as template
                    </Button>
                    {previewHref ? (
                      <Button variant="outline" size="sm" asChild>
                        <Link href={previewHref}>
                          <ExternalLink className="mr-1 h-3.5 w-3.5" />
                          Preview
                        </Link>
                      </Button>
                    ) : null}
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() =>
                        deleteConversation.mutate({ conversationId: conversation.id })
                      }
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </div>

                <div className="space-y-2 max-h-48 overflow-y-auto border-b border-border pb-3">
                  {(conversation.messages || []).map((message) => (
                    <div key={message.id} className="text-sm">
                      <span className="font-medium capitalize text-muted-foreground">
                        {message.role}:{" "}
                      </span>
                      <span>{message.content}</span>
                    </div>
                  ))}
                </div>

                {workingSpec ? (
                  <SectionCards spec={workingSpec} unmapped={unmapped} judgement={judgement} />
                ) : (
                  <p className="text-sm text-muted-foreground">
                    Send a request to plan the first specification.
                  </p>
                )}

                <div className="space-y-2">
                  <Textarea
                    rows={3}
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    placeholder="Add a KPI for clean submissions, or a red-flag table…"
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                        e.preventDefault();
                        void sendTurn();
                      }
                    }}
                  />
                  <div className="flex gap-2">
                    <Button onClick={() => void sendTurn()} disabled={isPlanning || !draft.trim()}>
                      <Send className="mr-2 h-4 w-4" />
                      {isPlanning ? "Planning…" : "Send"}
                    </Button>
                  </div>
                  {error ? (
                    <p className="text-sm text-destructive whitespace-pre-wrap">{error}</p>
                  ) : null}
                </div>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">
                Start a new draft or pick one from the list.
              </p>
            )}
          </section>
        </div>

        <Dialog open={saveOpen} onOpenChange={setSaveOpen}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Save as template</DialogTitle>
            </DialogHeader>
            <div className="space-y-3">
              <div>
                <Label htmlFor="save-name">Name</Label>
                <Input
                  id="save-name"
                  value={saveName}
                  onChange={(e) => setSaveName(e.target.value)}
                />
              </div>
              <div>
                <Label htmlFor="save-kind">Kind</Label>
                <Input
                  id="save-kind"
                  value={saveKind}
                  onChange={(e) => setSaveKind(e.target.value)}
                />
              </div>
            </div>
            <DialogFooter>
              <Button
                onClick={() => {
                  if (!conversationId || !saveName.trim()) return;
                  saveAsTemplate.mutate({
                    conversationId,
                    data: { name: saveName.trim(), reportKind: saveKind },
                  });
                }}
                disabled={saveAsTemplate.isPending}
              >
                Save
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        <Dialog open={renameOpen} onOpenChange={setRenameOpen}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Rename draft</DialogTitle>
            </DialogHeader>
            <Input value={renameTitle} onChange={(e) => setRenameTitle(e.target.value)} />
            <DialogFooter>
              <Button
                onClick={() => {
                  if (!conversationId || !renameTitle.trim()) return;
                  updateConversation.mutate({
                    conversationId,
                    data: { title: renameTitle.trim() },
                  });
                }}
              >
                Save
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </RequireActiveStudy>
    </Layout>
  );
}
