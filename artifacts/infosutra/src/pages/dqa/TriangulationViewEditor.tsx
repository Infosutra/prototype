import React, { useEffect, useState } from "react";
import { Link, useParams } from "wouter";
import { useQueryClient } from "@tanstack/react-query";
import {
  getListStudyTriangulationViewsQueryKey,
  useCreateStudyTriangulationView,
  useDeleteStudyTriangulationView,
  useGetStudy,
  useListStudyTriangulationViews,
  useUpdateStudyTriangulationView,
  type TriangulationViewDefinitionOut,
} from "@workspace/api-client-react";
import { Layout } from "@/components/layout/Layout";
import { Header } from "@/components/layout/Header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { AlertCircle, Plus, Save, Trash2 } from "lucide-react";

const EMPTY_DEFINITION = `{
  "kind": "cross_form_join",
  "participants": [],
  "mismatch": { "all": [] },
  "columns": [
    { "key": "join_key", "label": "Join key", "as": "text" }
  ]
}`;

export default function TriangulationViewEditor() {
  const params = useParams<{ studyId: string }>();
  const studyId = params.studyId;
  const queryClient = useQueryClient();
  const studyQuery = useGetStudy(studyId);
  const viewsQuery = useListStudyTriangulationViews(studyId, {
    query: { enabled: Boolean(studyId) } as never,
  });
  const createView = useCreateStudyTriangulationView();
  const updateView = useUpdateStudyTriangulationView();
  const deleteView = useDeleteStudyTriangulationView();

  const [selectedCode, setSelectedCode] = useState<string>("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [definitionText, setDefinitionText] = useState(EMPTY_DEFINITION);
  const [message, setMessage] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  const views = viewsQuery.data ?? [];

  useEffect(() => {
    if (!views.length) return;
    if (!selectedCode || !views.some((v) => v.code === selectedCode)) {
      loadView(views[0]);
    }
  }, [viewsQuery.data]);

  const loadView = (view: TriangulationViewDefinitionOut) => {
    setSelectedCode(view.code);
    setTitle(view.title || view.code);
    setDescription(view.description || "");
    setDefinitionText(JSON.stringify(view.definition ?? {}, null, 2));
    setMessage("");
    setError(null);
  };

  const invalidate = () => {
    queryClient.invalidateQueries({
      queryKey: getListStudyTriangulationViewsQueryKey(studyId),
    });
  };

  const save = async () => {
    setError(null);
    setIsSaving(true);
    try {
      let definition: Record<string, unknown>;
      try {
        definition = JSON.parse(definitionText) as Record<string, unknown>;
      } catch {
        throw new Error("Definition must be valid JSON");
      }
      if (!selectedCode) {
        throw new Error("Select or create a view first");
      }
      await updateView.mutateAsync({
        studyId,
        code: selectedCode,
        data: {
          title: title.trim() || selectedCode,
          description: description.trim() || null,
          definition,
        },
      });
      setMessage("Saved triangulation view definition.");
      invalidate();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setIsSaving(false);
    }
  };

  const createNew = async () => {
    setError(null);
    const code = window.prompt("New view code (e.g. TR-4)");
    if (!code?.trim()) return;
    try {
      let definition: Record<string, unknown>;
      try {
        definition = JSON.parse(EMPTY_DEFINITION) as Record<string, unknown>;
      } catch {
        definition = { kind: "cross_form_join", participants: [], columns: [] };
      }
      definition.code = code.trim();
      definition.title = code.trim();
      const created = await createView.mutateAsync({
        studyId,
        data: {
          code: code.trim(),
          title: code.trim(),
          description: null,
          definition,
        },
      });
      invalidate();
      loadView(created);
      setMessage(`Created ${created.code}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create failed");
    }
  };

  const remove = async () => {
    if (!selectedCode) return;
    if (!window.confirm(`Delete triangulation view ${selectedCode}?`)) return;
    try {
      await deleteView.mutateAsync({ studyId, code: selectedCode });
      setSelectedCode("");
      setTitle("");
      setDescription("");
      setDefinitionText(EMPTY_DEFINITION);
      setMessage(`Deleted ${selectedCode}.`);
      invalidate();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    }
  };

  return (
    <Layout>
      <Header
        title="Triangulation views"
        description={
          studyQuery.data
            ? `Edit study-defined triangulation for ${studyQuery.data.name}`
            : "Edit study-defined triangulation view definitions (JSON)"
        }
        action={
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" asChild>
              <Link href="/dqa">Back to DQA</Link>
            </Button>
            <Button variant="outline" size="sm" onClick={createNew}>
              <Plus className="h-4 w-4 mr-1" />
              New view
            </Button>
            <Button size="sm" onClick={save} disabled={isSaving || !selectedCode}>
              <Save className="h-4 w-4 mr-1" />
              {isSaving ? "Saving…" : "Save"}
            </Button>
          </div>
        }
      />

      <div className="space-y-4 p-4 md:p-6">
        {(error || message) && (
          <div
            className={`flex items-start gap-2 rounded-md border px-3 py-2 text-sm ${
              error ? "border-destructive/40 text-destructive" : "border-border text-muted-foreground"
            }`}
          >
            {error && <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />}
            <span>{error || message}</span>
          </div>
        )}

        <div className="grid gap-4 lg:grid-cols-[240px_1fr]">
          <Card>
            <CardHeader className="py-3 border-b">
              <CardTitle className="text-sm">Views</CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              {viewsQuery.isLoading ? (
                <p className="p-3 text-sm text-muted-foreground">Loading…</p>
              ) : views.length === 0 ? (
                <p className="p-3 text-sm text-muted-foreground">No views yet.</p>
              ) : (
                <ul className="divide-y">
                  {views.map((v) => (
                    <li key={v.id}>
                      <button
                        type="button"
                        className={`w-full text-left px-3 py-2 text-sm hover:bg-muted/50 ${
                          v.code === selectedCode ? "bg-muted font-medium" : ""
                        }`}
                        onClick={() => loadView(v)}
                      >
                        <div className="font-mono text-xs">{v.code}</div>
                        <div className="text-muted-foreground truncate">{v.title}</div>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="py-3 border-b flex flex-row items-center justify-between gap-2">
              <CardTitle className="text-sm">
                {selectedCode ? `Definition · ${selectedCode}` : "Select a view"}
              </CardTitle>
              {selectedCode && (
                <Button variant="outline" size="sm" onClick={remove}>
                  <Trash2 className="h-4 w-4 mr-1" />
                  Delete
                </Button>
              )}
            </CardHeader>
            <CardContent className="space-y-3 pt-4">
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="space-y-1 text-sm">
                  <span className="text-muted-foreground">Title</span>
                  <Input value={title} onChange={(e) => setTitle(e.target.value)} disabled={!selectedCode} />
                </label>
                <label className="space-y-1 text-sm sm:col-span-2">
                  <span className="text-muted-foreground">Description</span>
                  <Input
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    disabled={!selectedCode}
                  />
                </label>
              </div>
              <label className="block space-y-1 text-sm">
                <span className="text-muted-foreground">Definition (JSON)</span>
                <textarea
                  className="field-control w-full min-h-[420px] p-3 font-mono text-xs leading-relaxed"
                  value={definitionText}
                  onChange={(e) => setDefinitionText(e.target.value)}
                  disabled={!selectedCode}
                  spellCheck={false}
                />
              </label>
              <p className="text-xs text-muted-foreground">
                Supported kinds: <code>cross_form_join</code>, <code>claim_vs_observation</code>.
                Primitives: reducers <code>bool_any</code>/<code>text</code>/<code>bool</code>/
                <code>int_or_zero</code>; picks <code>latest</code>, <code>prefer</code>; predicates{" "}
                <code>is_true</code>, <code>is_false</code>, <code>all</code>, <code>not</code>,{" "}
                <code>gt</code>.
              </p>
            </CardContent>
          </Card>
        </div>
      </div>
    </Layout>
  );
}
