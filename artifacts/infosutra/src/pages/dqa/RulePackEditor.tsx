import React, { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "wouter";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useGetProject } from "@workspace/api-client-react";
import { Layout } from "@/components/layout/Layout";
import { Header } from "@/components/layout/Header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { AlertCircle, Plus, Save, Trash2 } from "lucide-react";
import { dqaApi, type FormField } from "@/lib/dqa-api";

const STANDARD_ALIASES = [
  "consent",
  "enumerator_id",
  "respondent_id",
  "district",
  "block",
  "udise",
  "institution_name",
  "institution_type",
  "start",
  "end",
];

const OPERATORS = [
  "required",
  "blank",
  "equals",
  "equals_any",
  "not_in",
  "regex",
  "between",
  "duration_minutes_gte",
  "exclusive_choice",
  "unique_in_project",
  "group_count_lte",
  "all_equal",
  "gps_present",
];

type EditableRule = {
  id: string;
  title: string;
  severity: "red" | "amber";
  message: string;
  op: string;
  field: string;
  values: string;
  pattern: string;
  min: string;
  max: string;
  exclusiveValues: string;
  threshold: string;
};

function emptyRule(): EditableRule {
  return {
    id: "",
    title: "",
    severity: "amber",
    message: "",
    op: "required",
    field: "",
    values: "",
    pattern: "",
    min: "",
    max: "",
    exclusiveValues: "",
    threshold: "",
  };
}

function ruleToEditable(rule: Record<string, unknown>): EditableRule {
  const check = (rule.check as Record<string, unknown>) || {};
  const values = Array.isArray(check.values) ? check.values.join(",") : "";
  const exclusive = Array.isArray(check.exclusive_values)
    ? check.exclusive_values.join(",")
    : "";
  return {
    id: String(rule.id || ""),
    title: String(rule.title || ""),
    severity: (String(rule.severity || "amber").toLowerCase() === "red" ? "red" : "amber"),
    message: String(rule.message || ""),
    op: String(check.op || "required"),
    field: String(check.field || ""),
    values,
    pattern: String(check.pattern || ""),
    min: check.min != null ? String(check.min) : "",
    max: check.max != null ? String(check.max) : "",
    exclusiveValues: exclusive,
    threshold: String(check.threshold || ""),
  };
}

function editableToRule(rule: EditableRule): Record<string, unknown> {
  const check: Record<string, unknown> = { op: rule.op };
  if (rule.field) check.field = rule.field;
  if (rule.values.trim()) {
    check.values = rule.values.split(",").map((v) => v.trim()).filter(Boolean);
  }
  if (rule.pattern) check.pattern = rule.pattern;
  if (rule.min !== "") check.min = Number(rule.min);
  if (rule.max !== "") check.max = Number(rule.max);
  if (rule.exclusiveValues.trim()) {
    check.exclusive_values = rule.exclusiveValues.split(",").map((v) => v.trim()).filter(Boolean);
  }
  if (rule.threshold) check.threshold = rule.threshold;
  if (rule.op === "duration_minutes_gte") {
    check.start_field = "start";
    check.end_field = "end";
  }
  return {
    id: rule.id || `R-${Date.now()}`,
    title: rule.title || rule.id,
    severity: rule.severity,
    message: rule.message || rule.title,
    check,
  };
}

