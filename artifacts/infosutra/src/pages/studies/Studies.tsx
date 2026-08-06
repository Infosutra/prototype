import React, { useEffect, useMemo, useState } from "react";
import { Link } from "wouter";
import { useQueryClient } from "@tanstack/react-query";
import {
  getGetProjectsQueryKey,
  getGetStudiesQueryKey,
  useAssignStudyProject,
  useCreateStudy,
  useDeleteStudy,
  useGetProjects,
  useGetStudies,
  useUnassignStudyProject,
  useUpdateStudy,
  useGetStudyKobo,
  useUpdateStudyKobo,
  useTestStudyKoboConnection,
  type StudyCreate,
  type StudyOut,
  type StudyToolIn,
} from "@workspace/api-client-react";
import { Layout } from "@/components/layout/Layout";
import { Header } from "@/components/layout/Header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { AlertCircle, CheckCircle2, Plus, Save, Trash2, X } from "lucide-react";
import { useStudy } from "@/components/study/StudyProvider";

function emptyForm(): StudyCreate {
  return {
    name: "",
    description: "",
    startDate: "",
    endDate: "",
    timezone: "Asia/Kolkata",
    tools: [],
  };
}

function toolsFromStudy(study: StudyOut): StudyToolIn[] {
  return (study.tools ?? []).map((t, index) => ({
    id: t.id,
    code: t.code,
    label: t.label ?? "",
    targetCount: t.targetCount ?? 0,
    sortOrder: t.sortOrder ?? index,
  }));
}

type PanelMode = "idle" | "create" | "edit";

