import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQueries, useQueryClient } from "@tanstack/react-query";
import {
  getGetDqaFlagsQueryKey,
  getGetDqaSummaryQueryKey,
  getGetProjectRulePackQueryKey,
  getProjectRulePack,
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
import { AlertCircle, ArrowLeft, ChevronDown, HelpCircle, Search } from "lucide-react";

type View = "table" | "add" | "edit" | "edit-ai";
type ChatPhase = "idle" | "thinking" | "streaming" | "done";
type CompileStatus = "idle" | "loading" | "success" | "needs_clarification" | "invalid";
type RuleLifecycleStatus = "draft" | "reviewed" | "approved" | "active";

type DisplayRule = {
  id: string;
  english: string;
  description: string;
  status: RuleLifecycleStatus;
  enabled: boolean;
  severity: "red" | "amber";
  group: string;
  resolvedFields: ResolvedField[];
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

type ResolvedField = {
  code: string;
  form: string;
  label: string;
};

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
  resolvedFields?: ResolvedField[];
  sourceProjectId?: string;
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

function ruleSeverity(rule: Record<string, unknown>): "red" | "amber" {
  return String(rule.severity || "").toLowerCase() === "red" ? "red" : "amber";
}

function cleanAiExplanation(text: string): string {
  return text
    .replace(/\n*\s*Is that correct\??\s*$/i, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function ruleResolvedFields(rule: Record<string, unknown>): ResolvedField[] {
  const raw = rule.resolvedFields ?? rule.resolved_fields;
  if (!Array.isArray(raw)) return [];
  const rows: ResolvedField[] = [];
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const row = item as Record<string, unknown>;
    const code = String(row.code || "").trim();
    if (!code) continue;
    rows.push({
      code,
      form: String(row.form || "").trim() || "—",
      label: String(row.label || "").trim() || code,
    });
  }
  return rows;
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
      severity: ruleSeverity(rule),
      group: String(rule.group || "").trim(),
      resolvedFields: ruleResolvedFields(rule),
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

function RuleStatusBadge({
  status,
  severity,
}: {
  status: RuleLifecycleStatus;
  severity: "red" | "amber";
}) {
  if (status === "active") {
    if (severity === "red") {
      return <Badge variant="destructive">{status}</Badge>;
    }
    return (
      <Badge className="border-transparent bg-amber-100 text-amber-900 hover:bg-amber-100 dark:bg-amber-950/60 dark:text-amber-200">
        {status}
      </Badge>
    );
  }
  return <Badge variant={statusBadgeVariant(status)}>{status}</Badge>;
}

function ResolvedFieldsTable({ fields }: { fields: ResolvedField[] }) {
  if (!fields.length) {
    return <p className="text-xs text-muted-foreground">No resolved fields stored for this rule.</p>;
  }
  return (
    <div className="overflow-x-auto rounded-md border bg-background">
      <table className="w-full min-w-[360px] text-xs">
        <thead className="bg-muted/50 text-left">
          <tr>
            <th className="p-2 font-medium">Code</th>
            <th className="p-2 font-medium">Form</th>
            <th className="p-2 font-medium">Label</th>
          </tr>
        </thead>
        <tbody>
          {fields.map((row) => (
            <tr key={`${row.code}-${row.form}`} className="border-t">
              <td className="p-2 font-mono">{row.code}</td>
              <td className="p-2 text-muted-foreground">{row.form}</td>
              <td className="p-2">{row.label}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RuleTableRows({
  rules,
  colSpan,
  renderFormCell,
  renderActions,
}: {
  rules: Array<DisplayRule & { projectId?: string; formLabel?: string }>;
  colSpan: number;
  renderFormCell?: (rule: DisplayRule & { projectId?: string; formLabel?: string }) => React.ReactNode;
  renderActions: (rule: DisplayRule & { projectId?: string; formLabel?: string }) => React.ReactNode;
}) {
  const [expandedIds, setExpandedIds] = useState<Record<string, boolean>>({});

  return (
    <>
      {rules.map((rule, index) => {
        const rowKey = `${rule.projectId || ""}:${rule.id || index}`;
        const open = Boolean(expandedIds[rowKey]);
        const hasDetails =
          Boolean(rule.description && rule.description !== rule.english) ||
          rule.resolvedFields.length > 0;
        return (
          <React.Fragment key={rowKey}>
            <tr className="border-b last:border-0">
              <td className="p-3 text-muted-foreground">
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    className="rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-40"
                    aria-expanded={open}
                    aria-label={open ? "Collapse rule details" : "Expand rule details"}
                    disabled={!hasDetails}
                    onClick={() =>
                      setExpandedIds((prev) => ({ ...prev, [rowKey]: !prev[rowKey] }))
                    }
                  >
                    <ChevronDown
                      className={`h-4 w-4 transition-transform ${open ? "rotate-180" : ""}`}
                    />
                  </button>
                  <span>{index + 1}</span>
                </div>
              </td>
              {renderFormCell ? <td className="p-3">{renderFormCell(rule)}</td> : null}
              <td className="p-3">
                <p>{rule.english}</p>
                {rule.group && (
                  <Badge variant="outline" className="text-[10px] mt-1">
                    {rule.group}
                  </Badge>
                )}
              </td>
              <td className="p-3">
                <RuleStatusBadge status={rule.status} severity={rule.severity} />
              </td>
              <td className="p-3">{renderActions(rule)}</td>
            </tr>
            {open && (
              <tr className="border-b bg-muted/20">
                <td colSpan={colSpan} className="p-4">
                  <div className="space-y-3 max-w-3xl">
                    <div className="space-y-1">
                      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                        AI summary
                      </p>
                      <p className="text-sm whitespace-pre-wrap">
                        {rule.description && rule.description !== rule.english
                          ? rule.description
                          : "No AI summary stored for this rule."}
                      </p>
                    </div>
                    <div className="space-y-1.5">
                      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                        Resolved fields
                      </p>
                      <ResolvedFieldsTable fields={rule.resolvedFields} />
                    </div>
                  </div>
                </td>
              </tr>
            )}
          </React.Fragment>
        );
      })}
    </>
  );
}

async function streamCompileDqaRule(
  projectId: string,
  payload: DqaCompileInput,
  handlers: {
    signal?: AbortSignal;
    onProgress?: (message: string, phase?: string, attempt?: number) => void;
    onToken?: (text: string) => void;
  } = {},
): Promise<CompileResponse> {
  const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}/dqa/compile/stream`, {
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
    throw new Error("Compile stream returned an empty body");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalResult: CompileResponse | null = null;
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
        typeof data.attempt === "number" ? data.attempt : undefined,
      );
      return;
    }
    if (eventName === "token") {
      if (typeof data.text === "string" && data.text) {
        handlers.onToken?.(data.text);
      }
      return;
    }
    if (eventName === "result") {
      finalResult = (data.data as CompileResponse) || (data as CompileResponse);
      return;
    }
    if (eventName === "error") {
      streamError = String(data.message || "Compile stream failed");
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
  if (!finalResult) throw new Error("Compile stream ended without a result");
  return finalResult;
}

function normalizeCompileResponse(data: CompileResponse): CompileResponse {
  const raw = data as CompileResponse & {
    resolved_fields?: ResolvedField[];
    partial_explanation?: string;
    last_proposal?: Record<string, unknown>;
    source_project_id?: string;
  };
  return {
    ...data,
    resolvedFields: data.resolvedFields ?? raw.resolved_fields ?? [],
    partialExplanation: data.partialExplanation ?? raw.partial_explanation,
    lastProposal: data.lastProposal ?? raw.last_proposal,
    sourceProjectId: data.sourceProjectId ?? raw.source_project_id,
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

function formatApiError(err: unknown, fallback: string): string {
  if (err instanceof Error && err.message && err.message !== "Error") {
    // Axios / fetch wrappers often put the useful payload on the error object
    const withResponse = err as Error & {
      response?: { data?: { detail?: unknown; message?: unknown } };
      data?: { detail?: unknown; message?: unknown };
    };
    const detail =
      withResponse.response?.data?.detail ??
      withResponse.data?.detail ??
      withResponse.response?.data?.message;
    if (typeof detail === "string" && detail.trim()) return detail;
    if (detail && typeof detail === "object") {
      const obj = detail as { message?: unknown; validation?: { errors?: Array<{ message?: string }> } };
      if (typeof obj.message === "string" && obj.message.trim()) {
        const first = obj.validation?.errors?.[0]?.message;
        return first ? `${obj.message}: ${first}` : obj.message;
      }
    }
    return err.message;
  }
  if (typeof err === "string" && err.trim()) return err;
  return fallback;
}

function RuleDetailsEditor({
  rule,
  onBack,
  onRewriteWithAi,
  onSave,
}: {
  rule: Record<string, unknown>;
  onBack: () => void;
  onRewriteWithAi: () => void;
  onSave: (
    next: Record<string, unknown>,
    lifecycle: RuleLifecycleStatus,
  ) => void | Promise<void>;
}) {
  const currentStatus = ruleLifecycleStatus(rule);
  const english = ruleEnglish(rule);
  const storedResolvedFields = ruleResolvedFields(rule);
  const [severity, setSeverity] = useState<"red" | "amber">(ruleSeverity(rule));
  const [title, setTitle] = useState(String(rule.title || "").trim());
  const [description, setDescription] = useState(
    String(rule.description || rule.message || "").trim(),
  );
  const [confirmActivate, setConfirmActivate] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  const editingActiveRule = currentStatus === "active";

  async function handleSave(lifecycle: RuleLifecycleStatus) {
    if (isSaving) return;
    if (lifecycle === "active" && editingActiveRule && !confirmActivate) {
      setConfirmActivate(true);
      return;
    }
    setSaveError(null);
    setIsSaving(true);
    try {
      const nextDescription = description.trim() || english || String(rule.message || "");
      const next: Record<string, unknown> = {
        ...rule,
        // English / check / resolved fields stay unchanged unless rewritten via AI
        english,
        severity,
        title: title.trim() || english.slice(0, 80) || String(rule.title || "DQA rule"),
        description: nextDescription,
        message: nextDescription,
        resolvedFields: storedResolvedFields,
      };
      await onSave(applyLifecycle(next, lifecycle), lifecycle);
    } catch (err) {
      setSaveError(formatApiError(err, "Save failed"));
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          className="gap-1 bg-primary text-primary-foreground"
          onClick={onBack}
          disabled={isSaving}
        >
          <ArrowLeft className="h-4 w-4" />
          Back
        </Button>
        <div className="flex-1" />
        <Button
          size="sm"
          disabled={isSaving}
          onClick={onRewriteWithAi}
          className="border-transparent bg-emerald-600 text-white hover:bg-emerald-700"
        >
          Rewrite with AI
        </Button>
      </div>

      <Card className="mx-auto w-full max-w-2xl">
        <CardContent className="space-y-4 p-4">
          <div className="space-y-1.5">
            <p className="text-sm font-medium">Rule</p>
            <div className="rounded-md border bg-muted/30 px-3 py-2.5 text-sm whitespace-pre-wrap">
              {english || "—"}
            </div>
          </div>

          <div className="space-y-1.5">
            <p className="text-sm font-medium">Severity color</p>
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                size="sm"
                variant={severity === "amber" ? "default" : "outline"}
                className={
                  severity === "amber"
                    ? "border-transparent bg-amber-100 text-amber-900 hover:bg-amber-100 dark:bg-amber-950/60 dark:text-amber-200"
                    : ""
                }
                onClick={() => setSeverity("amber")}
              >
                Amber
              </Button>
              <Button
                type="button"
                size="sm"
                variant={severity === "red" ? "destructive" : "outline"}
                onClick={() => setSeverity("red")}
              >
                Red
              </Button>
            </div>
          </div>

          <div className="space-y-1.5">
            <label className="text-sm font-medium" htmlFor="rule-title">
              Title
            </label>
            <Input
              id="rule-title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Short title shown in flags"
            />
          </div>

          <div className="space-y-1.5">
            <label className="text-sm font-medium" htmlFor="rule-description">
              Description
            </label>
            <Textarea
              id="rule-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="min-h-[80px]"
              placeholder="Description shown with this rule"
            />
          </div>

          {storedResolvedFields.length > 0 && (
            <div className="space-y-1.5">
              <p className="text-sm font-medium">Resolved fields</p>
              <ResolvedFieldsTable fields={storedResolvedFields} />
            </div>
          )}

          {editingActiveRule && confirmActivate && (
            <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-3 text-sm space-y-2">
              <p className="font-semibold">Confirm save to active rule</p>
              <p className="text-muted-foreground text-xs">
                This updates the currently active rule used in evaluation.
              </p>
              <div className="flex gap-2">
                <Button size="sm" disabled={isSaving} onClick={() => void handleSave("active")}>
                  Confirm save
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={isSaving}
                  onClick={() => setConfirmActivate(false)}
                >
                  Cancel
                </Button>
              </div>
            </div>
          )}

          {saveError && (
            <div className="flex gap-2 text-sm text-destructive">
              <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
              {saveError}
            </div>
          )}

          <div className="flex flex-wrap gap-2 pt-1">
            <Button
              variant="outline"
              disabled={isSaving || !english.trim()}
              onClick={() => void handleSave("draft")}
            >
              {isSaving ? "Saving…" : "Save as draft"}
            </Button>
            <Button
              className="bg-primary text-primary-foreground"
              disabled={isSaving || !english.trim()}
              onClick={() => void handleSave("active")}
            >
              {isSaving ? "Saving…" : editingActiveRule ? "Save & activate" : "Activate rule"}
            </Button>
            <Button variant="ghost" disabled={isSaving} onClick={onBack}>
              Discard
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function RuleAuthoringChat({
  projectId,
  mode,
  initialEnglish,
  existingRule,
  fields,
  scopeNote,
  onBack,
  onApprove,
}: {
  projectId: string;
  mode: "add" | "edit";
  initialEnglish: string;
  existingRule: Record<string, unknown> | null;
  fields: { name: string; label: string }[];
  scopeNote?: string;
  onBack: () => void;
  onApprove: (
    rule: Record<string, unknown>,
    lifecycle: RuleLifecycleStatus,
    sourceProjectId?: string,
  ) => void | Promise<void>;
}) {
  const compileRule = useCompileDqaRule();
  const validateRule = useValidateDqaRule();
  const testRuleMutation = useTestDqaRule();

  const [composer, setComposer] = useState(
    mode === "edit" && initialEnglish ? initialEnglish : "",
  );
  const [conversation, setConversation] = useState<ConversationTurn[]>([]);
  const [transcript, setTranscript] = useState<ConversationTurn[]>(
    mode === "edit" && initialEnglish
      ? [
          {
            role: "assistant",
            content:
              "Current rule is loaded. Edit the text below and send to recompile, or ask for a change (for example: “make this red” or “compare A10 to D4 instead”).",
          },
        ]
      : [],
  );
  const [phase, setPhase] = useState<ChatPhase>("idle");
  const [progressLines, setProgressLines] = useState<string[]>([]);
  const [draftTokens, setDraftTokens] = useState("");
  const [compileStatus, setCompileStatus] = useState<CompileStatus>("idle");
  const [compiledRule, setCompiledRule] = useState<Record<string, unknown> | null>(
    mode === "edit" && existingRule ? { ...existingRule } : null,
  );
  const [preview, setPreview] = useState<DqaPreviewResult | null>(null);
  const [testResult, setTestResult] = useState<DqaTestRuleOut | null>(null);
  const [ruleDiff, setRuleDiff] = useState<RuleDiff | null>(null);
  const [qualityWarnings, setQualityWarnings] = useState<DqaRuleWarning[]>([]);
  const [validation, setValidation] = useState<DqaValidationResult | null>(null);
  const [compileError, setCompileError] = useState<string | null>(null);
  const [jsonDraft, setJsonDraft] = useState("");
  const [confirmActivate, setConfirmActivate] = useState(false);
  const [resolvedFields, setResolvedFields] = useState<ResolvedField[]>([]);
  const [sourceProjectId, setSourceProjectId] = useState<string | undefined>(undefined);
  const [aiExplanation, setAiExplanation] = useState("");
  const [proposalConfirmed, setProposalConfirmed] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const editingActiveRule =
    mode === "edit" && existingRule !== null && ruleLifecycleStatus(existingRule) === "active";

  useEffect(() => () => abortRef.current?.abort(), []);

  useEffect(() => {
    if (compiledRule) {
      setJsonDraft(JSON.stringify(compiledRule, null, 2));
    }
  }, [compiledRule]);

  const busy = compileStatus === "loading" || phase === "thinking" || phase === "streaming";
  const readyToApprove =
    compileStatus === "success" && compiledRule !== null && proposalConfirmed;

  const handleCompileResponse = useCallback((data: CompileResponse, userText: string) => {
    const normalized = normalizeCompileResponse(data);
    if (normalized.status === "needs_clarification") {
      const question = normalized.question || "Could you clarify this rule?";
      setCompileStatus("needs_clarification");
      setCompiledRule(null);
      setPreview(null);
      setTestResult(null);
      setRuleDiff(null);
      setQualityWarnings([]);
      setResolvedFields([]);
      setAiExplanation("");
      setProposalConfirmed(false);
      setValidation(normalized.validation ?? null);
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
      return;
    }

    if (normalized.status === "success" && normalized.rule) {
      setCompileStatus("success");
      setCompiledRule(normalized.rule as Record<string, unknown>);
      setPreview(normalized.preview ?? null);
      setTestResult(normalized.test ?? null);
      setRuleDiff(normalized.diff ?? null);
      setQualityWarnings(normalized.warnings ?? normalized.preview?.warnings ?? []);
      setValidation(normalized.validation ?? null);
      setConfirmActivate(false);
      setResolvedFields(normalized.resolvedFields ?? []);
      setSourceProjectId(normalized.sourceProjectId || projectId);
      setAiExplanation(cleanAiExplanation(String(normalized.explanation || "")));
      setProposalConfirmed(false);
      const explanation =
        normalized.explanation || "I found matching fields in your study forms.";
      const confirmPrompt = explanation.trim().toLowerCase().includes("is that correct")
        ? explanation
        : `${explanation.trim()}\n\nIs that correct?`;
      setConversation((prev) => [
        ...prev,
        { role: "user", content: userText },
        { role: "assistant", content: confirmPrompt },
      ]);
      setTranscript((prev) => [
        ...prev,
        { role: "user", content: userText },
        { role: "assistant", content: confirmPrompt },
      ]);
      return;
    }

    const message =
      normalized.message ||
      normalized.validation?.errors?.map((e) => e.message).join("; ") ||
      "Compilation failed";
    setCompileStatus("invalid");
    setCompiledRule(null);
    setPreview(null);
    setTestResult(null);
    setRuleDiff(null);
    setQualityWarnings([]);
    setResolvedFields([]);
    setAiExplanation("");
    setProposalConfirmed(false);
    setValidation(normalized.validation ?? null);
    setCompileError(message);
    setConversation((prev) => [...prev, { role: "user", content: userText }]);
    setTranscript((prev) => [
      ...prev,
      { role: "user", content: userText },
      { role: "assistant", content: message },
    ]);
  }, [projectId]);

  const runCompile = useCallback(
    async (userText: string) => {
      setCompileError(null);
      setCompileStatus("loading");
      setPhase("thinking");
      setProgressLines(["Starting compile…"]);
      setDraftTokens("");
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      const payload: DqaCompileInput = {
        english: userText,
        conversation,
        existingRule: existingRule ?? undefined,
        previewLimit: 50,
      };

      try {
        const data = await streamCompileDqaRule(projectId, payload, {
          signal: controller.signal,
          onProgress: (message, phaseName) => {
            if (message) {
              setProgressLines((prev) =>
                prev[prev.length - 1] === message ? prev : [...prev, message].slice(-8),
              );
            }
            if (phaseName === "compile" || phaseName === "repair" || phaseName === "llm") {
              setPhase("streaming");
            }
          },
          onToken: (text) => {
            setPhase("streaming");
            setDraftTokens((prev) => prev + text);
          },
        });
        setPhase("done");
        setDraftTokens("");
        handleCompileResponse(data, userText);
      } catch (err) {
        if (controller.signal.aborted) {
          setPhase("done");
          setCompileStatus("idle");
          setProgressLines([]);
          setDraftTokens("");
          return;
        }
        // Fallback to non-stream endpoint if stream route is unavailable
        const message = err instanceof Error ? err.message : "Compile request failed";
        const canFallback =
          /404|Failed to fetch|NetworkError|stream/i.test(message) || message.includes("HTTP 404");
        if (canFallback) {
          try {
            setProgressLines((prev) => [...prev, "Stream unavailable — retrying without stream…"]);
            const data = (await compileRule.mutateAsync({
              projectId,
              data: payload,
            })) as CompileResponse;
            setPhase("done");
            handleCompileResponse(data, userText);
            return;
          } catch (fallbackErr) {
            const fbMessage =
              fallbackErr instanceof Error ? fallbackErr.message : "Compile request failed";
            setPhase("done");
            setCompileStatus("invalid");
            setCompileError(fbMessage);
            setTranscript((prev) => [
              ...prev,
              { role: "user", content: userText },
              { role: "assistant", content: fbMessage },
            ]);
            return;
          }
        }
        setPhase("done");
        setCompileStatus("invalid");
        setCompileError(message);
        setTranscript((prev) => [
          ...prev,
          { role: "user", content: userText },
          { role: "assistant", content: message },
        ]);
      }
    },
    [compileRule, conversation, existingRule, handleCompileResponse, projectId],
  );

  function handleSend() {
    const text = composer.trim();
    if (!text || busy) return;
    // Confirm proposal via chat ("yes" / "correct") without recompiling
    if (
      compileStatus === "success" &&
      compiledRule &&
      !proposalConfirmed &&
      /^(y|yes|yeah|yep|correct|ok|okay|confirm|looks good)\b/i.test(text)
    ) {
      setComposer("");
      setProposalConfirmed(true);
      setTranscript((prev) => [
        ...prev,
        { role: "user", content: text },
        {
          role: "assistant",
          content:
            "Confirmed. Review the preview below, then save as draft or activate the rule.",
        },
      ]);
      setConversation((prev) => [
        ...prev,
        { role: "user", content: text },
        { role: "assistant", content: "User confirmed the proposed field mapping." },
      ]);
      return;
    }
    setComposer("");
    void runCompile(text);
  }

  function handleConfirmProposal() {
    if (!compiledRule || proposalConfirmed) return;
    setProposalConfirmed(true);
    setTranscript((prev) => [
      ...prev,
      { role: "user", content: "Yes, that’s correct" },
      {
        role: "assistant",
        content:
          "Confirmed. Review the preview below, then save as draft or activate the rule.",
      },
    ]);
    setConversation((prev) => [
      ...prev,
      { role: "user", content: "Yes, that’s correct" },
      { role: "assistant", content: "User confirmed the proposed field mapping." },
    ]);
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

  async function handleSave(lifecycle: RuleLifecycleStatus) {
    if (!compiledRule || isSaving) return;
    if (lifecycle === "active" && editingActiveRule && !confirmActivate) {
      setConfirmActivate(true);
      return;
    }
    setSaveError(null);
    setIsSaving(true);
    try {
      const summary =
        aiExplanation ||
        cleanAiExplanation(String(compiledRule.description || compiledRule.message || ""));
      const toSave: Record<string, unknown> = {
        ...compiledRule,
        description: summary || String(compiledRule.description || compiledRule.message || ""),
        resolvedFields,
      };
      await onApprove(applyLifecycle(toSave, lifecycle), lifecycle, sourceProjectId || projectId);
    } catch (err) {
      const message =
        err instanceof Error
          ? err.message
          : typeof err === "object" &&
              err !== null &&
              "message" in err &&
              typeof (err as { message: unknown }).message === "string"
            ? (err as { message: string }).message
            : "Save failed";
      setSaveError(message);
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Button
          size="sm"
          className="gap-1 bg-primary text-primary-foreground"
          onClick={onBack}
        >
          <ArrowLeft className="h-4 w-4" />
          Back
        </Button>
        {scopeNote && (
          <p className="text-xs text-muted-foreground">{scopeNote}</p>
        )}
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
              <ThinkingBlock lines={progressLines.length ? progressLines : THINKING_LINES} visibleCount={Math.max(progressLines.length, 1)} />
              {draftTokens && (
                <div className="rounded-lg border bg-muted/30 p-3">
                  <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground mb-1">
                    Model draft (streaming)
                  </p>
                  <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] text-muted-foreground">
                    {draftTokens}
                    <span className="opacity-50">▌</span>
                  </pre>
                </div>
              )}
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  abortRef.current?.abort();
                  setCompileStatus("idle");
                  setPhase("done");
                  setProgressLines([]);
                  setDraftTokens("");
                }}
              >
                Cancel
              </Button>
            </div>
          )}

          {compileStatus === "success" && !busy && (
            <div className="rounded-lg border p-3 text-sm space-y-3">
              <p className="font-semibold">Resolved fields</p>
              {resolvedFields.length > 0 ? (
                <ResolvedFieldsTable fields={resolvedFields} />
              ) : (
                <p className="text-xs text-muted-foreground">
                  No field references were extracted from the compiled check.
                </p>
              )}
              {!proposalConfirmed && (
                <div className="flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    className="bg-primary text-primary-foreground"
                    onClick={handleConfirmProposal}
                  >
                    Yes, that’s correct
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      setComposer("No — please adjust the fields: ");
                    }}
                  >
                    No, adjust fields
                  </Button>
                </div>
              )}
            </div>
          )}

          {proposalConfirmed && compileStatus === "success" && (testResult || preview) && (
            <RuleTestWorkspace test={testResult ?? previewToTest(preview)} />
          )}

          {proposalConfirmed && <WarningsList warnings={qualityWarnings} />}

          {proposalConfirmed && ruleDiff && <RuleDiffPanel diff={ruleDiff} />}

          {proposalConfirmed && editingActiveRule && confirmActivate && (
            <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-3 text-sm space-y-2">
              <p className="font-semibold">Confirm activation</p>
              <p className="text-muted-foreground text-xs">
                This replaces the currently active rule. Review the diff above before activating.
              </p>
              <div className="flex gap-2">
                <Button size="sm" disabled={isSaving} onClick={() => void handleSave("active")}>
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

          {proposalConfirmed && (compiledRule || jsonDraft) && (
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
              <Button
                variant="outline"
                disabled={isSaving}
                onClick={() => void handleSave("draft")}
              >
                {isSaving ? "Saving…" : "Save as draft"}
              </Button>
              <Button
                disabled={isSaving}
                onClick={() => void handleSave("active")}
                className="bg-primary text-primary-foreground"
              >
                {isSaving
                  ? "Saving…"
                  : mode === "add"
                    ? "Activate rule"
                    : "Save & activate"}
              </Button>
              <Button variant="ghost" disabled={isSaving} onClick={onBack}>
                Discard
              </Button>
            </div>
          )}

          {saveError && (
            <div className="flex gap-2 text-sm text-destructive">
              <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
              {saveError}
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
                  : compileStatus === "success" && !proposalConfirmed
                    ? "Yes to confirm, or describe corrections…"
                    : "Describe the rule in English. It can cover one form or several related forms…"
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

export function DqaChecksPanel({
  projectId,
  initialView = "table",
  initialEditRuleId = null,
}: {
  projectId: string;
  initialView?: View;
  initialEditRuleId?: string | null;
}) {
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

  const [view, setView] = useState<View>(initialView);
  const [helpOpen, setHelpOpen] = useState(false);
  const [editRuleId, setEditRuleId] = useState<string | null>(initialEditRuleId);
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

  useEffect(() => {
    if (initialView === "edit" && initialEditRuleId) {
      setEditRuleId(initialEditRuleId);
      setView("edit");
      setAuthoringSession((n) => n + 1);
    } else if (initialView === "edit-ai" && initialEditRuleId) {
      setEditRuleId(initialEditRuleId);
      setView("edit-ai");
      setAuthoringSession((n) => n + 1);
    } else if (initialView === "add") {
      setEditRuleId(null);
      setView("add");
      setAuthoringSession((n) => n + 1);
    }
  }, [projectId, initialView, initialEditRuleId]);

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
          r.group.toLowerCase().includes(q) ||
          r.resolvedFields.some(
            (f) =>
              f.code.toLowerCase().includes(q) ||
              f.label.toLowerCase().includes(q) ||
              f.form.toLowerCase().includes(q),
          ),
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
      const message = formatApiError(err, "Save failed");
      setSaveError(message);
      throw new Error(message);
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
    } else if (editRule && (view === "edit" || view === "edit-ai")) {
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

  if (view === "edit" && editRule?.raw) {
    return (
      <div key={`edit-${authoringSession}`}>
        <RuleDetailsEditor
          rule={editRule.raw}
          onBack={() => {
            setView("table");
            setEditRuleId(null);
          }}
          onRewriteWithAi={() => {
            setAuthoringSession((n) => n + 1);
            setView("edit-ai");
          }}
          onSave={(rule, lifecycle) => approveRule(rule, lifecycle)}
        />
      </div>
    );
  }

  if (view === "add" || view === "edit-ai") {
    return (
      <div key={`${view}-${authoringSession}`}>
        <RuleAuthoringChat
          projectId={projectId}
          mode={view === "add" ? "add" : "edit"}
          initialEnglish={editRule?.english ?? ""}
          existingRule={editRule?.raw ?? null}
          fields={fields}
          scopeNote="This form, plus related study forms when the rule spans more than one."
          onBack={() => {
            if (view === "edit-ai" && editRuleId) {
              setView("edit");
            } else {
              setView("table");
              setEditRuleId(null);
            }
          }}
          onApprove={(rule, lifecycle) => approveRule(rule, lifecycle)}
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
              Write rules in plain English. A rule can stay on this form or span related
              study forms. The compiler validates against the study schemas, previews on
              recent submissions, and saves deterministic JSON checks.
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
                <th className="p-3 w-56 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredRules.length === 0 ? (
                <tr>
                  <td colSpan={4} className="p-6 text-center text-muted-foreground">
                    {displayRules.length === 0
                      ? "No rules yet. Add one in English or sync form data to load seeded rules."
                      : "No rules match your filters."}
                  </td>
                </tr>
              ) : (
                <RuleTableRows
                  rules={filteredRules}
                  colSpan={4}
                  renderActions={(rule) => (
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
                  )}
                />
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

type StudyFormRef = {
  id: string;
  name: string;
  toolCode?: string | null;
};

type StudyRuleRow = DisplayRule & {
  projectId: string;
  formLabel: string;
};

function formLabelFor(project: StudyFormRef): string {
  return project.toolCode ? `${project.toolCode} · ${project.name}` : project.name;
}

export function DqaStudyRulesPanel({
  projects,
  onOpenForm,
}: {
  projects: StudyFormRef[];
  onOpenForm: (projectId: string, opts?: { editRuleId?: string; add?: boolean }) => void;
}) {
  const queryClient = useQueryClient();
  const updatePack = useUpdateProjectRulePack();
  const recompute = useRecomputeDqa();
  const lifecycleMutation = useSetDqaRuleLifecycle();

  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [formFilter, setFormFilter] = useState<string>("all");
  const [view, setView] = useState<"table" | "add">("table");
  const [authoringSession, setAuthoringSession] = useState(0);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const compileHostId = projects[0]?.id ?? "";

  const packQueries = useQueries({
    queries: projects.map((project) => ({
      queryKey: getGetProjectRulePackQueryKey(project.id),
      queryFn: () => getProjectRulePack(project.id),
      enabled: Boolean(project.id),
    })),
  });

  const allRows = useMemo(() => {
    const rows: StudyRuleRow[] = [];
    projects.forEach((project, index) => {
      const pack = packQueries[index]?.data?.pack;
      const rawRules = Array.isArray(pack?.rules) ? (pack.rules as Record<string, unknown>[]) : [];
      for (const rule of packRulesToDisplay(rawRules)) {
        rows.push({
          ...rule,
          projectId: project.id,
          formLabel: formLabelFor(project),
        });
      }
    });
    return rows;
  }, [packQueries, projects]);

  const filteredRows = useMemo(() => {
    let items = allRows;
    if (formFilter !== "all") {
      items = items.filter((r) => r.projectId === formFilter);
    }
    if (statusFilter !== "all") {
      items = items.filter((r) => r.status === statusFilter);
    }
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      items = items.filter(
        (r) =>
          r.english.toLowerCase().includes(q) ||
          r.id.toLowerCase().includes(q) ||
          r.description.toLowerCase().includes(q) ||
          r.group.toLowerCase().includes(q) ||
          r.formLabel.toLowerCase().includes(q) ||
          r.resolvedFields.some(
            (f) =>
              f.code.toLowerCase().includes(q) ||
              f.label.toLowerCase().includes(q) ||
              f.form.toLowerCase().includes(q),
          ),
      );
    }
    return items;
  }, [allRows, formFilter, searchQuery, statusFilter]);

  const loading = packQueries.some((q) => q.isLoading);
  const loadError = packQueries.find((q) => q.error)?.error;
  const errorMessage =
    actionError ||
    (loadError instanceof Error ? loadError.message : loadError ? String(loadError) : null);

  const refreshProject = async (projectId: string) => {
    await queryClient.invalidateQueries({ queryKey: getGetProjectRulePackQueryKey(projectId) });
    queryClient.invalidateQueries({ queryKey: getGetDqaSummaryQueryKey() });
    queryClient.invalidateQueries({ queryKey: getGetDqaFlagsQueryKey() });
  };

  const setRuleLifecycle = async (
    projectId: string,
    ruleId: string,
    status: RuleLifecycleStatus,
  ) => {
    const key = `${projectId}:${ruleId}:lifecycle`;
    setActionError(null);
    setBusyKey(key);
    try {
      await lifecycleMutation.mutateAsync({
        projectId,
        ruleId,
        data: { status, enabled: status === "active" },
      });
      if (status === "active") {
        await recompute.mutateAsync({ params: { projectId } });
      }
      await refreshProject(projectId);
    } catch (err) {
      setActionError(formatApiError(err, "Lifecycle update failed"));
    } finally {
      setBusyKey(null);
    }
  };

  const deleteRule = async (projectId: string, ruleId: string) => {
    const key = `${projectId}:${ruleId}:delete`;
    setActionError(null);
    setBusyKey(key);
    try {
      const packOut = await getProjectRulePack(projectId);
      const existing = packOut.pack || {};
      const rawRules = Array.isArray(existing.rules) ? [...(existing.rules as unknown[])] : [];
      const nextRules = rawRules.filter(
        (r) => !(r && typeof r === "object" && String((r as { id?: unknown }).id) === ruleId),
      );
      const pack = {
        ...existing,
        id: existing.id || projectId,
        project_uids: existing.project_uids || [projectId],
        rules: nextRules,
      };
      await updatePack.mutateAsync({ projectId, data: { pack } });
      await recompute.mutateAsync({ params: { projectId } });
      await refreshProject(projectId);
    } catch (err) {
      setActionError(formatApiError(err, "Delete failed"));
    } finally {
      setBusyKey(null);
    }
  };

  const approveStudyRule = async (
    compiled: Record<string, unknown>,
    lifecycle: RuleLifecycleStatus,
    sourceProjectId?: string,
  ) => {
    const projectId =
      (sourceProjectId && projects.some((p) => p.id === sourceProjectId)
        ? sourceProjectId
        : compileHostId) || "";
    if (!projectId) {
      throw new Error("No form in this study to store the rule");
    }
    const packOut = await getProjectRulePack(projectId);
    const existing = packOut.pack || {};
    const rawRules = Array.isArray(existing.rules) ? [...(existing.rules as unknown[])] : [];
    const withLifecycle = applyLifecycle(compiled, lifecycle);
    const id = String(withLifecycle.id || `R-${Date.now()}`);
    const pack = {
      ...existing,
      id: existing.id || projectId,
      project_uids: existing.project_uids || [projectId],
      rules: [...rawRules, { ...withLifecycle, id }],
    };
    await updatePack.mutateAsync({ projectId, data: { pack } });
    if (lifecycle === "active") {
      await recompute.mutateAsync({ params: { projectId } });
    }
    await refreshProject(projectId);
    setView("table");
  };

  if (view === "add" && compileHostId) {
    return (
      <div key={`study-add-${authoringSession}`}>
        <RuleAuthoringChat
          projectId={compileHostId}
          mode="add"
          initialEnglish=""
          existingRule={null}
          fields={[]}
          scopeNote="Uses every form in this study. A rule can stay on one form or span related forms."
          onBack={() => setView("table")}
          onApprove={approveStudyRule}
        />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-sm font-semibold">DQA checks</p>
        <span className="text-sm text-muted-foreground">· All study forms</span>
        <div className="flex-1" />
        <Button
          size="sm"
          className="bg-primary text-primary-foreground"
          disabled={!compileHostId}
          onClick={() => {
            setAuthoringSession((n) => n + 1);
            setView("add");
          }}
        >
          Add rule in English
        </Button>
      </div>

      <p className="text-xs text-muted-foreground">
        Showing rules across every form in this study. Add a rule in English — it can cover one
        form or several related forms. Edit a row to open that form&apos;s authoring view.
      </p>

      {errorMessage && (
        <div className="flex gap-2 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
          <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
          {errorMessage}
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
          <Select value={formFilter} onValueChange={setFormFilter}>
            <SelectTrigger className="w-[200px]">
              <SelectValue placeholder="Form" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All forms</SelectItem>
              {projects.map((project) => (
                <SelectItem key={project.id} value={project.id}>
                  {formLabelFor(project)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
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
                <th className="p-3 w-48">Form</th>
                <th className="p-3">Rule</th>
                <th className="p-3 w-28">Status</th>
                <th className="p-3 w-56 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={5} className="p-6 text-center text-muted-foreground">
                    Loading rules…
                  </td>
                </tr>
              ) : filteredRows.length === 0 ? (
                <tr>
                  <td colSpan={5} className="p-6 text-center text-muted-foreground">
                    {allRows.length === 0
                      ? "No rules yet across study forms. Add a rule in English to get started."
                      : "No rules match your filters."}
                  </td>
                </tr>
              ) : (
                <RuleTableRows
                  rules={filteredRows}
                  colSpan={5}
                  renderFormCell={(rule) => (
                    <button
                      type="button"
                      className="text-left text-primary hover:underline"
                      onClick={() => onOpenForm(String(rule.projectId || ""))}
                    >
                      {rule.formLabel}
                    </button>
                  )}
                  renderActions={(rule) => {
                    const projectId = String(rule.projectId || "");
                    const rowBusy =
                      busyKey === `${projectId}:${rule.id}:lifecycle` ||
                      busyKey === `${projectId}:${rule.id}:delete`;
                    return (
                      <div className="flex justify-end gap-1 flex-wrap">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => onOpenForm(projectId, { editRuleId: rule.id })}
                        >
                          Edit
                        </Button>
                        {rule.status !== "active" && (
                          <Button
                            variant="ghost"
                            size="sm"
                            disabled={rowBusy}
                            onClick={() => void setRuleLifecycle(projectId, rule.id, "active")}
                          >
                            Activate
                          </Button>
                        )}
                        {rule.status === "active" && (
                          <Button
                            variant="ghost"
                            size="sm"
                            disabled={rowBusy}
                            onClick={() => void setRuleLifecycle(projectId, rule.id, "draft")}
                          >
                            Disable
                          </Button>
                        )}
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={rowBusy}
                          onClick={() => void deleteRule(projectId, rule.id)}
                        >
                          Delete
                        </Button>
                      </div>
                    );
                  }}
                />
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
