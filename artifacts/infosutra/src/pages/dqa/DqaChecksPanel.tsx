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
  useSetDqaRuleLifecycle,
  useTestDqaRule,
  useUpdateProjectRulePack,
  useValidateDqaRule,
  type DqaCompileInput,
  type DqaPreviewResult,
  type DqaRuleWarning,
  type DqaTestRecord,
  type DqaTestRuleOut,
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { AlertCircle, ChevronDown, HelpCircle, Search } from "lucide-react";

type View = "table" | "add" | "edit";
type ChatPhase = "idle" | "thinking" | "streaming" | "done";
type CompileStatus = "idle" | "loading" | "success" | "needs_clarification" | "invalid";
type RuleLifecycleStatus = "draft" | "reviewed" | "approved" | "active";

type DisplayRule = {
  id: string;
  english: string;
  description: string;
  status: RuleLifecycleStatus;
  enabled: boolean;
  group: string;
  raw: Record<string, unknown>;
};

type RuleDiff = {
  changeCount?: number;
  changes?: Array<{
    path: string;
    change: string;
    before?: unknown;
    after?: unknown;
  }>;
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
  test?: DqaTestRuleOut;
  diff?: RuleDiff;
  warnings?: DqaRuleWarning[];
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

function ruleLifecycleStatus(rule: Record<string, unknown>): RuleLifecycleStatus {
  const status = String(rule.status || "").toLowerCase();
  if (status === "draft" || status === "reviewed" || status === "approved" || status === "active") {
    return status;
  }
  if (rule._draft) return "draft";
  return "active";
}

function ruleIsEnabled(rule: Record<string, unknown>): boolean {
  if (rule.enabled === false) return false;
  return ruleLifecycleStatus(rule) === "active";
}

function applyLifecycle(
  rule: Record<string, unknown>,
  status: RuleLifecycleStatus,
): Record<string, unknown> {
  const meta = (rule.meta && typeof rule.meta === "object" ? rule.meta : {}) as Record<
    string,
    unknown
  >;
  const audit = (meta.audit && typeof meta.audit === "object" ? meta.audit : {}) as Record<
    string,
    unknown
  >;
  return {
    ...rule,
    status,
    enabled: status === "active",
    meta: {
      ...meta,
      audit: {
        ...audit,
        status,
        ...(status === "active"
          ? { approved: true, activated_at: new Date().toISOString() }
          : {}),
      },
    },
  };
}

function packRulesToDisplay(rules: unknown[]): DisplayRule[] {
  return rules
    .filter((r): r is Record<string, unknown> => Boolean(r) && typeof r === "object")
    .map((rule) => ({
      id: String(rule.id || ""),
      english: ruleEnglish(rule),
      description: String(rule.description || rule.title || "").trim(),
      status: ruleLifecycleStatus(rule),
      enabled: ruleIsEnabled(rule),
      group: String(rule.group || "").trim(),
      raw: rule,
    }));
}

function statusBadgeVariant(
  status: RuleLifecycleStatus,
): "default" | "secondary" | "outline" | "destructive" {
  if (status === "active") return "default";
  if (status === "draft") return "secondary";
  if (status === "approved") return "outline";
  return "outline";
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

function WarningsList({ warnings }: { warnings: DqaRuleWarning[] }) {
  if (!warnings.length) return null;
  return (
    <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-sm space-y-1">
      <p className="font-semibold text-amber-800 dark:text-amber-200">Quality warnings</p>
      {warnings.map((w) => (
        <p key={`${w.code}-${w.message}`} className="text-xs text-amber-900 dark:text-amber-100">
          {w.message}
        </p>
      ))}
    </div>
  );
}

function RuleDiffPanel({ diff }: { diff: RuleDiff | null }) {
  if (!diff?.changes?.length) return null;
  return (
    <Collapsible defaultOpen>
      <CollapsibleTrigger className="flex w-full items-center gap-2 rounded-lg border px-3 py-2 text-sm hover:bg-muted/50">
        <ChevronDown className="h-4 w-4" />
        Proposed changes ({diff.changeCount ?? diff.changes.length})
      </CollapsibleTrigger>
      <CollapsibleContent className="pt-2 space-y-1">
        {diff.changes.map((change) => (
          <div key={change.path} className="rounded border px-2 py-1.5 text-xs font-mono">
            <span className="text-muted-foreground">{change.path}</span>{" "}
            <Badge variant="outline" className="text-[10px] ml-1">
              {change.change}
            </Badge>
            {change.before !== undefined && (
              <p className="text-destructive mt-0.5">− {JSON.stringify(change.before)}</p>
            )}
            {change.after !== undefined && (
              <p className="text-green-700 dark:text-green-400 mt-0.5">
                + {JSON.stringify(change.after)}
              </p>
            )}
          </div>
        ))}
      </CollapsibleContent>
    </Collapsible>
  );
}

function explanationLines(record: DqaTestRecord): string[] {
  const exp = record.explanation;
  if (exp && typeof exp === "object" && "lines" in exp && Array.isArray(exp.lines)) {
    return exp.lines.map(String);
  }
  if (exp && typeof exp === "object" && "summary" in exp && typeof exp.summary === "string") {
    return [exp.summary];
  }
  return [];
}

function previewToTest(preview: DqaPreviewResult | null): DqaTestRuleOut | null {
  if (!preview) return null;
  return {
    submissionsChecked: preview.submissionsChecked,
    flagCount: preview.flagCount,
    passCount: preview.passCount,
    notApplicableCount: preview.notApplicableCount,
    examples: (preview.examples ?? []).map((ex) => ({
      submissionId: ex.submissionId,
      koboId: ex.koboId,
      enumerator: ex.enumerator,
      outcome: ex.outcome ?? (ex.wouldFlag ? "fail" : "pass"),
      wouldFlag: ex.wouldFlag,
      explanation: ex.explanation ?? {},
      details: ex.details ?? {},
    })),
    warnings: preview.warnings,
  };
}

function RuleTestWorkspace({ test }: { test: DqaTestRuleOut | null }) {
  if (!test) return null;
  const examples = test.records?.length ? test.records : test.examples ?? [];
  return (
    <div className="rounded-lg border p-3 space-y-3 text-sm">
      <p className="font-semibold">Rule test workspace</p>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div>
          <p className="text-2xl font-semibold">{test.submissionsChecked}</p>
          <p className="text-xs text-muted-foreground">Records tested</p>
        </div>
        <div>
          <p className="text-2xl font-semibold text-green-700 dark:text-green-400">
            {test.passCount}
          </p>
          <p className="text-xs text-muted-foreground">Passing</p>
        </div>
        <div>
          <p className="text-2xl font-semibold text-destructive">{test.flagCount}</p>
          <p className="text-xs text-muted-foreground">Failing / flagged</p>
        </div>
        <div>
          <p className="text-2xl font-semibold text-muted-foreground">
            {test.missingDataCount ?? 0}
          </p>
          <p className="text-xs text-muted-foreground">Missing data</p>
        </div>
      </div>
      {(test.notApplicableCount ?? 0) > 0 && (
        <p className="text-xs text-muted-foreground">
          {test.notApplicableCount} not applicable
          {(test.ambiguousRelatedCount ?? 0) > 0 &&
            ` · ${test.ambiguousRelatedCount} ambiguous related matches`}
        </p>
      )}
      {examples.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-semibold text-muted-foreground">Sample records</p>
          {examples.slice(0, 6).map((row) => (
            <Collapsible key={row.submissionId}>
              <CollapsibleTrigger className="flex w-full items-center justify-between rounded border px-2 py-1.5 text-left text-xs hover:bg-muted/40">
                <span>
                  {row.koboId || row.submissionId}
                  {row.enumerator ? ` · ${row.enumerator}` : ""}
                </span>
                <Badge
                  variant={
                    row.outcome === "fail"
                      ? "destructive"
                      : row.outcome === "pass"
                        ? "default"
                        : "secondary"
                  }
                  className="text-[10px]"
                >
                  {row.outcome}
                </Badge>
              </CollapsibleTrigger>
              <CollapsibleContent className="px-2 py-1.5 space-y-1 text-xs">
                {explanationLines(row).map((line) => (
                  <p key={line} className="text-muted-foreground">
                    {line}
                  </p>
                ))}
                {row.fieldValues && Object.keys(row.fieldValues).length > 0 && (
                  <div className="font-mono text-[11px] space-y-0.5">
                    {Object.entries(row.fieldValues).map(([k, v]) => (
                      <p key={k}>
                        {k}: {JSON.stringify(v)}
                      </p>
                    ))}
                  </div>
                )}
                {(row.related?.length ?? 0) > 0 && (
                  <div className="text-[11px] text-muted-foreground">
                    {row.related!.map((rel) => (
                      <p key={String(rel.relationship)}>
                        Related: {String(rel.relationship)} ({String(rel.status)})
                        {rel.joinKey ? ` · join ${String(rel.joinKey)}` : ""}
                      </p>
                    ))}
                  </div>
                )}
                {row.debugTrace && Object.keys(row.debugTrace).length > 0 && (
                  <Collapsible>
                    <CollapsibleTrigger className="text-[11px] underline">
                      Debug trace
                    </CollapsibleTrigger>
                    <CollapsibleContent>
                      <pre className="text-[10px] overflow-auto max-h-32">
                        {JSON.stringify(row.debugTrace, null, 2)}
                      </pre>
                    </CollapsibleContent>
                  </Collapsible>
                )}
              </CollapsibleContent>
            </Collapsible>
          ))}
        </div>
      )}
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
  onApprove: (rule: Record<string, unknown>, lifecycle: RuleLifecycleStatus) => void;
}) {
  const compileRule = useCompileDqaRule();
  const validateRule = useValidateDqaRule();
  const testRuleMutation = useTestDqaRule();

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
  const [testResult, setTestResult] = useState<DqaTestRuleOut | null>(null);
  const [ruleDiff, setRuleDiff] = useState<RuleDiff | null>(null);
  const [qualityWarnings, setQualityWarnings] = useState<DqaRuleWarning[]>([]);
  const [validation, setValidation] = useState<DqaValidationResult | null>(null);
  const [compileError, setCompileError] = useState<string | null>(null);
  const [jsonDraft, setJsonDraft] = useState("");
  const [confirmActivate, setConfirmActivate] = useState(false);
  const cleanupRef = useRef<(() => void) | null>(null);

  const editingActiveRule =
    mode === "edit" && existingRule !== null && ruleLifecycleStatus(existingRule) === "active";

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
      setTestResult(null);
      setRuleDiff(null);
      setQualityWarnings([]);
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
      setTestResult(data.test ?? null);
      setRuleDiff(data.diff ?? null);
      setQualityWarnings(data.warnings ?? data.preview?.warnings ?? []);
      setValidation(data.validation ?? null);
      setConfirmActivate(false);
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
    setTestResult(null);
    setRuleDiff(null);
    setQualityWarnings([]);
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
        setTestResult(result.test ?? null);
        setQualityWarnings(result.warnings ?? result.test?.warnings ?? []);
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

  async function handleRunTest() {
    if (!compiledRule) return;
    try {
      const result = await testRuleMutation.mutateAsync({
        projectId,
        data: { rule: compiledRule, limit: 50 },
      });
      setTestResult(result);
      setQualityWarnings(result.warnings ?? []);
    } catch (err) {
      setCompileError(err instanceof Error ? err.message : "Test failed");
    }
  }

  function handleSave(lifecycle: RuleLifecycleStatus) {
    if (!compiledRule) return;
    if (lifecycle === "active" && editingActiveRule && !confirmActivate) {
      setConfirmActivate(true);
      return;
    }
    onApprove(applyLifecycle(compiledRule, lifecycle), lifecycle);
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

          {compileStatus === "success" && (testResult || preview) && (
            <RuleTestWorkspace test={testResult ?? previewToTest(preview)} />
          )}

          <WarningsList warnings={qualityWarnings} />

          {ruleDiff && <RuleDiffPanel diff={ruleDiff} />}

          {editingActiveRule && confirmActivate && (
            <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-3 text-sm space-y-2">
              <p className="font-semibold">Confirm activation</p>
              <p className="text-muted-foreground text-xs">
                This replaces the currently active rule. Review the diff above before activating.
              </p>
              <div className="flex gap-2">
                <Button size="sm" onClick={() => handleSave("active")}>
                  Confirm activate
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setConfirmActivate(false)}>
                  Cancel
                </Button>
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
                <Button variant="outline" size="sm" onClick={() => void handleRunTest()}>
                  Run test
                </Button>
              </CollapsibleContent>
            </Collapsible>
          )}

          {readyToApprove && (
            <div className="flex flex-wrap gap-2 pt-1">
              <Button variant="outline" onClick={() => handleSave("draft")}>
                Save as draft
              </Button>
              <Button
                onClick={() => handleSave("active")}
                className="bg-primary text-primary-foreground"
              >
                {mode === "add" ? "Activate rule" : "Save & activate"}
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
  const lifecycleMutation = useSetDqaRuleLifecycle();

  const [view, setView] = useState<View>("table");
  const [helpOpen, setHelpOpen] = useState(false);
  const [editRuleId, setEditRuleId] = useState<string | null>(null);
  const [authoringSession, setAuthoringSession] = useState(0);
  const [packRules, setPackRules] = useState<Record<string, unknown>[]>([]);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");

  useEffect(() => {
    if (!packQuery.data?.pack) return;
    const rawRules = Array.isArray(packQuery.data.pack.rules) ? packQuery.data.pack.rules : [];
    setPackRules(rawRules as Record<string, unknown>[]);
  }, [packQuery.data]);

  const displayRules = useMemo(() => packRulesToDisplay(packRules), [packRules]);
  const filteredRules = useMemo(() => {
    let items = displayRules;
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      items = items.filter(
        (r) =>
          r.english.toLowerCase().includes(q) ||
          r.id.toLowerCase().includes(q) ||
          r.description.toLowerCase().includes(q) ||
          r.group.toLowerCase().includes(q),
      );
    }
    if (statusFilter !== "all") {
      items = items.filter((r) => r.status === statusFilter);
    }
    return items;
  }, [displayRules, searchQuery, statusFilter]);
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

  const approveRule = async (
    compiled: Record<string, unknown>,
    lifecycle: RuleLifecycleStatus = "active",
  ) => {
    const withLifecycle = applyLifecycle(compiled, lifecycle);
    let next: Record<string, unknown>[];
    if (view === "add") {
      const id = String(withLifecycle.id || `R-${Date.now()}`);
      next = [...packRules, { ...withLifecycle, id }];
    } else if (editRule) {
      next = packRules.map((r) =>
        String(r.id) === editRule.id ? { ...withLifecycle, id: editRule.id } : r,
      );
    } else {
      return;
    }
    await saveRules(next);
    setView("table");
    setEditRuleId(null);
  };

  const setRuleLifecycle = async (ruleId: string, status: RuleLifecycleStatus) => {
    setSaveError(null);
    try {
      await lifecycleMutation.mutateAsync({
        projectId,
        ruleId,
        data: { status, enabled: status === "active" },
      });
      queryClient.invalidateQueries({ queryKey: getGetProjectRulePackQueryKey(projectId) });
      const updated = packRules.map((r) =>
        String(r.id) === ruleId ? applyLifecycle(r, status) : r,
      );
      setPackRules(updated);
      if (status === "active") {
        await recompute.mutateAsync({ params: { projectId } });
        queryClient.invalidateQueries({ queryKey: getGetDqaSummaryQueryKey() });
        queryClient.invalidateQueries({ queryKey: getGetDqaFlagsQueryKey() });
      }
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Lifecycle update failed");
    }
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
          onApprove={(rule, lifecycle) => void approveRule(rule, lifecycle)}
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
        <div className="flex flex-wrap items-center gap-2 border-b p-3">
          <div className="relative flex-1 min-w-[200px]">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search rules…"
              className="pl-8"
            />
          </div>
          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger className="w-[140px]">
              <SelectValue placeholder="Status" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All statuses</SelectItem>
              <SelectItem value="active">Active</SelectItem>
              <SelectItem value="draft">Draft</SelectItem>
              <SelectItem value="reviewed">Reviewed</SelectItem>
              <SelectItem value="approved">Approved</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="overflow-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/40 text-left">
                <th className="p-3 w-12">#</th>
                <th className="p-3">Rule</th>
                <th className="p-3 w-28">Status</th>
                <th className="p-3 w-24">Enabled</th>
                <th className="p-3 w-56 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredRules.length === 0 ? (
                <tr>
                  <td colSpan={5} className="p-6 text-center text-muted-foreground">
                    {displayRules.length === 0
                      ? "No rules yet. Add one in English or sync form data to load seeded rules."
                      : "No rules match your filters."}
                  </td>
                </tr>
              ) : (
                filteredRules.map((rule, index) => (
                  <tr key={rule.id || index} className="border-b last:border-0">
                    <td className="p-3 text-muted-foreground">{index + 1}</td>
                    <td className="p-3">
                      <p>{rule.english}</p>
                      {rule.description && rule.description !== rule.english && (
                        <p className="text-xs text-muted-foreground mt-0.5">{rule.description}</p>
                      )}
                      {rule.group && (
                        <Badge variant="outline" className="text-[10px] mt-1">
                          {rule.group}
                        </Badge>
                      )}
                    </td>
                    <td className="p-3">
                      <Badge variant={statusBadgeVariant(rule.status)}>{rule.status}</Badge>
                    </td>
                    <td className="p-3">
                      <Badge variant={rule.enabled ? "default" : "secondary"}>
                        {rule.enabled ? "On" : "Off"}
                      </Badge>
                    </td>
                    <td className="p-3">
                      <div className="flex justify-end gap-1 flex-wrap">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => {
                            setEditRuleId(rule.id);
                            setAuthoringSession((n) => n + 1);
                            setView("edit");
                          }}
                        >
                          Edit
                        </Button>
                        {rule.status !== "active" && (
                          <Button
                            variant="ghost"
                            size="sm"
                            disabled={isSaving}
                            onClick={() => void setRuleLifecycle(rule.id, "active")}
                          >
                            Activate
                          </Button>
                        )}
                        {rule.status === "active" && (
                          <Button
                            variant="ghost"
                            size="sm"
                            disabled={isSaving}
                            onClick={() => void setRuleLifecycle(rule.id, "draft")}
                          >
                            Disable
                          </Button>
                        )}
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