export default function StudiesPage() {
  const queryClient = useQueryClient();
  const { activeStudyId, setActiveStudyId, refetch } = useStudy();
  const studiesQuery = useGetStudies();
  const projectsQuery = useGetProjects();
  const studies = studiesQuery.data ?? [];
  const projects = projectsQuery.data ?? [];

  const [panelMode, setPanelMode] = useState<PanelMode>("idle");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<StudyCreate>(emptyForm());
  const [toolCode, setToolCode] = useState("T1");
  const [toolLabel, setToolLabel] = useState("");
  const [toolTarget, setToolTarget] = useState("");
  const [assignProjectId, setAssignProjectId] = useState("");
  const [assignTool, setAssignTool] = useState("T1");
  const [koboServerUrl, setKoboServerUrl] = useState("https://kf.kobotoolbox.org");
  const [koboApiToken, setKoboApiToken] = useState("");
  const [koboUsername, setKoboUsername] = useState("");
  const [koboFeedback, setKoboFeedback] = useState<{ success: boolean; message: string } | null>(null);
  const [message, setMessage] = useState("");
  const [didAutoSelect, setDidAutoSelect] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const createStudy = useCreateStudy();
  const updateStudy = useUpdateStudy();
  const deleteStudy = useDeleteStudy();
  const assignStudyProject = useAssignStudyProject();
  const unassignStudyProject = useUnassignStudyProject();
  const studyKoboQuery = useGetStudyKobo(editingId ?? "", {
    query: { enabled: Boolean(editingId) } as never,
  });
  const updateStudyKobo = useUpdateStudyKobo({
    mutation: {
      onSuccess: (cred) => {
        setKoboApiToken(cred.apiToken ?? "");
        setKoboFeedback({ success: true, message: "Kobo settings saved and connection verified." });
        queryClient.invalidateQueries({ queryKey: getGetStudiesQueryKey() });
      },
      onError: (err) =>
        setKoboFeedback({
          success: false,
          message: err instanceof Error ? err.message : "Save failed",
        }),
    },
  });
  const testStudyKobo = useTestStudyKoboConnection({
    mutation: {
      onSuccess: (result) =>
        setKoboFeedback({
          success: result.success,
          message: result.details ?? result.message,
        }),
      onError: (err) =>
        setKoboFeedback({
          success: false,
          message: err instanceof Error ? err.message : "Test failed",
        }),
    },
  });

  const editing = useMemo(
    () => studies.find((s) => s.id === editingId) ?? null,
    [studies, editingId],
  );

  const startCreate = () => {
    setPanelMode("create");
    setEditingId(null);
    setForm(emptyForm());
    setMessage("");
    setActionError(null);
  };

  const clearPanel = () => {
    setPanelMode("idle");
    setEditingId(null);
    setForm(emptyForm());
  };

  const startEdit = (study: StudyOut) => {
    setPanelMode("edit");
    setEditingId(study.id);
    setForm({
      name: study.name,
      description: study.description ?? "",
      startDate: study.startDate ?? "",
      endDate: study.endDate ?? "",
      timezone: study.timezone || "Asia/Kolkata",
      tools: toolsFromStudy(study),
    });
    setMessage("");
    setActionError(null);
    setKoboFeedback(null);
  };

  const cancelCreate = () => {
    const preferred =
      studies.find((s) => s.id === activeStudyId) ?? studies[0] ?? null;
    if (preferred) startEdit(preferred);
    else clearPanel();
  };

  // Open the active (or first) study once the list loads — never default to Create.
  useEffect(() => {
    if (didAutoSelect || studiesQuery.isLoading || panelMode !== "idle") return;
    if (studies.length === 0) {
      setDidAutoSelect(true);
      return;
    }
    const preferred =
      studies.find((s) => s.id === activeStudyId) ?? studies[0];
    if (preferred) startEdit(preferred);
    setDidAutoSelect(true);
  }, [studies, studiesQuery.isLoading, activeStudyId, didAutoSelect, panelMode]);

  const invalidateStudyQueries = () => {
    queryClient.invalidateQueries({ queryKey: getGetStudiesQueryKey() });
    queryClient.invalidateQueries({ queryKey: getGetProjectsQueryKey() });
    refetch();
  };

  const applyStudyToForm = (study: StudyOut) => {
    setMessage(`Saved study “${study.name}”. Assign synced forms below.`);
    setPanelMode("edit");
    setEditingId(study.id);
    setActiveStudyId(study.id);
    setForm({
      name: study.name,
      description: study.description ?? "",
      startDate: study.startDate ?? "",
      endDate: study.endDate ?? "",
      timezone: study.timezone || "Asia/Kolkata",
      tools: toolsFromStudy(study),
    });
    invalidateStudyQueries();
  };

  const saveStudy = async () => {
    setActionError(null);
    const payload: StudyCreate = {
      ...form,
      startDate: form.startDate || null,
      endDate: form.endDate || null,
    };
    try {
      if (panelMode === "edit" && editingId) {
        const study = await updateStudy.mutateAsync({ studyId: editingId, data: payload });
        applyStudyToForm(study);
      } else {
        const study = await createStudy.mutateAsync({ data: payload });
        applyStudyToForm(study);
      }
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Save failed");
    }
  };

  const removeStudy = async (id: string) => {
    setActionError(null);
    try {
      await deleteStudy.mutateAsync({ studyId: id });
      setMessage("Study deleted.");
      clearPanel();
      setDidAutoSelect(false);
      if (activeStudyId === id) setActiveStudyId(null);
      invalidateStudyQueries();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Delete failed");
    }
  };

  const assignProject = async () => {
    setActionError(null);
    if (!editingId || !assignProjectId) {
      setActionError("Select a project");
      return;
    }
    try {
      await assignStudyProject.mutateAsync({
        studyId: editingId,
        data: { projectId: assignProjectId, toolCode: assignTool || undefined },
      });
      setMessage("Form assigned to study.");
      setAssignProjectId("");
      queryClient.invalidateQueries({ queryKey: getGetStudiesQueryKey() });
      queryClient.invalidateQueries({ queryKey: getGetProjectsQueryKey() });
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Assign failed");
    }
  };

  const unassignProject = async (projectId: string) => {
    setActionError(null);
    if (!editingId) {
      setActionError("No study selected");
      return;
    }
    try {
      await unassignStudyProject.mutateAsync({ studyId: editingId, projectId });
      queryClient.invalidateQueries({ queryKey: getGetStudiesQueryKey() });
      queryClient.invalidateQueries({ queryKey: getGetProjectsQueryKey() });
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Unassign failed");
    }
  };

  useEffect(() => {
    const cred = studyKoboQuery.data ?? editing?.credential;
    if (!cred) return;
    setKoboServerUrl(cred.serverUrl || "https://kf.kobotoolbox.org");
    setKoboApiToken(cred.apiToken || "");
    setKoboUsername(cred.username || "");
  }, [studyKoboQuery.data, editing?.credential, editingId]);

  const unassignedProjects = projects.filter((p) => !p.studyId);
  const otherStudyProjects = projects.filter(
    (p) => p.studyId && p.studyId !== editingId,
  );

  const isSaving = createStudy.isPending || updateStudy.isPending;
  const error =
    studiesQuery.error?.message ||
    actionError;

  const tools = form.tools ?? [];

  return (
    <Layout>
      <Header
        title="Studies"
        description="Create a study, then assign synced Kobo forms with tool codes (T1 / T2 / T3)"
        action={
          <Button size="sm" onClick={startCreate}>
            <Plus className="mr-2 h-4 w-4" />
            New study
          </Button>
        }
      />
      <div className="flex-1 overflow-auto bg-muted/30 p-4 md:p-6 space-y-6">
        <div className="rounded-md border bg-card p-3 text-sm text-muted-foreground">
          <ol className="list-decimal pl-5 space-y-1">
            <li>Create forms in KoboToolbox</li>
            <li>
              <Link href="/forms" className="underline text-primary">
                Sync from Kobo
              </Link>{" "}
              on the Forms page
            </li>
            <li>Create a study here, define tools and Kobo credentials, then assign forms</li>
            <li>Keep this study selected in the sidebar workspace for DQA and Reports</li>
          </ol>
        </div>
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

        <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
          <Card className="xl:col-span-1">
            <CardHeader className="py-4 border-b">
              <CardTitle className="text-sm">All studies</CardTitle>
            </CardHeader>
            <CardContent className="p-0 divide-y">
              {studies.length === 0 && (
                <p className="p-4 text-sm text-muted-foreground">No studies yet.</p>
              )}
              {studies.map((study) => (
                <button
                  key={study.id}
                  type="button"
                  onClick={() => startEdit(study)}
                  className={`w-full text-left p-4 hover:bg-muted/40 ${
                    panelMode === "edit" && editingId === study.id ? "bg-muted/60" : ""
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-sm">{study.name}</span>
                    {activeStudyId === study.id && (
                      <Badge variant="secondary" className="text-[10px]">
                        Active
                      </Badge>
                    )}
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {study.projectCount ?? 0} forms ·{" "}
                    {(study.submissionCount ?? 0).toLocaleString()} submissions
                    {study.dayNumber != null ? ` · Day ${study.dayNumber}` : ""}
                  </p>
                  <div className="mt-2 flex flex-wrap gap-1">
                    {(study.projects ?? []).map((p) => (
                      <Badge key={p.id} variant="outline" className="text-[10px]">
                        {p.toolCode || "—"} {p.name.slice(0, 24)}
                      </Badge>
                    ))}
                  </div>
                </button>
              ))}
            </CardContent>
          </Card>

          <Card className="xl:col-span-2">
            {panelMode === "idle" ? (
              <>
                <CardHeader className="py-4 border-b">
                  <CardTitle className="text-sm">Study details</CardTitle>
                </CardHeader>
                <CardContent className="p-8 text-center space-y-3">
                  <p className="text-sm text-muted-foreground">
                    {studies.length === 0
                      ? "No studies yet. Click “New study” to create one."
                      : "Select a study from the list, or click “New study” to create another."}
                  </p>
                  {studies.length === 0 && (
                    <Button size="sm" onClick={startCreate}>
                      <Plus className="mr-2 h-4 w-4" />
                      New study
                    </Button>
                  )}
                </CardContent>
              </>
            ) : (
              <>
            <CardHeader className="py-4 border-b flex flex-row items-center justify-between">
              <CardTitle className="text-sm">
                {panelMode === "edit" ? "Edit study" : "Create study"}
              </CardTitle>
              <div className="flex gap-2">
                {panelMode === "create" && (
                  <Button size="sm" variant="ghost" onClick={cancelCreate}>
                    <X className="mr-1 h-4 w-4" />
                    Cancel
                  </Button>
                )}
                {panelMode === "edit" && editingId && (
                  <>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => setActiveStudyId(editingId)}
                      disabled={activeStudyId === editingId}
                    >
                      Set active
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="text-destructive"
                      disabled={deleteStudy.isPending}
                      onClick={() => {
                        if (confirm("Delete this study? Forms stay in Kobo; only local grouping is removed.")) {
                          void removeStudy(editingId);
                        }
                      }}
                    >
                      <Trash2 className="mr-1 h-4 w-4" />
                      Delete
                    </Button>
                  </>
                )}
                <Button
                  size="sm"
                  disabled={isSaving || !form.name.trim()}
                  onClick={() => void saveStudy()}
                >
                  <Save className="mr-1 h-4 w-4" />
                  Save
                </Button>
              </div>
            </CardHeader>
            <CardContent className="p-4 space-y-4">
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-1.5 sm:col-span-2">
                  <Label>Name</Label>
                  <Input
                    value={form.name}
                    onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                    placeholder="e.g. Inclusive Education Baseline"
                  />
                </div>
                <div className="space-y-1.5 sm:col-span-2">
                  <Label>Description</Label>
                  <Input
                    value={form.description ?? ""}
                    onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label>Start date (Day 1)</Label>
                  <Input
                    type="date"
                    value={form.startDate ?? ""}
                    onChange={(e) => setForm((f) => ({ ...f, startDate: e.target.value }))}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label>End date (optional)</Label>
                  <Input
                    type="date"
                    value={form.endDate ?? ""}
                    onChange={(e) => setForm((f) => ({ ...f, endDate: e.target.value }))}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label>Timezone</Label>
                  <Input
                    value={form.timezone ?? "Asia/Kolkata"}
                    onChange={(e) => setForm((f) => ({ ...f, timezone: e.target.value }))}
                  />
                </div>
              </div>

              <div className="border-t pt-4 space-y-3">
                <Label>Tools (codes, labels, coverage targets)</Label>
                <div className="space-y-2">
                  {tools.map((tool, index) => (
                    <div key={tool.id ?? `${tool.code}-${index}`} className="flex flex-wrap items-center gap-2 rounded border px-2 py-1.5 text-sm">
                      <span className="font-mono text-xs w-12">{tool.code}</span>
                      <Input
                        className="h-8 flex-1 min-w-[120px]"
                        value={tool.label ?? ""}
                        onChange={(e) =>
                          setForm((f) => ({
                            ...f,
                            tools: (f.tools ?? []).map((t, i) =>
                              i === index ? { ...t, label: e.target.value } : t,
                            ),
                          }))
                        }
                        placeholder="Label"
                      />
                      <Input
                        className="h-8 w-24"
                        type="number"
                        value={tool.targetCount ?? 0}
                        onChange={(e) =>
                          setForm((f) => ({
                            ...f,
                            tools: (f.tools ?? []).map((t, i) =>
                              i === index ? { ...t, targetCount: Number(e.target.value) } : t,
                            ),
                          }))
                        }
                      />
                      <button
                        type="button"
                        onClick={() =>
                          setForm((f) => ({
                            ...f,
                            tools: (f.tools ?? []).filter((_, i) => i !== index),
                          }))
                        }
                      >
                        <Trash2 className="h-3.5 w-3.5 text-muted-foreground" />
                      </button>
                    </div>
                  ))}
                </div>
                <div className="flex flex-wrap gap-2 max-w-xl">
                  <Input
                    className="w-24"
                    value={toolCode}
                    onChange={(e) => setToolCode(e.target.value.toUpperCase())}
                    placeholder="T1"
                  />
                  <Input
                    className="flex-1 min-w-[120px]"
                    value={toolLabel}
                    onChange={(e) => setToolLabel(e.target.value)}
                    placeholder="Label"
                  />
                  <Input
                    className="w-24"
                    type="number"
                    value={toolTarget}
                    onChange={(e) => setToolTarget(e.target.value)}
                    placeholder="440"
                  />
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => {
                      if (!toolCode.trim()) return;
                      setForm((f) => ({
                        ...f,
                        tools: [
                          ...(f.tools ?? []),
                          {
                            code: toolCode.trim().toUpperCase(),
                            label: toolLabel.trim() || toolCode.trim().toUpperCase(),
                            targetCount: Number(toolTarget || 0),
                            sortOrder: (f.tools ?? []).length,
                          },
                        ],
                      }));
                      setToolLabel("");
                      setToolTarget("");
                    }}
                  >
                    Add tool
                  </Button>
                </div>
              </div>

              {panelMode === "edit" && editingId && (
                <div className="border-t pt-4 space-y-3">
                  <Label>KoboToolbox connection</Label>
                  <p className="text-xs text-muted-foreground">
                    One Kobo account per study. Sync on the Forms page uses these credentials.
                  </p>
                  <div className="grid gap-3 md:grid-cols-2">
                    <div className="space-y-1.5 md:col-span-2">
                      <Label className="text-xs">Server URL</Label>
                      <Input
                        className="font-mono text-sm"
                        value={koboServerUrl}
                        onChange={(e) => setKoboServerUrl(e.target.value)}
                      />
                    </div>
                    <div className="space-y-1.5">
                      <Label className="text-xs">API token</Label>
                      <Input
                        type="password"
                        className="font-mono text-sm"
                        value={koboApiToken}
                        onChange={(e) => setKoboApiToken(e.target.value)}
                        autoComplete="off"
                      />
                    </div>
                    <div className="space-y-1.5">
                      <Label className="text-xs">Username (optional)</Label>
                      <Input
                        value={koboUsername}
                        onChange={(e) => setKoboUsername(e.target.value)}
                      />
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Button
                      type="button"
                      variant="outline"
                      disabled={updateStudyKobo.isPending}
                      onClick={() => {
                        setKoboFeedback(null);
                        updateStudyKobo.mutate({
                          studyId: editingId,
                          data: {
                            serverUrl: koboServerUrl,
                            apiToken: koboApiToken,
                            username: koboUsername,
                          },
                        });
                      }}
                    >
                      {updateStudyKobo.isPending ? "Saving…" : "Save & connect"}
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      disabled={testStudyKobo.isPending || !koboApiToken}
                      onClick={() => {
                        setKoboFeedback(null);
                        testStudyKobo.mutate({ studyId: editingId });
                      }}
                    >
                      {testStudyKobo.isPending ? "Testing…" : "Test connection"}
                    </Button>
                    {(studyKoboQuery.data?.connected || editing?.credential?.connected) && !koboFeedback && (
                      <span className="text-sm text-green-600 dark:text-green-400 flex items-center font-medium">
                        <CheckCircle2 className="w-4 h-4 mr-1" /> Connected
                      </span>
                    )}
                  </div>
                  {koboFeedback && (
                    <div
                      className={`flex items-start gap-2 rounded-md border p-3 text-sm ${
                        koboFeedback.success
                          ? "border-green-200 bg-green-50 text-green-800"
                          : "border-destructive/30 bg-destructive/5 text-destructive"
                      }`}
                    >
                      {koboFeedback.success ? (
                        <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
                      ) : (
                        <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                      )}
                      {koboFeedback.message}
                    </div>
                  )}
                </div>
              )}

              {panelMode === "edit" && editingId && (
                <div className="border-t pt-4 space-y-3">
                  <Label>Forms in this study</Label>
                  <div className="divide-y rounded-md border">
                    {(editing?.projects ?? []).length === 0 && (
                      <p className="p-3 text-sm text-muted-foreground">
                        No forms assigned yet.{" "}
                        <Link href="/forms" className="underline text-primary">
                          Sync from Kobo
                        </Link>{" "}
                        first, then assign unassigned forms below.
                      </p>
                    )}
                    {(editing?.projects ?? []).map((p) => (
                      <div
                        key={p.id}
                        className="flex items-center justify-between gap-2 p-3 text-sm"
                      >
                        <div>
                          <Badge variant="outline" className="mr-2 font-mono text-[10px]">
                            {p.toolCode || "—"}
                          </Badge>
                          <Link className="text-primary underline" href={`/forms/${p.id}`}>
                            {p.name}
                          </Link>
                          <span className="ml-2 text-xs text-muted-foreground">
                            {(p.submissionCount ?? 0).toLocaleString()} submissions
                          </span>
                        </div>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => void unassignProject(p.id)}
                        >
                          Remove
                        </Button>
                      </div>
                    ))}
                  </div>
                  <div className="space-y-2">
                    <Label className="text-xs text-muted-foreground">
                      Assign a synced form ({unassignedProjects.length} unassigned)
                    </Label>
                    <div className="flex flex-wrap gap-2">
                      <select
                        className="h-9 flex-1 min-w-[180px] rounded-md border bg-background px-2 text-sm"
                        value={assignProjectId}
                        onChange={(e) => setAssignProjectId(e.target.value)}
                      >
                        <option value="">Choose a form…</option>
                        {unassignedProjects.length > 0 && (
                          <optgroup label="Unassigned">
                            {unassignedProjects.map((p) => (
                              <option key={p.id} value={p.id}>
                                {p.name}
                              </option>
                            ))}
                          </optgroup>
                        )}
                        {otherStudyProjects.length > 0 && (
                          <optgroup label="In another study (will move)">
                            {otherStudyProjects.map((p) => (
                              <option key={p.id} value={p.id}>
                                [{p.toolCode || "—"}] {p.name}
                              </option>
                            ))}
                          </optgroup>
                        )}
                      </select>
                      <Input
                        className="h-9 w-20"
                        value={assignTool}
                        onChange={(e) => setAssignTool(e.target.value.toUpperCase())}
                        placeholder="T1"
                      />
                      <Button
                        variant="outline"
                        disabled={!assignProjectId || assignStudyProject.isPending}
                        onClick={() => void assignProject()}
                      >
                        Assign
                      </Button>
                    </div>
                    {projects.length === 0 && (
                      <p className="text-xs text-muted-foreground">
                        No forms synced yet. Go to Forms → Sync from Kobo.
                      </p>
                    )}
                  </div>
                </div>
              )}
            </CardContent>
              </>
            )}
          </Card>
        </div>
      </div>
    </Layout>
  );
}
