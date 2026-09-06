import React, { useEffect, useState } from "react";
import { Link, useLocation } from "wouter";
import { useQueryClient } from "@tanstack/react-query";
import {
  getGetReportConversationQueryKey,
  getListReportConversationsQueryKey,
  getListReportTemplatesQueryKey,
  useAddReportConversationMessage,
  useCreateReportConversation,
  useGetReportConversation,
  useGetReportSpecCatalog,
  useListReportConversations,
  usePreviewReportConversation,
  useSaveReportConversationAsTemplate,
  type ExecutedReportOut,
  type ReportConversationOut,
} from "@workspace/api-client-react";
import { Layout } from "@/components/layout/Layout";
import { Header } from "@/components/layout/Header";
import { ComposerHelpSheet } from "@/components/reports/ComposerHelpSheet";
import { RequireActiveStudy } from "@/components/study/RequireActiveStudy";
import { useStudy } from "@/components/study/StudyProvider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
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
import { CircleHelp, MessageSquare, Save, Send } from "lucide-react";

function turnStatusMessage(result: {
  status: string;
  question?: string | null;
  reason?: string | null;
}): string | null {
  if (result.status === "ok" || result.status === "answer") return null;
  if (result.status === "clarification") return result.question || null;
  return result.question || result.reason || result.status;
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
  const [preview, setPreview] = useState<ExecutedReportOut | null>(null);
  const [saveOpen, setSaveOpen] = useState(false);
  const [saveName, setSaveName] = useState("");
  const [helpOpen, setHelpOpen] = useState(false);

  const listQuery = useListReportConversations(
    activeStudyId ? { studyId: activeStudyId } : undefined,
    { query: { enabled: Boolean(activeStudyId) } as never },
  );
  const conversations = listQuery.data ?? [];
  const detailQuery = useGetReportConversation(conversationId, {
    query: { enabled: Boolean(conversationId) } as never,
  });
  const conversation = detailQuery.data;
  const catalogQuery = useGetReportSpecCatalog(undefined, {
    query: { enabled: helpOpen || Boolean(activeStudyId) } as never,
  });

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
        setError(turnStatusMessage(result));
        setDraft("");
        const id = result.conversation.id;
        setLocation(`/report-composer/${id}`);
        await refresh(id);
      },
      onError: (err) => setError(err.message),
    },
  });

  const addMessage = useAddReportConversationMessage({
    mutation: {
      onSuccess: async (result) => {
        setError(turnStatusMessage(result));
        setDraft("");
        await refresh(result.conversation.id);
      },
      onError: (err) => setError(err.message),
    },
  });

  const previewConversation = usePreviewReportConversation({
    mutation: {
      onSuccess: async (result) => {
        setPreview(result);
        setError(null);
        if (conversationId) {
          await queryClient.invalidateQueries({
            queryKey: getGetReportConversationQueryKey(conversationId),
          });
        }
      },
      onError: (err) => setError(err.message),
    },
  });

  const saveTemplate = useSaveReportConversationAsTemplate({
    mutation: {
      onSuccess: async () => {
        setSaveOpen(false);
        await queryClient.invalidateQueries({ queryKey: getListReportTemplatesQueryKey() });
        if (conversationId) await refresh(conversationId);
      },
      onError: (err) => setError(err.message),
    },
  });

  useEffect(() => {
    if (!conversationId || !conversation?.spec || !activeStudyId) return;
    previewConversation.mutate({
      conversationId,
      data: { studyId: activeStudyId, runAi: false },
    });
    // Intentionally only when the working spec identity changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId, JSON.stringify(conversation?.spec), activeStudyId]);

  const send = () => {
    const message = draft.trim();
    if (!message || !activeStudyId) return;
    if (!conversationId) {
      createConversation.mutate({
        data: { studyId: activeStudyId, title: "Untitled report", message },
      });
      return;
    }
    addMessage.mutate({ conversationId, data: { message } });
  };

  const busy = createConversation.isPending || addMessage.isPending;

  return (
    <Layout>
      <Header
        title="Compose a report"
        description="Describe the report, refine it in conversation, and preview the rendered output against the active study."
        action={
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="outline" onClick={() => setHelpOpen(true)}>
              <CircleHelp className="mr-2 h-4 w-4" />
              Help
            </Button>
            <Button size="sm" variant="outline" asChild>
              <Link href="/report-templates">Templates</Link>
            </Button>
            <Button
              size="sm"
              disabled={!conversation?.spec}
              onClick={() => {
                setSaveName(conversation?.title || "");
                setSaveOpen(true);
              }}
            >
              <Save className="mr-2 h-4 w-4" />
              Save as template
            </Button>
          </div>
        }
      />
      <div className="flex-1 overflow-auto bg-muted/30 p-4 md:p-6">
        <RequireActiveStudy
          title="Select a study to compose a report"
          description="Conversations are scoped to the active study so preview uses that study's data."
        >
          {(error || listQuery.error) && (
            <div className="mb-4 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
              {error || listQuery.error?.message}
            </div>
          )}
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-[240px_minmax(0,1fr)_minmax(0,1.1fr)]">
            <Card className="h-fit">
              <CardContent className="p-2">
                <Button
                  variant="ghost"
                  size="sm"
                  className="mb-2 w-full justify-start"
                  onClick={() => {
                    setLocation("/report-composer");
                    setPreview(null);
                    setError(null);
                  }}
                >
                  New conversation
                </Button>
                <ul className="space-y-1">
                  {conversations.map((row: ReportConversationOut) => (
                    <li key={row.id}>
                      <button
                        type="button"
                        className={`w-full rounded-md px-3 py-2 text-left text-sm ${
                          row.id === conversationId ? "bg-muted font-medium" : "hover:bg-muted/60"
                        }`}
                        onClick={() => setLocation(`/report-composer/${row.id}`)}
                      >
                        <span className="block truncate">{row.title}</span>
                        <span className="text-[11px] text-muted-foreground">{row.status}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>

            <Card className="flex min-h-[520px] flex-col">
              <CardContent className="flex flex-1 flex-col gap-3 p-4">
                <div className="flex-1 space-y-3 overflow-auto">
                  {(conversation?.messages ?? []).length === 0 && (
                    <p className="text-sm text-muted-foreground">
                      Ask for the sections and charts you need, or open Help for visual samples and
                      example prompts. Unrelated sections stay put when you refine the report.
                    </p>
                  )}
                  {(conversation?.messages ?? []).map((message) => (
                    <div
                      key={message.id}
                      className={`rounded-md px-3 py-2 text-sm ${
                        message.role === "user" ? "bg-primary/10 ml-8" : "bg-muted mr-8"
                      }`}
                    >
                      <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">
                        {message.role}
                      </p>
                      <p className="whitespace-pre-wrap">{message.content}</p>
                      {(message.changes ?? []).length > 0 ? (
                        <ul className="mt-2 list-disc pl-4 text-xs text-muted-foreground">
                          {message.changes?.map((change) => (
                            <li key={change}>{change}</li>
                          ))}
                        </ul>
                      ) : null}
                    </div>
                  ))}
                </div>
                <div className="flex gap-2">
                  <Textarea
                    rows={3}
                    value={draft}
                    onChange={(event) => setDraft(event.target.value)}
                    placeholder="Add today's enumerator flag rates, worst first."
                    onKeyDown={(event) => {
                      if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
                        event.preventDefault();
                        send();
                      }
                    }}
                  />
                  <Button disabled={!draft.trim() || busy} onClick={send}>
                    <Send className="h-4 w-4" />
                  </Button>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="space-y-3 p-4">
                <div className="flex items-center justify-between gap-2">
                  <h3 className="text-sm font-medium">Live preview</h3>
                  <div className="flex items-center gap-2">
                    {previewConversation.isPending ? (
                      <span className="text-xs text-muted-foreground">Refreshing…</span>
                    ) : null}
                    {preview?.aiSource ? (
                      <Badge variant="outline" className="text-[10px]">
                        {preview.aiSource}
                      </Badge>
                    ) : null}
                  </div>
                </div>
                {previewConversation.isPending && !preview ? (
                  <p className="text-sm text-muted-foreground">Generating preview…</p>
                ) : preview?.html ? (
                  <iframe
                    title="Server-rendered preview"
                    className="h-[min(70vh,720px)] w-full rounded-md border bg-white"
                    srcDoc={preview.html}
                  />
                ) : (
                  <div className="flex h-48 flex-col items-center justify-center gap-2 text-sm text-muted-foreground">
                    <MessageSquare className="h-6 w-6" />
                    Preview appears once the planner produces a specification.
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </RequireActiveStudy>
      </div>

      <Dialog open={saveOpen} onOpenChange={setSaveOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Save conversation as template</DialogTitle>
          </DialogHeader>
          <div>
            <Label htmlFor="save-name">Template name</Label>
            <Input id="save-name" value={saveName} onChange={(event) => setSaveName(event.target.value)} />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setSaveOpen(false)}>
              Cancel
            </Button>
            <Button
              disabled={!saveName.trim() || !conversationId || saveTemplate.isPending}
              onClick={() =>
                saveTemplate.mutate({
                  conversationId,
                  data: { name: saveName.trim(), reportKind: "adhoc" },
                })
              }
            >
              {saveTemplate.isPending ? "Saving…" : "Save template"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ComposerHelpSheet
        open={helpOpen}
        onOpenChange={setHelpOpen}
        catalog={catalogQuery.data}
        loading={catalogQuery.isLoading}
        error={catalogQuery.error?.message ?? null}
        onTryPrompt={(prompt) => setDraft(prompt)}
      />
    </Layout>
  );
}
