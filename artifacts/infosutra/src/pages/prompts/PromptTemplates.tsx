import React, { useMemo, useState } from "react";
import {
  getGetPromptsQueryKey,
  useCreatePrompt,
  useDeletePrompt,
  useGetPrompts,
  useGetStudies,
  useRevertPrompt,
  useUpdatePrompt,
  type PromptInput,
  type PromptOut,
} from "@workspace/api-client-react";
import { useQueryClient } from "@tanstack/react-query";
import { Layout } from "@/components/layout/Layout";
import { Header } from "@/components/layout/Header";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Copy, Edit2, Trash2, Plus, RotateCcw } from "lucide-react";

const CATEGORIES = [
  { value: "daily-dqa", label: "Daily DQA" },
  { value: "final-dqa", label: "Final DQA" },
  { value: "dqa-compile", label: "DQA compile" },
  { value: "report-planner", label: "Report Planner" },
  { value: "report-analyst", label: "Report Analyst" },
  { value: "general", label: "General" },
] as const;

function categoryLabel(value: string): string {
  return CATEGORIES.find((c) => c.value === value)?.label ?? value;
}

function emptyForm(): PromptInput {
  return {
    name: "",
    description: "",
    content: "",
    category: "daily-dqa",
    projectIds: [],
  };
}

function assignmentLabel(
  prompt: PromptOut,
  studyNameById: Map<string, string>,
): string {
  const usedBy = (prompt.studyIds ?? [])
    .map((id) => studyNameById.get(id) || id)
    .filter(Boolean);
  if (usedBy.length > 0) return usedBy.join(", ");
  if (prompt.isSystem) return "Default when unassigned";
  return "Not assigned";
}