export default function RulePackEditor() {
  const params = useParams<{ id: string }>();
  const projectId = params.id;
  const queryClient = useQueryClient();
  const projectQuery = useGetProject(projectId);
  const fieldsQuery = useQuery({
    queryKey: ["form-fields", projectId],
    queryFn: () => dqaApi.formFields(projectId),
    enabled: Boolean(projectId),
  });
  const packQuery = useQuery({
    queryKey: ["rule-pack", projectId],
    queryFn: () => dqaApi.getRulePack(projectId),
    enabled: Boolean(projectId),
  });

  const [fieldsMap, setFieldsMap] = useState<Record<string, string>>({});
  const [thresholds, setThresholds] = useState<Record<string, number>>({});
  const [thresholdKey, setThresholdKey] = useState("");
  const [thresholdValue, setThresholdValue] = useState("");
  const [rules, setRules] = useState<EditableRule[]>([]);
  const [fieldSearch, setFieldSearch] = useState("");
  const [joinKey, setJoinKey] = useState("udise");
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (!packQuery.data?.pack) return;
    const pack = packQuery.data.pack;
    setFieldsMap({ ...(pack.fields || {}) });
    setThresholds({ ...(pack.thresholds || {}) });
    setJoinKey(String(pack.join_key || "udise"));
    setRules((pack.rules || []).map((r) => ruleToEditable(r as Record<string, unknown>)));
  }, [packQuery.data]);

  const filteredFields = useMemo(() => {
    const q = fieldSearch.toLowerCase();
    return (fieldsQuery.data ?? []).filter(
      (f) =>
        !q ||
        f.name.toLowerCase().includes(q) ||
        f.label.toLowerCase().includes(q),
    );
  }, [fieldsQuery.data, fieldSearch]);

  const saveMutation = useMutation({
    mutationFn: async () => {
      const existing = packQuery.data?.pack || {};
      const pack = {
        ...existing,
        id: existing.id || projectQuery.data?.uid || projectId,
        project_uids: existing.project_uids || [projectQuery.data?.uid || projectId],
        join_key: joinKey,
        fields: fieldsMap,
        thresholds,
        rules: rules.filter((r) => r.id || r.title).map(editableToRule),
      };
      await dqaApi.putRulePack(projectId, pack);
      return dqaApi.recompute(projectId);
    },
    onSuccess: (result) => {
      setMessage(`Saved. Recomputed ${result.flags} flags across ${result.submissions} submissions.`);
      queryClient.invalidateQueries({ queryKey: ["rule-pack", projectId] });
      queryClient.invalidateQueries({ queryKey: ["dqa-summary"] });
      queryClient.invalidateQueries({ queryKey: ["dqa-flags"] });
    },
  });

  const aliasKeys = useMemo(() => {
    const keys = new Set([...STANDARD_ALIASES, ...Object.keys(fieldsMap)]);
    return Array.from(keys);
  }, [fieldsMap]);

  const error =
    projectQuery.error?.message ||
    fieldsQuery.error?.message ||
    packQuery.error?.message ||
    saveMutation.error?.message;

  function FieldSelect({
    value,
    onChange,
  }: {
    value: string;
    onChange: (v: string) => void;
  }) {
    return (
      <select
        className="h-9 w-full rounded-md border bg-background px-2 text-sm"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">— select field —</option>
        {(fieldsQuery.data ?? []).map((f: FormField) => (
          <option key={f.name} value={f.name}>
            {f.name} — {f.label.slice(0, 60)}
          </option>
        ))}
      </select>
    );
  }

  return (
    <Layout>
      <Header
        title="Rule pack editor"
        description={projectQuery.data?.name || "Configure DQA aliases, thresholds, and constraints"}
        action={
          <div className="flex gap-2">
            <Button variant="outline" asChild>
              <Link href="/dqa">Back to DQA</Link>
            </Button>
            <Button
              onClick={() => saveMutation.mutate()}
              disabled={saveMutation.isPending}
              className="bg-primary text-primary-foreground"
            >
              <Save className="w-4 h-4 mr-2" />
              Save & recompute
            </Button>
          </div>
        }
      />

      <div className="flex-1 overflow-auto p-4 md:p-6 bg-muted/30 space-y-6">
        {error && (
          <div className="flex gap-2 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
            <AlertCircle className="h-4 w-4 mt-0.5" />
            {error}
          </div>
        )}
        {message && (
          <div className="rounded-md border border-green-200 bg-green-50 p-3 text-sm text-green-800">
            {message}
          </div>
        )}

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
          <Card>
            <CardHeader className="py-4 border-b">
              <CardTitle className="text-sm">Kobo field browser</CardTitle>
            </CardHeader>
            <CardContent className="p-4 space-y-3">
              <Input
                placeholder="Search fields…"
                value={fieldSearch}
                onChange={(e) => setFieldSearch(e.target.value)}
              />
              <div className="max-h-96 overflow-auto divide-y border rounded-md">
                {filteredFields.map((f) => (
                  <div key={f.name} className="p-3 text-sm">
                    <div className="font-mono text-xs text-muted-foreground">{f.type}</div>
                    <div className="font-medium">{f.name}</div>
                    <div className="text-muted-foreground text-xs">{f.label}</div>
                    {f.choices?.length > 0 && (
                      <div className="mt-1 text-[11px] font-mono text-muted-foreground">
                        {f.choices.slice(0, 8).map((c) => `${c.name}=${c.label}`).join(" · ")}
                        {f.choices.length > 8 ? "…" : ""}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="py-4 border-b">
              <CardTitle className="text-sm">Aliases / mappings</CardTitle>
            </CardHeader>
            <CardContent className="p-4 space-y-3">
              <div className="flex items-center gap-2 text-sm">
                <span className="w-28 text-muted-foreground">join_key</span>
                <Input value={joinKey} onChange={(e) => setJoinKey(e.target.value)} className="h-9" />
              </div>
              {aliasKeys.map((alias) => (
                <div key={alias} className="flex items-center gap-2 text-sm">
                  <span className="w-28 font-mono text-xs truncate">{alias}</span>
                  <FieldSelect
                    value={fieldsMap[alias] || ""}
                    onChange={(v) => setFieldsMap((prev) => ({ ...prev, [alias]: v }))}
                  />
                </div>
              ))}
              <div className="flex gap-2">
                <Input
                  placeholder="custom alias"
                  id="custom-alias"
                  className="h-9"
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      const value = (e.target as HTMLInputElement).value.trim();
                      if (value) setFieldsMap((prev) => ({ ...prev, [value]: prev[value] || "" }));
                      (e.target as HTMLInputElement).value = "";
                    }
                  }}
                />
                <span className="text-xs text-muted-foreground self-center">Press Enter to add</span>
              </div>
            </CardContent>
          </Card>
        </div>

        <Card>
          <CardHeader className="py-4 border-b">
            <CardTitle className="text-sm">Thresholds</CardTitle>
          </CardHeader>
          <CardContent className="p-4 space-y-3">
            <div className="flex flex-wrap gap-2">
              {Object.entries(thresholds).map(([key, value]) => (
                <div key={key} className="flex items-center gap-2 rounded border px-2 py-1 text-sm">
                  <span className="font-mono text-xs">{key}</span>
                  <Input
                    className="h-8 w-24"
                    type="number"
                    value={value}
                    onChange={(e) =>
                      setThresholds((prev) => ({ ...prev, [key]: Number(e.target.value) }))
                    }
                  />
                  <button
                    type="button"
                    onClick={() =>
                      setThresholds((prev) => {
                        const next = { ...prev };
                        delete next[key];
                        return next;
                      })
                    }
                  >
                    <Trash2 className="w-3.5 h-3.5 text-muted-foreground" />
                  </button>
                </div>
              ))}
            </div>
            <div className="flex gap-2 max-w-lg">
              <Input
                placeholder="name e.g. min_duration_minutes"
                value={thresholdKey}
                onChange={(e) => setThresholdKey(e.target.value)}
              />
              <Input
                placeholder="value"
                type="number"
                value={thresholdValue}
                onChange={(e) => setThresholdValue(e.target.value)}
              />
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  if (!thresholdKey.trim()) return;
                  setThresholds((prev) => ({
                    ...prev,
                    [thresholdKey.trim()]: Number(thresholdValue || 0),
                  }));
                  setThresholdKey("");
                  setThresholdValue("");
                }}
              >
                Add
              </Button>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="py-4 border-b flex flex-row items-center justify-between">
            <CardTitle className="text-sm">Constraints / rules</CardTitle>
            <Button type="button" variant="outline" size="sm" onClick={() => setRules((r) => [...r, emptyRule()])}>
              <Plus className="w-4 h-4 mr-1" /> Add rule
            </Button>
          </CardHeader>
          <CardContent className="p-4 space-y-4">
            {rules.length === 0 && (
              <p className="text-sm text-muted-foreground">No rules yet. Add one or save seeded pack edits.</p>
            )}
            {rules.map((rule, index) => (
              <div key={index} className="rounded-md border p-3 space-y-2 bg-card">
                <div className="grid grid-cols-1 md:grid-cols-4 gap-2">
                  <Input
                    placeholder="Rule id"
                    value={rule.id}
                    onChange={(e) =>
                      setRules((prev) => prev.map((r, i) => (i === index ? { ...r, id: e.target.value } : r)))
                    }
                  />
                  <Input
                    placeholder="Title"
                    value={rule.title}
                    onChange={(e) =>
                      setRules((prev) => prev.map((r, i) => (i === index ? { ...r, title: e.target.value } : r)))
                    }
                  />
                  <select
                    className="h-9 rounded-md border bg-background px-2 text-sm"
                    value={rule.severity}
                    onChange={(e) =>
                      setRules((prev) =>
                        prev.map((r, i) =>
                          i === index ? { ...r, severity: e.target.value as "red" | "amber" } : r,
                        ),
                      )
                    }
                  >
                    <option value="red">RED</option>
                    <option value="amber">AMBER</option>
                  </select>
                  <select
                    className="h-9 rounded-md border bg-background px-2 text-sm"
                    value={rule.op}
                    onChange={(e) =>
                      setRules((prev) => prev.map((r, i) => (i === index ? { ...r, op: e.target.value } : r)))
                    }
                  >
                    {OPERATORS.map((op) => (
                      <option key={op} value={op}>
                        {op}
                      </option>
                    ))}
                  </select>
                </div>
                <Input
                  placeholder="Message"
                  value={rule.message}
                  onChange={(e) =>
                    setRules((prev) => prev.map((r, i) => (i === index ? { ...r, message: e.target.value } : r)))
                  }
                />
                <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                  <FieldSelect
                    value={rule.field}
                    onChange={(v) =>
                      setRules((prev) => prev.map((r, i) => (i === index ? { ...r, field: v } : r)))
                    }
                  />
                  <Input
                    placeholder="values (comma-separated)"
                    value={rule.values}
                    onChange={(e) =>
                      setRules((prev) => prev.map((r, i) => (i === index ? { ...r, values: e.target.value } : r)))
                    }
                  />
                  <Input
                    placeholder="pattern / exclusive / threshold"
                    value={rule.pattern || rule.exclusiveValues || rule.threshold}
                    onChange={(e) => {
                      const v = e.target.value;
                      setRules((prev) =>
                        prev.map((r, i) => {
                          if (i !== index) return r;
                          if (r.op === "regex") return { ...r, pattern: v };
                          if (r.op === "exclusive_choice") return { ...r, exclusiveValues: v };
                          return { ...r, threshold: v };
                        }),
                      );
                    }}
                  />
                </div>
                <div className="flex justify-end">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => setRules((prev) => prev.filter((_, i) => i !== index))}
                  >
                    <Trash2 className="w-4 h-4 mr-1" /> Remove
                  </Button>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
    </Layout>
  );
}
