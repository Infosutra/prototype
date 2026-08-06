import React, { useMemo } from "react";
import { Link, useRoute } from "wouter";
import {
  useGetDqaFlags,
  useGetProjectFormFields,
  useGetSubmission,
  type DqaFlagOut,
  type FormFieldOut,
} from "@workspace/api-client-react";
import { Layout } from "@/components/layout/Layout";
import { Header } from "@/components/layout/Header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ArrowLeft, AlertCircle } from "lucide-react";

function leafName(key: string): string {
  return key.split("/").filter(Boolean).pop() || key;
}

function fallbackFieldLabel(key: string): string {
  return key
    .split("/")
    .filter(Boolean)
    .map((part) =>
      part
        .replace(/^_+/, "")
        .replace(/[_-]+/g, " ")
        .replace(/\b\w/g, (letter) => letter.toUpperCase()),
    )
    .join(" / ");
}

function buildFieldCatalog(fields: FormFieldOut[]) {
  const byName = new Map<string, FormFieldOut>();
  for (const field of fields) {
    byName.set(field.name, field);
    // Also index by leaf if name is a path
    byName.set(leafName(field.name), field);
  }
  return byName;
}

function resolveQuestionLabel(key: string, catalog: Map<string, FormFieldOut>, existingLabel?: string): string {
  const leaf = leafName(key);
  const fromCatalog = catalog.get(key)?.label || catalog.get(leaf)?.label;
  if (fromCatalog) return fromCatalog;
  if (existingLabel && existingLabel.trim() && existingLabel !== leaf && !existingLabel.endsWith("(flagged field)")) {
    return existingLabel;
  }
  return fallbackFieldLabel(key);
}

function lookupDataValue(data: Record<string, unknown> | undefined, target: string): unknown {
  if (!data) return null;
  if (target in data) return data[target];
  const leaf = leafName(target);
  if (leaf in data) return data[leaf];
  const suffix = `/${leaf}`;
  for (const [key, value] of Object.entries(data)) {
    if (key === leaf || key.endsWith(suffix)) return value;
  }
  return null;
}

function decodeChoiceValue(
  value: unknown,
  fieldMeta: FormFieldOut | undefined,
): unknown {
  if (!fieldMeta?.choices?.length || value == null || value === "") return value;
  const choiceMap = new Map(
    fieldMeta.choices.map((c) => [
      String(c.name ?? ""),
      String(c.label ?? c.name ?? ""),
    ]),
  );
  if (Array.isArray(value)) {
    return value.map((item) => choiceMap.get(String(item)) || item);
  }
  const text = String(value);
  // select_multiple may be space-separated
  if (text.includes(" ") && fieldMeta.type.startsWith("select_multiple")) {
    return text
      .split(/\s+/)
      .filter(Boolean)
      .map((part) => choiceMap.get(part) || part)
      .join(", ");
  }
  return choiceMap.get(text) || value;
}

function FieldValue({ value }: { value: unknown }) {
  if (value == null || value === "") {
    return <span className="text-muted-foreground">Not provided</span>;
  }
  if (typeof value === "boolean") return <span>{value ? "Yes" : "No"}</span>;
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="text-muted-foreground">None</span>;
    if (value.every((item) => ["string", "number", "boolean"].includes(typeof item))) {
      return <span>{value.join(", ")}</span>;
    }
  }
  if (typeof value === "object") {
    return (
      <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-md bg-muted p-3 text-xs">
        {JSON.stringify(value, null, 2)}
      </pre>
    );
  }
  return <span className="break-words">{String(value)}</span>;
}

function highlightTargets(flag: DqaFlagOut): string[] {
  const details = flag.details;
  if (!details || typeof details !== "object") return [];
  const raw = details.highlightFields;
  if (!Array.isArray(raw)) return [];
  return raw.map((item) => String(item)).filter(Boolean);
}