export default function PromptTemplates() {
  const queryClient = useQueryClient();
  const promptsQuery = useGetPrompts();
  const studiesQuery = useGetStudies();
  const prompts = promptsQuery.data ?? [];
  const studies = studiesQuery.data ?? [];
  const studyNameById = useMemo(
    () => new Map(studies.map((s) => [s.id, s.name])),
    [studies],
  );

  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<PromptOut | null>(null);
  const [form, setForm] = useState<PromptInput>(emptyForm());
  const [error, setError] = useState<string | null>(null);

  const createPrompt = useCreatePrompt();
  const updatePrompt = useUpdatePrompt();
  const deletePrompt = useDeletePrompt();
  const revertPrompt = useRevertPrompt();

  const isSaving = createPrompt.isPending || updatePrompt.isPending;
  const isReverting = revertPrompt.isPending;

  const title = useMemo(
    () => (editing ? "Edit prompt" : "New prompt"),
    [editing],
  );

  const openCreate = () => {
    setEditing(null);
    setForm(emptyForm());
    setError(null);
    setOpen(true);
  };

  const openEdit = (prompt: PromptOut) => {
    setEditing(prompt);
    setForm({
      name: prompt.name,
      description: prompt.description ?? "",
      content: prompt.content ?? "",
      category: prompt.category || "general",
      projectIds: prompt.projectIds ?? [],
    });
    setError(null);
    setOpen(true);
  };

  const save = async () => {
    setError(null);
    if (!form.name.trim() || !(form.content ?? "").trim()) {
      setError("Name and content are required");
      return;
    }
    try {
      if (editing) {
        await updatePrompt.mutateAsync({
          promptId: editing.id,
          data: {
            name: form.name,
            description: form.description,
            content: form.content,
            category: form.category,
            projectIds: form.projectIds,
          },
        });
      } else {
        await createPrompt.mutateAsync({ data: form });
      }
      await queryClient.invalidateQueries({ queryKey: getGetPromptsQueryKey() });
      setOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    }
  };

  const duplicate = async (prompt: PromptOut) => {
    setError(null);
    try {
      await createPrompt.mutateAsync({
        data: {
          name: `${prompt.name} (copy)`,
          description: prompt.description ?? "",
          content: prompt.content ?? "",
          category: prompt.category || "general",
          projectIds: [],
        },
      });
      await queryClient.invalidateQueries({ queryKey: getGetPromptsQueryKey() });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Duplicate failed");
    }
  };

  const remove = async (prompt: PromptOut) => {
    if (prompt.isSystem) {
      setError("Default system prompts cannot be deleted. Edit them or duplicate for a study.");
      return;
    }
    if (!confirm(`Delete prompt “${prompt.name}”?`)) return;
    try {
      await deletePrompt.mutateAsync({ promptId: prompt.id });
      await queryClient.invalidateQueries({ queryKey: getGetPromptsQueryKey() });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    }
  };

  const revert = async (prompt: PromptOut) => {
    if (!prompt.isSystem) return;
    if (
      !confirm(
        `Revert “${prompt.name}” to the original seeded version? Unsaved edits in this dialog will be discarded.`,
      )
    ) {
      return;
    }
    setError(null);
    try {
      const restored = await revertPrompt.mutateAsync({ promptId: prompt.id });
      await queryClient.invalidateQueries({ queryKey: getGetPromptsQueryKey() });
      setEditing(restored);
      setForm({
        name: restored.name,
        description: restored.description ?? "",
        content: restored.content ?? "",
        category: restored.category || "general",
        projectIds: restored.projectIds ?? [],
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Revert failed");
    }
  };

  return (
    <Layout>
      <Header
        title="Prompt Templates"
        description="Edit Daily / Final DQA narrative instructions and assign them on each study"
        action={
          <Button size="sm" className="bg-primary text-primary-foreground" onClick={openCreate}>
            <Plus className="w-4 h-4 mr-2" />
            New Prompt
          </Button>
        }
      />
      <div className="flex-1 overflow-auto p-4 md:p-6 bg-muted/30">
        {(error || promptsQuery.error) && (
          <div className="mb-4 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
            {error || promptsQuery.error?.message}
          </div>
        )}
        {promptsQuery.isLoading ? (
          <p className="text-sm text-muted-foreground">Loading prompts…</p>
        ) : (
          <Card>
            <div className="overflow-x-auto">
              <table className="w-full text-sm text-left">
                <thead className="bg-muted text-muted-foreground text-xs uppercase">
                  <tr>
                    <th className="px-4 py-3 font-medium">Name</th>
                    <th className="px-4 py-3 font-medium">Category</th>
                    <th className="px-4 py-3 font-medium">Description</th>
                    <th className="px-4 py-3 font-medium">Assigned</th>
                    <th className="px-4 py-3 font-medium">Updated</th>
                    <th className="px-4 py-3 font-medium text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border bg-card">
                  {prompts.map((prompt) => (
                    <tr key={prompt.id} className="hover:bg-muted/50 transition-colors">
                      <td className="px-4 py-3">
                        <div className="font-medium">{prompt.name}</div>
                        {prompt.isSystem ? (
                          <Badge variant="secondary" className="mt-1 text-[10px]">
                            Default
                          </Badge>
                        ) : null}
                      </td>
                      <td className="px-4 py-3">
                        <Badge
                          variant="outline"
                          className="uppercase text-[10px] tracking-wider"
                        >
                          {categoryLabel(prompt.category)}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 text-muted-foreground max-w-[280px]">
                        <span className="line-clamp-2">{prompt.description || "—"}</span>
                      </td>
                      <td className="px-4 py-3 text-muted-foreground max-w-[220px]">
                        <span className="line-clamp-2">
                          {assignmentLabel(prompt, studyNameById)}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-xs text-muted-foreground whitespace-nowrap">
                        {new Date(prompt.updatedAt).toLocaleDateString()}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex justify-end gap-1">
                          <Button
                            variant="ghost"
                            size="sm"
                            className="text-muted-foreground hover:text-foreground"
                            disabled={createPrompt.isPending}
                            onClick={() => void duplicate(prompt)}
                          >
                            <Copy className="w-4 h-4 mr-1" />
                            Duplicate
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="text-muted-foreground hover:text-foreground"
                            onClick={() => openEdit(prompt)}
                          >
                            <Edit2 className="w-4 h-4 mr-1" />
                            Edit
                          </Button>
                          {prompt.isSystem ? (
                            <Button
                              variant="ghost"
                              size="sm"
                              className="text-muted-foreground hover:text-foreground"
                              disabled={isReverting}
                              onClick={() => void revert(prompt)}
                            >
                              <RotateCcw className="w-4 h-4 mr-1" />
                              Revert
                            </Button>
                          ) : (
                            <Button
                              variant="ghost"
                              size="sm"
                              className="text-destructive hover:bg-destructive/10 hover:text-destructive"
                              disabled={deletePrompt.isPending}
                              onClick={() => void remove(prompt)}
                            >
                              <Trash2 className="w-4 h-4" />
                            </Button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                  {prompts.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="px-4 py-8 text-center text-muted-foreground">
                        No prompts yet. Create one to guide AI report generation.
                      </td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          </Card>
        )}
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3 py-2">
            {editing?.isSystem ? (
              <p className="text-xs text-muted-foreground rounded-md border bg-muted/40 p-2">
                This is a seeded system prompt. You can edit it; use Revert to restore the original
                packaged version. It cannot be deleted.
              </p>
            ) : null}
            <div className="space-y-1.5">
              <Label>Name</Label>
              <Input
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="Daily DQA — health baseline"
              />
            </div>
            <div className="space-y-1.5">
              <Label>Category</Label>
              <select
                className="field-control h-9 w-full px-2 text-sm"
                value={form.category ?? "general"}
                disabled={Boolean(editing?.isSystem)}
                onChange={(e) => setForm((f) => ({ ...f, category: e.target.value }))}
              >
                {CATEGORIES.map((c) => (
                  <option key={c.value} value={c.value}>
                    {c.label}
                  </option>
                ))}
                {form.category &&
                !CATEGORIES.some((c) => c.value === form.category) ? (
                  <option value={form.category}>{form.category}</option>
                ) : null}
              </select>
            </div>
            <div className="space-y-1.5">
              <Label>Description</Label>
              <Input
                value={form.description ?? ""}
                onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
              />
            </div>
            <div className="space-y-1.5">
              <Label>Content</Label>
              <Textarea
                className="min-h-[220px] font-mono text-sm"
                value={form.content ?? ""}
                onChange={(e) => setForm((f) => ({ ...f, content: e.target.value }))}
              />
            </div>
            {error && <p className="text-sm text-destructive">{error}</p>}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            {editing?.isSystem ? (
              <Button
                variant="outline"
                disabled={isReverting || isSaving}
                onClick={() => void revert(editing)}
              >
                <RotateCcw className="w-4 h-4 mr-2" />
                {isReverting ? "Reverting…" : "Revert to original"}
              </Button>
            ) : null}
            <Button disabled={isSaving || isReverting} onClick={() => void save()}>
              {isSaving ? "Saving…" : "Save"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Layout>
  );
}
