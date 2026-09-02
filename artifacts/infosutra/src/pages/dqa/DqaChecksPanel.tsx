import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  getGetDqaFlagsQueryKey,
  getGetDqaSummaryQueryKey,
  getGetProjectRulePackQueryKey,
  useCompileDqaRule,
  useGetDqaSummary,
  useGetProject,
  useGetProjectFormFields,
  useGetProjectRulePack,
  useRecomputeDqa,
  useUpdateProjectRulePack,
  useValidateDqaRule,
  type DqaCompileInput,
  type DqaPreviewResult,
  type DqaValidationResult,
} from "@workspace/api-client-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { AlertCircle, ChevronDown, HelpCircle } from "lucide-react";

type View = "table" | "add" | "edit";
type ChatPhase = "idle" | "thinking" | "streaming" | "done";
type CompileStatus = "idle" | "loading" | "success" | "needs_clarification" | "invalid";

type DisplayRule = {
  id: string;
  english: string;
  status: "compiled" | "draft";
  raw: Record<string, unknown>;
};

type ConversationTurn = { role: "user" | "assistant"; content: string };

type CompileResponse = {
  status: string;
  question?: string;
  partialExplanation?: string;
  rule?: Record<string, unknown>;
  explanation?: string;
  message?: string;
  validation?: DqaValidationResult;
  preview?: DqaPreviewResult;
  lastProposal?: Record<string, unknown>;
};

const THINKING_LINES = [
  "Reading your requirement…",
  "Matching fields against the form schema…",
  "Selecting supported operators…",
  "Validating compiled check…",
];

function ruleEnglish(rule: Record<string, unknown>): string {
  if (typeof rule.english === "string" && rule.english.trim()) return rule.english.trim();
  if (typeof rule.message === "string" && rule.message.trim()) return rule.message.trim();
  if (typeof rule.title === "string" && rule.title.trim()) return rule.title.trim();
  return String(rule.id || "Untitled rule");
}

function packRulesToDisplay(rules: unknown[]): DisplayRule[] {
  return rules
    .filter((r): r is Record<string, unknown> => Boolean(r) && typeof r === "object")
    .map((rule) => ({
      id: String(rule.id || ""),
      english: ruleEnglish(rule),
      status: (rule as Record<string, unknown>)._draft ? "draft" : "compiled",
      raw: rule,
    }));
}

function runThinkingWhileLoading(
  onThinkingStep: (n: number) => void,
  onPhase: (p: ChatPhase) => void,
  onStreamPos: (n: number) => void,
  placeholder: string,
) {
  let step = 0;
  const thinkId = window.setInterval(() => {
    step += 1;
    onThinkingStep(step);
    if (step >= THINKING_LINES.length) {
      window.clearInterval(thinkId);
      onPhase("streaming");
      let pos = 0;
      const streamId = window.setInterval(() => {
        pos += 6;
        onStreamPos(Math.min(pos, placeholder.length));
        if (pos >= placeholder.length) {
          window.clearInterval(streamId);
          onPhase("done");
        }
      }, 20);
    }
  }, 350);
  return () => {
    window.clearInterval(thinkId);
  };
}

function UserBubble({ text }: { text: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[85%] rounded-xl bg-muted px-3.5 py-2.5 text-sm">{text}</div>
    </div>
  );
}

function ThinkingBlock({ lines, visibleCount }: { lines: string[]; visibleCount: number }) {
  return (
    <div className="border-l-2 border-border pl-3">
      <p className="text-xs font-semibold text-muted-foreground">Thinking</p>
      <div className="mt-1.5 space-y-1">
        {lines.slice(0, visibleCount).map((line) => (
          <p key={line} className="text-xs text-muted-foreground">
            {line}
          </p>
        ))}
        {visibleCount < lines.length && <p className="text-xs text-muted-foreground/60">…</p>}
      </div>
    </div>
  );
}

function AssistantBubble({ text, streaming }: { text: string; streaming?: boolean }) {
  return (
    <div className="space-y-1.5">
      <Badge variant="secondary" className="text-[10px]">
        Assistant
      </Badge>
      <p className="text-sm whitespace-pre-wrap">
        {text}
        {streaming && <span className="opacity-50">▌</span>}
      </p>
    </div>
  );
}

