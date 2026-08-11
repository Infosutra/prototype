import React, { useMemo, useState } from "react";
import {
  getGetPromptsQueryKey,
  useCreatePrompt,
  useDeletePrompt,
  useGetPrompts,
  useUpdatePrompt,
  type PromptInput,
  type PromptOut,
} from "@workspace/api-client-react";
import { useQueryClient } from "@tanstack/react-query";
import { Layout } from "@/components/layout/Layout";
import { Header } from "@/components/layout/Header";
import { Card, CardContent, CardHeader, CardTitle, CardFooter } from "@/components/ui/card";
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
import { Edit2, Trash2, Plus, MessageSquare } from "lucide-react";

function emptyForm(): PromptInput {
  return {
    name: "",
    description: "",
    content: "",
    category: "general",
    projectIds: [],
  };
}

export default function PromptTemplates() {
  const queryClient = useQueryClient();
  const promptsQuery = useGetPrompts();
  const prompts = promptsQuery.data ?? [];

  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<PromptOut | null>(null);
  const [form, setForm] = useState<PromptInput>(emptyForm());
  const [error, setError] = useState<string | null>(null);

  const createPrompt = useCreatePrompt();
  const updatePrompt = useUpdatePrompt();
  const deletePrompt = useDeletePrompt();

  const isSaving = createPrompt.isPending || updatePrompt.isPending;

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

  const remove = async (prompt: PromptOut) => {
    if (!confirm(`Delete prompt “${prompt.name}”?`)) return;
    try {
      await deletePrompt.mutateAsync({ promptId: prompt.id });
      await queryClient.invalidateQueries({ queryKey: getGetPromptsQueryKey() });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    }
  };

  return (
    <Layout>
      <Header
        title="Prompt Templates"
        description="Manage instructions used by AI to generate reports and insights"
        action={
          <Button size="sm" className="bg-primary text-primary-foreground" onClick={openCreate}>
            <Plus className="w-4 h-4 mr-2" />
            New Prompt
          </Button>
        }
      />
      <div className="flex-1 overflow-auto p-4 md:p-6 bg-muted/30">
        {promptsQuery.error && (
          <div className="mb-4 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
            {promptsQuery.error.message}
          </div>
        )}
        {promptsQuery.isLoading ? (
          <p className="text-sm text-muted-foreground">Loading prompts…</p>
        ) : prompts.length === 0 ? (
          <Card>
            <CardContent className="p-8 text-center text-sm text-muted-foreground">
              No prompts yet. Create one to guide AI report generation.
            </CardContent>
          </Card>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-6">
            {prompts.map((prompt) => (
              <Card key={prompt.id} className="flex flex-col">
                <CardHeader className="pb-3 border-b">
                  <div className="flex justify-between items-start mb-2">
                    <Badge
                      variant="outline"
                      className="uppercase text-[10px] tracking-wider bg-card text-muted-foreground"
                    >
                      {prompt.category}
                    </Badge>
                    <span className="text-xs font-mono text-muted-foreground">
                      Updated: {new Date(prompt.updatedAt).toLocaleDateString()}
                    </span>
                  </div>
                  <CardTitle className="text-lg flex items-center">
                    <MessageSquare className="w-4 h-4 mr-2 text-primary" />
                    {prompt.name}
                  </CardTitle>
                  <p className="text-sm text-muted-foreground mt-1 line-clamp-2">
                    {prompt.description || "—"}
                  </p>
                </CardHeader>
                <CardContent className="p-4 flex-1 bg-muted/10">
                  <div className="text-xs font-mono text-foreground/80 whitespace-pre-wrap bg-card border rounded p-3 h-32 overflow-y-auto">
                    {prompt.content}
                  </div>
                </CardContent>
                <CardFooter className="p-3 border-t bg-card flex justify-end gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-muted-foreground hover:text-foreground"
                    onClick={() => openEdit(prompt)}
                  >
                    <Edit2 className="w-4 h-4 mr-2" />
                    Edit
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-destructive hover:bg-destructive/10 hover:text-destructive"
                    disabled={deletePrompt.isPending}
                    onClick={() => void remove(prompt)}
                  >
                    <Trash2 className="w-4 h-4" />
                  </Button>
                </CardFooter>
              </Card>
            ))}
          </div>
        )}
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <div className="space-y-1.5">
              <Label>Name</Label>
              <Input
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="Executive monthly summary"
              />
            </div>
            <div className="space-y-1.5">
              <Label>Category</Label>
              <Input
                value={form.category ?? "general"}
                onChange={(e) => setForm((f) => ({ ...f, category: e.target.value }))}
                placeholder="executive"
              />
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
                className="min-h-[140px] font-mono text-sm"
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
            <Button disabled={isSaving} onClick={() => void save()}>
              {isSaving ? "Saving…" : "Save"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Layout>
  );
}
