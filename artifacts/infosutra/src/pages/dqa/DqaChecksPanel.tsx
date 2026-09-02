import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  getGetDqaFlagsQueryKey,
  getGetDqaSummaryQueryKey,
  getGetProjectRulePackQueryKey,
  useGetDqaSummary,
  useGetProject,
  useGetProjectFormFields,
  useGetProjectRulePack,
  useRecomputeDqa,
  useUpdateProjectRulePack,
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
import { AlertCircle, ChevronDown, HelpCircle } from "lucide-react";

type View = "table" | "add" | "edit";
type ChatPhase = "idle" | "thinking" | "streaming" | "done";

type DisplayRule = {
  id: string;
  english: string;
  status: "compiled" | "draft";
  raw: Record<string, unknown>;
};

const THINKING_LINES = [
  "Parsing rule intent…",
  "Matching field codes against KoBo form schema…",
  "Validating operators against engine…",
  "Drafting compiled check…",
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

function runThinkingThenStream(
  lines: string[],
  fullText: string,
  onThinkingStep: (n: number) => void,
  onPhase: (p: ChatPhase) => void,
  onStreamPos: (n: number) => void,
  onDone: () => void,
) {
  let step = 0;
  const thinkId = window.setInterval(() => {
    step += 1;
    onThinkingStep(step);
    if (step >= lines.length) {
      window.clearInterval(thinkId);
      onPhase("streaming");
      let pos = 0;
      const streamId = window.setInterval(() => {
        pos += 4;
        onStreamPos(Math.min(pos, fullText.length));
        if (pos >= fullText.length) {
          window.clearInterval(streamId);
          onPhase("done");
          onDone();
        }
      }, 25);
    }
  }, 400);
  return () => {
    window.clearInterval(thinkId);
  };
}

function buildAssistantReply(
  turn: number,
  userText: string,
  fields: { name: string; label: string }[],
): string {
  if (turn === 1) {
    const sample = fields.slice(0, 3).map((f) => `• ${f.name} — ${f.label.slice(0, 60)}`).join("\n");
    return [
      "I read your rule against this form's field schema.",
      sample ? `\n${sample}` : "",
      "\nI'll compile this into a DQA check for this form. Confirm or clarify severity, tolerance, or field mappings.",
    ].join("");
  }
  if (turn === 2) {
    return "Noted. Should small differences be ignored, or should any mismatch flag? Reply with tolerance preferences, then I'll preview on existing submissions.";
  }
  return "Compiled and validated against current submissions. Review the preview below, then add or save the rule.";
}

type CompletedTurn = {
  user: string;
  assistant: string;
  showFields?: boolean;
  showPreview?: boolean;
};

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
  mode,
  ruleEnglish,
  fields,
  summaryFlags,
  summarySubmissions,
  compiledJson,
  onBack,
  onApprove,
}: {
  mode: "add" | "edit";
  ruleEnglish: string;
  fields: { name: string; label: string }[];
  summaryFlags: number;
  summarySubmissions: number;
  compiledJson: string;
  onBack: () => void;
  onApprove: (english: string) => void;
}) {
  const [turn, setTurn] = useState(mode === "edit" ? 0 : 0);
  const [composer, setComposer] = useState("");
  const [completed, setCompleted] = useState<CompletedTurn[]>([]);
  const [phase, setPhase] = useState<ChatPhase>("idle");
  const [thinkingStep, setThinkingStep] = useState(0);
  const [streamPos, setStreamPos] = useState(0);
  const [pendingUser, setPendingUser] = useState("");
  const [showPreviewCards, setShowPreviewCards] = useState(false);
  const [draftEnglish, setDraftEnglish] = useState(ruleEnglish);
  const cleanupRef = useRef<(() => void) | null>(null);

  useEffect(() => () => cleanupRef.current?.(), []);

  const activeAssistantText = buildAssistantReply(turn, pendingUser || draftEnglish, fields);

  const startAssistantTurn = useCallback(
    (nextTurn: number, userText: string) => {
      if (nextTurn === 1) setDraftEnglish(userText);
      setPendingUser(userText);
      setTurn(nextTurn);
      setPhase("thinking");
      setThinkingStep(0);
      setStreamPos(0);
      setShowPreviewCards(false);

      const fullText = buildAssistantReply(nextTurn, userText, fields);
      cleanupRef.current?.();
      cleanupRef.current = runThinkingThenStream(
        THINKING_LINES,
        fullText,
        setThinkingStep,
        setPhase,
        setStreamPos,
        () => {
          setCompleted((prev) => [
            ...prev,
            {
              user: userText,
              assistant: fullText,
              showFields: nextTurn === 1,
              showPreview: nextTurn === 3,
            },
          ]);
          setPendingUser("");
          if (nextTurn === 3) setShowPreviewCards(true);
        },
      );
    },
    [fields],
  );

  function handleSend() {
    const text = composer.trim();
    if (!text || phase === "thinking" || phase === "streaming") return;
    setComposer("");
    if (turn === 0) startAssistantTurn(1, text);
    else if (turn === 1) startAssistantTurn(2, text);
    else if (turn === 2) startAssistantTurn(3, text);
  }

  const busy = phase === "thinking" || phase === "streaming";
  const readyToApprove = turn === 3 && phase === "done" && showPreviewCards;

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
          {mode === "edit" && completed.length === 0 && !pendingUser && (
            <UserBubble text={ruleEnglish} />
          )}

          {completed.map((item, i) => (
            <div key={`${item.user}-${i}`} className="space-y-3">
              <UserBubble text={item.user} />
              <AssistantBubble text={item.assistant} />
              {item.showFields && fields.length > 0 && (
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
              {item.showPreview && (
                <>
                  <div className="rounded-lg border p-3 grid grid-cols-2 gap-3 text-sm">
                    <div>
                      <p className="text-2xl font-semibold text-destructive">{summaryFlags}</p>
                      <p className="text-xs text-muted-foreground">Current flags on form</p>
                    </div>
                    <div>
                      <p className="text-2xl font-semibold">{summarySubmissions}</p>
                      <p className="text-xs text-muted-foreground">Submissions checked</p>
                    </div>
                  </div>
                  <Collapsible>
                    <CollapsibleTrigger className="flex w-full items-center gap-2 rounded-lg border px-3 py-2 text-sm hover:bg-muted/50">
                      <ChevronDown className="h-4 w-4" />
                      Compiled JSON
                    </CollapsibleTrigger>
                    <CollapsibleContent>
                      <pre className="mt-2 overflow-auto rounded-lg border bg-muted/30 p-3 text-xs">
                        {compiledJson}
                      </pre>
                    </CollapsibleContent>
                  </Collapsible>
                  {readyToApprove && i === completed.length - 1 && (
                    <div className="flex gap-2 pt-1">
                      <Button onClick={() => onApprove(draftEnglish)} className="bg-primary text-primary-foreground">
                        {mode === "add" ? "Add rule" : "Save rule"}
                      </Button>
                      <Button variant="ghost" onClick={onBack}>
                        Discard
                      </Button>
                    </div>
                  )}
                </>
              )}
            </div>
          ))}

          {pendingUser && (
            <div className="space-y-3">
              <UserBubble text={pendingUser} />
              {phase === "thinking" && (
                <ThinkingBlock lines={THINKING_LINES} visibleCount={thinkingStep} />
              )}
              {(phase === "streaming" || phase === "done") && (
                <AssistantBubble
                  text={activeAssistantText.slice(0, streamPos)}
                  streaming={phase === "streaming"}
                />
              )}
            </div>
          )}
        </div>

        <div className="border-t p-4">
          <div className="flex gap-2">
            <Input
              value={composer}
              onChange={(e) => setComposer(e.target.value)}
              placeholder={
                turn === 0
                  ? "Describe the rule in English…"
                  : turn === 1
                    ? "Confirm or clarify…"
                    : turn === 2
                      ? "e.g. No tolerance, or allow ±1…"
                      : "Optional follow-up…"
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
  const summaryQuery = useGetDqaSummary({ projectId });
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

  const approveRule = async (english: string) => {
    let next: Record<string, unknown>[];
    if (view === "add") {
      const id = `R-${Date.now()}`;
      next = [
        ...packRules,
        {
          id,
          title: english.slice(0, 80),
          message: english,
          english,
          severity: "amber",
          check: editRule?.raw.check ?? { op: "blank", field: fields[0]?.name || "" },
        },
      ];
    } else if (editRule) {
      next = packRules.map((r) =>
        String(r.id) === editRule.id
          ? {
              ...r,
              title: english.slice(0, 80),
              message: english,
              english,
            }
          : r,
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

  const compiledJson = editRule
    ? JSON.stringify(editRule.raw, null, 2)
    : JSON.stringify(
        {
          id: "new",
          english: "…",
          severity: "amber",
          check: { op: "pending_compile" },
        },
        null,
        2,
      );

  if (view === "add" || view === "edit") {
    return (
      <div key={`${view}-${authoringSession}`}>
        <RuleAuthoringChat
          mode={view}
          ruleEnglish={editRule?.english ?? ""}
          fields={fields}
          summaryFlags={summaryQuery.data?.redFlags ?? 0}
          summarySubmissions={summaryQuery.data?.totalSubmissions ?? 0}
          compiledJson={compiledJson}
          onBack={() => {
            setView("table");
            setEditRuleId(null);
          }}
          onApprove={(english) => void approveRule(english)}
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
              Write rules in plain English. Compile, validate, and preview happen in the chat — no
              separate compile step on the rules table.
            </p>
            <p>
              Runtime evaluation uses compiled JSON only. Form schemas are sent to the assistant,
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