function RuleAuthoringChat({
  projectId,
  mode,
  initialEnglish,
  existingRule,
  fields,
  onBack,
  onApprove,
}: {
  projectId: string;
  mode: "add" | "edit";
  initialEnglish: string;
  existingRule: Record<string, unknown> | null;
  fields: { name: string; label: string }[];
  onBack: () => void;
  onApprove: (rule: Record<string, unknown>) => void;
}) {
  const compileRule = useCompileDqaRule();
  const validateRule = useValidateDqaRule();

  const [composer, setComposer] = useState("");
  const [conversation, setConversation] = useState<ConversationTurn[]>([]);
  const [transcript, setTranscript] = useState<ConversationTurn[]>(
    mode === "edit" && initialEnglish ? [{ role: "user", content: initialEnglish }] : [],
  );
  const [phase, setPhase] = useState<ChatPhase>("idle");
  const [thinkingStep, setThinkingStep] = useState(0);
  const [streamPos, setStreamPos] = useState(0);
  const [pendingAssistant, setPendingAssistant] = useState("");
  const [compileStatus, setCompileStatus] = useState<CompileStatus>("idle");
  const [compiledRule, setCompiledRule] = useState<Record<string, unknown> | null>(null);
  const [preview, setPreview] = useState<DqaPreviewResult | null>(null);
  const [validation, setValidation] = useState<DqaValidationResult | null>(null);
  const [compileError, setCompileError] = useState<string | null>(null);
  const [jsonDraft, setJsonDraft] = useState("");
  const cleanupRef = useRef<(() => void) | null>(null);

  useEffect(() => () => cleanupRef.current?.(), []);

  useEffect(() => {
    if (compiledRule) {
      setJsonDraft(JSON.stringify(compiledRule, null, 2));
    }
  }, [compiledRule]);

  const busy = compileStatus === "loading" || phase === "thinking" || phase === "streaming";
  const readyToApprove = compileStatus === "success" && compiledRule !== null;

  const handleCompileResponse = useCallback((data: CompileResponse, userText: string) => {
    if (data.status === "needs_clarification") {
      const question = data.question || "Could you clarify this rule?";
      setCompileStatus("needs_clarification");
      setCompiledRule(null);
      setPreview(null);
      setValidation(data.validation ?? null);
      setConversation((prev) => [
        ...prev,
        { role: "user", content: userText },
        { role: "assistant", content: question },
      ]);
      setTranscript((prev) => [
        ...prev,
        { role: "user", content: userText },
        { role: "assistant", content: question },
      ]);
      setPendingAssistant(question);
      return;
    }

    if (data.status === "success" && data.rule) {
      setCompileStatus("success");
      setCompiledRule(data.rule as Record<string, unknown>);
      setPreview(data.preview ?? null);
      setValidation(data.validation ?? null);
      const explanation = data.explanation || "Rule compiled and validated.";
      setConversation((prev) => [
        ...prev,
        { role: "user", content: userText },
        { role: "assistant", content: explanation },
      ]);
      setTranscript((prev) => [
        ...prev,
        { role: "user", content: userText },
        { role: "assistant", content: explanation },
      ]);
      setPendingAssistant(explanation);
      return;
    }

    const message =
      data.message ||
      data.validation?.errors?.map((e) => e.message).join("; ") ||
      "Compilation failed";
    setCompileStatus("invalid");
    setCompiledRule(null);
    setPreview(null);
    setValidation(data.validation ?? null);
    setCompileError(message);
    setConversation((prev) => [...prev, { role: "user", content: userText }]);
    setTranscript((prev) => [
      ...prev,
      { role: "user", content: userText },
      { role: "assistant", content: message },
    ]);
    setPendingAssistant(message);
  }, []);

  const runCompile = useCallback(
    async (userText: string) => {
      setCompileError(null);
      setCompileStatus("loading");
      setPhase("thinking");
      setThinkingStep(0);
      setStreamPos(0);
      setPendingAssistant("Compiling rule…");
      cleanupRef.current?.();
      cleanupRef.current = runThinkingWhileLoading(
        setThinkingStep,
        setPhase,
        setStreamPos,
        "Compiling rule…",
      );

      const payload: DqaCompileInput = {
        english: userText,
        conversation,
        existingRule: existingRule ?? undefined,
        previewLimit: 50,
      };

      try {
        const data = (await compileRule.mutateAsync({
          projectId,
          data: payload,
        })) as CompileResponse;
        cleanupRef.current?.();
        setPhase("done");
        handleCompileResponse(data, userText);
      } catch (err) {
        cleanupRef.current?.();
        setPhase("done");
        setCompileStatus("invalid");
        const message = err instanceof Error ? err.message : "Compile request failed";
        setCompileError(message);
        setTranscript((prev) => [
          ...prev,
          { role: "user", content: userText },
          { role: "assistant", content: message },
        ]);
        setPendingAssistant(message);
      }
    },
    [compileRule, conversation, existingRule, handleCompileResponse, projectId],
  );

  function handleSend() {
    const text = composer.trim();
    if (!text || busy) return;
    setComposer("");
    void runCompile(text);
  }

  async function handleRevalidateJson() {
    setCompileError(null);
    try {
      const parsed = JSON.parse(jsonDraft) as Record<string, unknown>;
      const result = await validateRule.mutateAsync({
        projectId,
        data: { rule: parsed, previewLimit: 50 },
      });
      setValidation(result.validation);
      if (result.status === "success" && result.validation?.valid) {
        setCompiledRule(parsed);
        setPreview(result.preview ?? null);
        setCompileStatus("success");
      } else {
        setCompileStatus("invalid");
        setCompileError(result.message || "Rule failed validation");
      }
    } catch (err) {
      setCompileError(err instanceof Error ? err.message : "Invalid JSON");
      setCompileStatus("invalid");
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="sm" onClick={onBack}>
          Back
        </Button>
        <span className="text-sm font-semibold">{mode === "add" ? "Add rule" : "Edit rule"}</span>
      </div>

      <div className="mx-auto flex w-full max-w-2xl flex-col rounded-xl border bg-card min-h-[520px]">
        <div className="flex-1 overflow-auto p-4 space-y-5">
          {transcript.map((item, i) => (
            <div key={`${item.role}-${i}`} className="space-y-3">
              {item.role === "user" ? (
                <UserBubble text={item.content} />
              ) : (
                <AssistantBubble text={item.content} />
              )}
            </div>
          ))}

          {busy && (
            <div className="space-y-3">
              {phase === "thinking" && (
                <ThinkingBlock lines={THINKING_LINES} visibleCount={thinkingStep} />
              )}
              {(phase === "streaming" || phase === "done") && pendingAssistant && (
                <AssistantBubble
                  text={pendingAssistant.slice(0, streamPos || pendingAssistant.length)}
                  streaming={phase === "streaming"}
                />
              )}
            </div>
          )}

          {compileStatus === "success" && preview && (
            <div className="rounded-lg border p-3 grid grid-cols-2 gap-3 text-sm">
              <div>
                <p className="text-2xl font-semibold text-destructive">{preview.flagCount}</p>
                <p className="text-xs text-muted-foreground">Would flag (preview)</p>
              </div>
              <div>
                <p className="text-2xl font-semibold">{preview.submissionsChecked}</p>
                <p className="text-xs text-muted-foreground">Submissions checked</p>
              </div>
            </div>
          )}

          {validation && !validation.valid && (validation.errors?.length ?? 0) > 0 && (
            <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive space-y-1">
              {(validation.errors ?? []).map((err) => (
                <p key={`${err.path}-${err.code}`}>
                  {err.path ? `${err.path}: ` : ""}
                  {err.message}
                </p>
              ))}
            </div>
          )}

          {compileError && compileStatus === "invalid" && (
            <div className="flex gap-2 text-sm text-destructive">
              <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
              {compileError}
            </div>
          )}

          {fields.length > 0 && compileStatus === "success" && (
            <div className="rounded-lg border p-3 text-sm">
              <p className="mb-2 font-semibold">Form fields (sample)</p>
              <ul className="space-y-1 text-xs text-muted-foreground">
                {fields.slice(0, 6).map((f) => (
                  <li key={f.name}>
                    <span className="font-mono">{f.name}</span> — {f.label.slice(0, 80)}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {(compiledRule || jsonDraft) && (
            <Collapsible defaultOpen={compileStatus === "success"}>
              <CollapsibleTrigger className="flex w-full items-center gap-2 rounded-lg border px-3 py-2 text-sm hover:bg-muted/50">
                <ChevronDown className="h-4 w-4" />
                Compiled JSON
              </CollapsibleTrigger>
              <CollapsibleContent className="space-y-2 pt-2">
                <Textarea
                  value={jsonDraft}
                  onChange={(e) => setJsonDraft(e.target.value)}
                  className="font-mono text-xs min-h-[160px]"
                />
                <Button variant="outline" size="sm" onClick={() => void handleRevalidateJson()}>
                  Re-validate & preview
                </Button>
              </CollapsibleContent>
            </Collapsible>
          )}

          {readyToApprove && (
            <div className="flex gap-2 pt-1">
              <Button
                onClick={() => compiledRule && onApprove(compiledRule)}
                className="bg-primary text-primary-foreground"
              >
                {mode === "add" ? "Add rule" : "Save rule"}
              </Button>
              <Button variant="ghost" onClick={onBack}>
                Discard
              </Button>
            </div>
          )}
        </div>

        <div className="border-t p-4">
          <div className="flex gap-2">
            <Input
              value={composer}
              onChange={(e) => setComposer(e.target.value)}
              placeholder={
                compileStatus === "needs_clarification"
                  ? "Answer the clarification…"
                  : "Describe the rule in English…"
              }
              disabled={busy}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSend();
                }
              }}
            />
            <Button onClick={handleSend} disabled={busy || !composer.trim()}>
              Send
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

export function DqaChecksPanel({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const projectQuery = useGetProject(projectId);
  const fieldsQuery = useGetProjectFormFields(projectId, {
    query: { enabled: Boolean(projectId) } as never,
  });
  const packQuery = useGetProjectRulePack(projectId, {
    query: { enabled: Boolean(projectId) } as never,
  });
  const updatePack = useUpdateProjectRulePack();
  const recompute = useRecomputeDqa();

  const [view, setView] = useState<View>("table");
  const [helpOpen, setHelpOpen] = useState(false);
  const [editRuleId, setEditRuleId] = useState<string | null>(null);
  const [authoringSession, setAuthoringSession] = useState(0);
  const [packRules, setPackRules] = useState<Record<string, unknown>[]>([]);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    if (!packQuery.data?.pack) return;
    const rawRules = Array.isArray(packQuery.data.pack.rules) ? packQuery.data.pack.rules : [];
    setPackRules(rawRules as Record<string, unknown>[]);
  }, [packQuery.data]);

  const displayRules = useMemo(() => packRulesToDisplay(packRules), [packRules]);
  const editRule = displayRules.find((r) => r.id === editRuleId);
  const fields = useMemo(
    () =>
      (fieldsQuery.data ?? []).map((f) => ({
        name: f.name,
        label: f.label,
      })),
    [fieldsQuery.data],
  );

  const saveRules = async (nextRules: Record<string, unknown>[]) => {
    setSaveError(null);
    setIsSaving(true);
    try {
      const existing = packQuery.data?.pack || {};
      const pack = {
        ...existing,
        id: existing.id || projectQuery.data?.uid || projectId,
        project_uids: existing.project_uids || [projectQuery.data?.uid || projectId],
        rules: nextRules,
      };
      await updatePack.mutateAsync({ projectId, data: { pack } });
      await recompute.mutateAsync({ params: { projectId } });
      setPackRules(nextRules);
      queryClient.invalidateQueries({ queryKey: getGetProjectRulePackQueryKey(projectId) });
      queryClient.invalidateQueries({ queryKey: getGetDqaSummaryQueryKey() });
      queryClient.invalidateQueries({ queryKey: getGetDqaFlagsQueryKey() });
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Save failed");
      throw err;
    } finally {
      setIsSaving(false);
    }
  };

  const deleteRule = async (ruleId: string) => {
    const next = packRules.filter((r) => String(r.id) !== ruleId);
    await saveRules(next);
  };

  const approveRule = async (compiled: Record<string, unknown>) => {
    let next: Record<string, unknown>[];
    if (view === "add") {
      const id = String(compiled.id || `R-${Date.now()}`);
      next = [...packRules, { ...compiled, id }];
    } else if (editRule) {
      next = packRules.map((r) =>
        String(r.id) === editRule.id ? { ...compiled, id: editRule.id } : r,
      );
    } else {
      return;
    }
    await saveRules(next);
    setView("table");
    setEditRuleId(null);
  };

  const error =
    projectQuery.error?.message ||
    fieldsQuery.error?.message ||
    packQuery.error?.message ||
    saveError;

  if (view === "add" || view === "edit") {
    return (
      <div key={`${view}-${authoringSession}`}>
        <RuleAuthoringChat
          projectId={projectId}
          mode={view}
          initialEnglish={editRule?.english ?? ""}
          existingRule={editRule?.raw ?? null}
          fields={fields}
          onBack={() => {
            setView("table");
            setEditRuleId(null);
          }}
          onApprove={(rule) => void approveRule(rule)}
        />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-sm font-semibold">DQA checks</p>
        {projectQuery.data?.name && (
          <span className="text-sm text-muted-foreground">· {projectQuery.data.name}</span>
        )}
        <div className="flex-1" />
        <Button variant="ghost" size="sm" onClick={() => setHelpOpen((v) => !v)}>
          <HelpCircle className="h-4 w-4 mr-1" />
          Help
        </Button>
        <Button variant="outline" size="sm" disabled>
          Upload docx
        </Button>
        <Button
          size="sm"
          className="bg-primary text-primary-foreground"
          disabled={isSaving}
          onClick={() => {
            setEditRuleId(null);
            setAuthoringSession((n) => n + 1);
            setView("add");
          }}
        >
          Add rule in English
        </Button>
      </div>

      {helpOpen && (
        <Card>
          <CardContent className="p-4 text-sm text-muted-foreground space-y-2">
            <p>
              Write rules in plain English. The compiler validates against this form&apos;s schema,
              previews on recent submissions, and saves deterministic JSON checks.
            </p>
            <p>
              Runtime evaluation uses compiled JSON only. Form schemas are sent to the compiler,
              not submission PII.
            </p>
          </CardContent>
        </Card>
      )}

      {error && (
        <div className="flex gap-2 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
          <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
          {error}
        </div>
      )}

      <Card>
        <div className="overflow-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/40 text-left">
                <th className="p-3 w-12">#</th>
                <th className="p-3">Rule</th>
                <th className="p-3 w-28">Status</th>
                <th className="p-3 w-48 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {displayRules.length === 0 ? (
                <tr>
                  <td colSpan={4} className="p-6 text-center text-muted-foreground">
                    No rules yet. Add one in English or sync form data to load seeded rules.
                  </td>
                </tr>
              ) : (
                displayRules.map((rule, index) => (
                  <tr key={rule.id || index} className="border-b last:border-0">
                    <td className="p-3 text-muted-foreground">{index + 1}</td>
                    <td className="p-3">{rule.english}</td>
                    <td className="p-3">
                      <Badge variant={rule.status === "compiled" ? "default" : "secondary"}>
                        {rule.status === "compiled" ? "Compiled" : "Draft"}
                      </Badge>
                    </td>
                    <td className="p-3">
                      <div className="flex justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => {
                            setEditRuleId(rule.id);
                            setAuthoringSession((n) => n + 1);
                            setView("edit");
                          }}
                        >
                          Edit via chat
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={isSaving}
                          onClick={() => void deleteRule(rule.id)}
                        >
                          Delete
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