function relatedSubmissions(flag: DqaFlagOut): Array<{
  submissionId?: string;
  koboId?: string | null;
  enumerator?: string | null;
  submittedAt?: string | null;
}> {
  const details = flag.details;
  if (!details || typeof details !== "object") return [];
  const raw = details.relatedSubmissions;
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
    .map((item) => ({
      submissionId: typeof item.submissionId === "string" ? item.submissionId : undefined,
      koboId: typeof item.koboId === "string" ? item.koboId : null,
      enumerator: typeof item.enumerator === "string" ? item.enumerator : null,
      submittedAt: typeof item.submittedAt === "string" ? item.submittedAt : null,
    }));
}

function formatShortDate(value?: string | null) {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function fieldMatches(fieldKey: string, target: string): boolean {
  if (!target) return false;
  if (fieldKey === target) return true;
  if (fieldKey.endsWith(`/${target}`)) return true;
  const leaf = leafName(fieldKey);
  const targetLeaf = leafName(target);
  return leaf === target || leaf === targetLeaf;
}

function severityRank(severity: string): number {
  return severity === "red" ? 2 : severity === "amber" ? 1 : 0;
}

function fieldRowClass(severity?: "red" | "amber"): string {
  if (severity === "red") {
    return "bg-red-50 border-l-4 border-l-red-500";
  }
  if (severity === "amber") {
    return "bg-amber-50 border-l-4 border-l-amber-500";
  }
  return "";
}

export default function SubmissionDetail() {
  const [, params] = useRoute("/submissions/:id");
  const submissionId = params?.id ? decodeURIComponent(params.id) : "";
  const submissionQuery = useGetSubmission(submissionId);
  const submission = submissionQuery.data;
  const flagsQuery = useGetDqaFlags(
    { submissionId },
    { query: { enabled: Boolean(submissionId) } as never },
  );
  const formFieldsQuery = useGetProjectFormFields(submission?.projectId ?? "", {
    query: { enabled: Boolean(submission?.projectId) } as never,
  });

  const fieldCatalog = useMemo(
    () => buildFieldCatalog(formFieldsQuery.data ?? []),
    [formFieldsQuery.data],
  );

  const fieldSeverity = useMemo(() => {
    const map = new Map<string, "red" | "amber">();
    for (const flag of flagsQuery.data ?? []) {
      const severity = flag.severity === "red" ? "red" : "amber";
      for (const target of highlightTargets(flag)) {
        const prev = map.get(target);
        if (!prev || severityRank(severity) > severityRank(prev)) {
          map.set(target, severity);
        }
      }
    }
    return map;
  }, [flagsQuery.data]);

  const locationSeverity = useMemo(() => {
    let best: "red" | "amber" | undefined;
    for (const [target, severity] of fieldSeverity) {
      if (target === "__location__" || target === "_geolocation" || target === "location") {
        if (!best || severityRank(severity) > severityRank(best)) best = severity;
      }
    }
    return best;
  }, [fieldSeverity]);

  const displayFields = useMemo(() => {
    if (!submission) return [];
    const data = (submission.data ?? {}) as Record<string, unknown>;

    const base =
      (submission.responses?.length ?? 0) > 0
        ? (submission.responses ?? []).map((field) => ({
            key: field.key,
            code: leafName(field.key),
            label: resolveQuestionLabel(field.key, fieldCatalog, field.label),
            value: decodeChoiceValue(
              field.value,
              fieldCatalog.get(field.key) || fieldCatalog.get(leafName(field.key)),
            ),
          }))
        : Object.entries(data)
            .filter(([key]) => !key.split("/").at(-1)?.startsWith("_"))
            .map(([key, value]) => ({
              key,
              code: leafName(key),
              label: resolveQuestionLabel(key, fieldCatalog),
              value: decodeChoiceValue(
                value,
                fieldCatalog.get(key) || fieldCatalog.get(leafName(key)),
              ),
            }));

    const severityFor = (fieldKey: string): "red" | "amber" | undefined => {
      let best: "red" | "amber" | undefined;
      for (const [target, severity] of fieldSeverity) {
        if (!fieldMatches(fieldKey, target)) continue;
        if (!best || severityRank(severity) > severityRank(best)) best = severity;
      }
      return best;
    };

    const rows = base.map((field) => ({
      ...field,
      severity: severityFor(field.key),
    }));

    const matchedTargets = new Set<string>();
    for (const field of rows) {
      for (const [target] of fieldSeverity) {
        if (fieldMatches(field.key, target)) matchedTargets.add(target);
      }
    }

    const extras = [...fieldSeverity.entries()]
      .filter(([target]) => {
        if (target.startsWith("_") || target.startsWith("__")) return false;
        return !matchedTargets.has(target);
      })
      .map(([target, severity]) => {
        const code = leafName(target);
        const meta = fieldCatalog.get(target) || fieldCatalog.get(code);
        const rawValue = lookupDataValue(data, target);
        return {
          key: target,
          code,
          label: resolveQuestionLabel(target, fieldCatalog),
          value: decodeChoiceValue(rawValue, meta),
          severity,
        };
      });

    return [...extras, ...rows];
  }, [submission, fieldSeverity, fieldCatalog]);

  if (submissionQuery.isLoading) {
    return (
      <Layout>
        <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
          Loading submission…
        </div>
      </Layout>
    );
  }

  if (!submission || submissionQuery.error) {
    return (
      <Layout>
        <div className="flex flex-1 items-center justify-center p-6">
          <Card className="max-w-lg p-6 text-center">
            <AlertCircle className="mx-auto mb-3 h-6 w-6 text-destructive" />
            <h2 className="font-semibold">Submission unavailable</h2>
            <p className="mt-2 text-sm text-muted-foreground">
              {submissionQuery.error?.message ?? "The requested submission was not found."}
            </p>
          </Card>
        </div>
      </Layout>
    );
  }

  const scrollToField = (flag: DqaFlagOut) => {
    const targets = highlightTargets(flag);
    const match = displayFields.find((field) => targets.some((t) => fieldMatches(field.key, t)));
    if (match) {
      document.getElementById(`field-${encodeURIComponent(match.key)}`)?.scrollIntoView({
        behavior: "smooth",
        block: "center",
      });
      return;
    }
    if (targets.some((t) => t === "__location__" || t === "_geolocation")) {
      document.getElementById("meta-location")?.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  };

  return (
    <Layout>
      <Header
        title={submission.displayId}
        description={submission.projectName}
        action={
          <Link href={`/forms/${submission.projectId}/submissions`}>
            <Button variant="outline" size="sm">
              <ArrowLeft className="mr-2 h-4 w-4" />
              All submissions
            </Button>
          </Link>
        }
      />
      <div className="flex-1 overflow-auto bg-muted/30 p-4 md:p-6">
        <div className="mx-auto max-w-5xl space-y-6">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {[
              ["Submitted", new Date(submission.submittedAt).toLocaleString()],
              ["Enumerator", submission.enumerator],
              ["Location", submission.location ?? "Not available"],
              ["Status", submission.status],
            ].map(([label, value]) => {
              const isLocation = label === "Location";
              return (
                <Card
                  key={label}
                  id={isLocation ? "meta-location" : undefined}
                  className={isLocation ? fieldRowClass(locationSeverity) : undefined}
                >
                  <CardContent className="p-4">
                    <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                      {label}
                    </p>
                    <p className={`mt-2 font-semibold ${label === "Status" ? "capitalize" : ""}`}>
                      {value}
                    </p>
                    {isLocation && locationSeverity && (
                      <p
                        className={`mt-1 text-xs font-medium ${
                          locationSeverity === "red" ? "text-red-700" : "text-amber-700"
                        }`}
                      >
                        DQA {locationSeverity.toUpperCase()}: GPS / location
                      </p>
                    )}
                  </CardContent>
                </Card>
              );
            })}
          </div>

          {(flagsQuery.data?.length ?? 0) > 0 && (
            <Card>
              <CardHeader className="border-b">
                <CardTitle className="text-base">DQA flags</CardTitle>
              </CardHeader>
              <CardContent className="divide-y p-0">
                {flagsQuery.data?.map((flag) => {
                  const related = relatedSubmissions(flag).filter(
                    (item) => item.submissionId && item.submissionId !== submission.id,
                  );
                  const sharedValue =
                    flag.details && typeof flag.details === "object" && "value" in flag.details
                      ? String(flag.details.value ?? "")
                      : "";
                  const targets = highlightTargets(flag).filter(
                    (t) => !t.startsWith("_") && !t.startsWith("__"),
                  );
                  return (
                    <div key={flag.id} className="px-5 py-4 text-sm space-y-2">
                      <button
                        type="button"
                        onClick={() => scrollToField(flag)}
                        className="flex w-full flex-wrap items-start gap-3 text-left hover:opacity-90"
                      >
                        <Badge variant={flag.severity === "red" ? "destructive" : "secondary"}>
                          {flag.severity.toUpperCase()}
                        </Badge>
                        <div>
                          <p className="font-medium">
                            <span className="font-mono text-xs text-muted-foreground mr-2">
                              {flag.ruleId}
                            </span>
                            {flag.title}
                          </p>
                          <p className="text-muted-foreground">{flag.message}</p>
                          {targets.length > 0 && (
                            <div className="mt-1 space-y-0.5">
                              {targets.map((target) => {
                                const code = leafName(target);
                                const label = resolveQuestionLabel(target, fieldCatalog);
                                return (
                                  <p key={target} className="text-xs text-muted-foreground">
                                    Field{" "}
                                    <span className="font-mono text-foreground">{code}</span>
                                    {label && label !== code ? ` — ${label}` : ""}
                                  </p>
                                );
                              })}
                            </div>
                          )}
                          {sharedValue && related.length > 0 && (
                            <p className="mt-1 text-xs text-muted-foreground">
                              Shared value: <span className="font-mono">{sharedValue}</span>
                            </p>
                          )}
                          {targets.length > 0 && (
                            <p className="mt-1 text-xs text-primary">Jump to field →</p>
                          )}
                        </div>
                      </button>
                      {related.length > 0 && (
                        <div className="ml-14 rounded-md border bg-muted/30 p-3 space-y-2">
                          <p className="text-xs font-medium text-muted-foreground">
                            Also appears in {related.length} other submission
                            {related.length === 1 ? "" : "s"}
                          </p>
                          <ul className="space-y-1">
                            {related.map((item) => (
                              <li key={item.submissionId} className="text-xs flex flex-wrap gap-x-3 gap-y-1">
                                <Link
                                  className="text-primary underline font-mono"
                                  href={`/submissions/${item.submissionId}`}
                                >
                                  {item.koboId || item.submissionId}
                                </Link>
                                {item.enumerator && <span>{item.enumerator}</span>}
                                {item.submittedAt && (
                                  <span className="text-muted-foreground">
                                    {formatShortDate(item.submittedAt)}
                                  </span>
                                )}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  );
                })}
              </CardContent>
            </Card>
          )}

          <Card>
            <CardHeader className="border-b">
              <CardTitle className="text-base">Form responses</CardTitle>
            </CardHeader>
            <CardContent className="divide-y p-0">
              {displayFields.map((field) => (
                <div
                  key={field.key}
                  id={`field-${encodeURIComponent(field.key)}`}
                  className={`grid gap-2 px-5 py-4 md:grid-cols-[minmax(0,360px)_1fr] ${fieldRowClass(field.severity)}`}
                >
                  <div>
                    <p className="font-mono text-xs text-muted-foreground">{field.code}</p>
                    <p className="text-sm font-medium">{field.label}</p>
                    {field.severity && (
                      <p
                        className={`mt-1 text-xs font-medium ${
                          field.severity === "red" ? "text-red-700" : "text-amber-700"
                        }`}
                      >
                        {field.severity.toUpperCase()} flag
                      </p>
                    )}
                  </div>
                  <div className="text-sm">
                    <FieldValue value={field.value} />
                  </div>
                </div>
              ))}
              {displayFields.length === 0 && (
                <p className="p-8 text-center text-sm text-muted-foreground">
                  This submission contains no displayable responses.
                </p>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </Layout>
  );
}
