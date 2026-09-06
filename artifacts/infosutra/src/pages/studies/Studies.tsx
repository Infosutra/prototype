import React, { useEffect, useMemo, useState } from "react";
import { Link } from "wouter";
import { useQueryClient } from "@tanstack/react-query";
import {
  getGetProjectsQueryKey,
  getGetStudiesQueryKey,
  getGetStudyScheduleQueryKey,
  useAssignStudyProject,
  useCreateStudy,
  useDeleteStudy,
  useGetProjects,
  useGetPrompts,
  useGetStudies,
  useUnassignStudyProject,
  useUpdateStudy,
  useGetStudyKobo,
  useUpdateStudyKobo,
  useTestStudyKoboConnection,
  useGetStudySchedule,
  useUpdateStudySchedule,
  useSyncProjects,
  type StudyCreate,
  type StudyOut,
  type StudyToolIn,
} from "@workspace/api-client-react";
import { Layout } from "@/components/layout/Layout";
import { Header } from "@/components/layout/Header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { AlertCircle, ArrowLeft, CheckCircle2, CircleHelp, Plus, RefreshCw, Save, Trash2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { useStudy } from "@/components/study/StudyProvider";

function parseRecipientInput(value: string): string[] {
  return [...new Set(value.split(/[,;\n]+/).map((item) => item.trim()).filter(Boolean))];
}

function emptyForm(): StudyCreate {
  return {
    name: "",
    description: "",
    startDate: "",
    endDate: "",
    timezone: "Asia/Kolkata",
    dailyDqaPromptId: null,
    finalDqaPromptId: null,
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

type FormLabelDraft = {
  toolCode: string;
  label: string;
  targetCount: number;
};

function defaultToolCode(index: number): string {
  return `T${index + 1}`;
}

export default function StudiesPage() {
  const queryClient = useQueryClient();
  const { activeStudyId, setActiveStudyId, refetch } = useStudy();
  const studiesQuery = useGetStudies();
  const projectsQuery = useGetProjects();
  const promptsQuery = useGetPrompts();
  const studies = studiesQuery.data ?? [];
  const projects = projectsQuery.data ?? [];
  const prompts = promptsQuery.data ?? [];

  const [panelMode, setPanelMode] = useState<PanelMode>("idle");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<StudyCreate>(emptyForm());
  const [assignProjectId, setAssignProjectId] = useState("");
  const [assignTool, setAssignTool] = useState("T1");
  const [assignLabel, setAssignLabel] = useState("");
  const [koboServerUrl, setKoboServerUrl] = useState("https://kf.kobotoolbox.org");
  const [koboApiToken, setKoboApiToken] = useState("");
  const [koboUsername, setKoboUsername] = useState("");
  const [koboFeedback, setKoboFeedback] = useState<{ success: boolean; message: string } | null>(null);
  const [scheduleEnabled, setScheduleEnabled] = useState(false);
  const [scheduleTime, setScheduleTime] = useState("21:30");
  const [scheduleTimezone, setScheduleTimezone] = useState("Asia/Kolkata");
  const [scheduleRecipients, setScheduleRecipients] = useState("");
  const [scheduleFeedback, setScheduleFeedback] = useState<{ success: boolean; message: string } | null>(null);
  const [message, setMessage] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [createPhase, setCreatePhase] = useState<string | null>(null);
  const [formLabels, setFormLabels] = useState<Record<string, FormLabelDraft>>({});
  const [isSavingLabels, setIsSavingLabels] = useState(false);

  const createStudy = useCreateStudy();
  const updateStudy = useUpdateStudy();
  const deleteStudy = useDeleteStudy();
  const assignStudyProject = useAssignStudyProject();
  const unassignStudyProject = useUnassignStudyProject();
  const syncProjects = useSyncProjects();
  const studyKoboQuery = useGetStudyKobo(editingId ?? "", {
    query: { enabled: Boolean(editingId) } as never,
  });
  const studyScheduleQuery = useGetStudySchedule(editingId ?? "", {
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
  const updateStudySchedule = useUpdateStudySchedule({
    mutation: {
      onSuccess: (schedule) => {
        setScheduleEnabled(Boolean(schedule.enabled));
        setScheduleTime(schedule.time || "21:30");
        setScheduleTimezone(schedule.timezone || "Asia/Kolkata");
        setScheduleRecipients((schedule.recipients ?? []).join("\n"));
        setScheduleFeedback({ success: true, message: "Daily DQA schedule saved." });
        if (editingId) {
          queryClient.invalidateQueries({
            queryKey: getGetStudyScheduleQueryKey(editingId),
          });
        }
      },
      onError: (err) =>
        setScheduleFeedback({
          success: false,
          message: err instanceof Error ? err.message : "Schedule save failed",
        }),
    },
  });

  useEffect(() => {
    const schedule = studyScheduleQuery.data;
    if (!schedule || !editingId) return;
    setScheduleEnabled(Boolean(schedule.enabled));
    setScheduleTime(schedule.time || "21:30");
    setScheduleTimezone(schedule.timezone || "Asia/Kolkata");
    setScheduleRecipients((schedule.recipients ?? []).join("\n"));
  }, [studyScheduleQuery.data, editingId]);

  const editing = useMemo(
    () => studies.find((s) => s.id === editingId) ?? null,
    [studies, editingId],
  );

  const studyProjects = useMemo(() => {
    if (!editingId) return [];
    return projects.filter((p) => p.studyId === editingId);
  }, [projects, editingId]);

  const startCreate = () => {
    setPanelMode("create");
    setEditingId(null);
    setForm(emptyForm());
    setMessage("");
    setActionError(null);
    setKoboFeedback(null);
    setKoboServerUrl("https://kf.kobotoolbox.org");
    setKoboApiToken("");
    setKoboUsername("");
    setFormLabels({});
    setCreatePhase(null);
  };

  const clearPanel = () => {
    setPanelMode("idle");
    setEditingId(null);
    setForm(emptyForm());
    setFormLabels({});
    setCreatePhase(null);
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
      dailyDqaPromptId: study.dailyDqaPromptId ?? null,
      finalDqaPromptId: study.finalDqaPromptId ?? null,
      tools: toolsFromStudy(study),
    });
    setMessage("");
    setActionError(null);
    setKoboFeedback(null);
    setScheduleFeedback(null);
    setCreatePhase(null);
  };

  const invalidateStudyQueries = () => {
    queryClient.invalidateQueries({ queryKey: getGetStudiesQueryKey() });
    queryClient.invalidateQueries({ queryKey: getGetProjectsQueryKey() });
    refetch();
  };

  const applyStudyToForm = (study: StudyOut, statusMessage?: string) => {
    setMessage(statusMessage ?? `Saved study “${study.name}”.`);
    setPanelMode("edit");
    setEditingId(study.id);
    setActiveStudyId(study.id);
    setForm({
      name: study.name,
      description: study.description ?? "",
      startDate: study.startDate ?? "",
      endDate: study.endDate ?? "",
      timezone: study.timezone || "Asia/Kolkata",
      dailyDqaPromptId: study.dailyDqaPromptId ?? null,
      finalDqaPromptId: study.finalDqaPromptId ?? null,
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
      dailyDqaPromptId: form.dailyDqaPromptId || null,
      finalDqaPromptId: form.finalDqaPromptId || null,
    };
    try {
      if (panelMode === "edit" && editingId) {
        const study = await updateStudy.mutateAsync({ studyId: editingId, data: payload });
        applyStudyToForm(study);
      }
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Save failed");
    }
  };

  const createStudyAndPullForms = async () => {
    setActionError(null);
    setKoboFeedback(null);
    if (!form.name.trim()) {
      setActionError("Enter a study name");
      return;
    }
    if (!koboApiToken.trim()) {
      setActionError("Enter your Kobo API token to pull forms");
      return;
    }

    setIsCreating(true);
    let createdStudyId: string | null = null;
    try {
      setCreatePhase("Creating study…");
      const payload: StudyCreate = {
        ...form,
        tools: [],
        startDate: form.startDate || null,
        endDate: form.endDate || null,
      };
      const study = await createStudy.mutateAsync({ data: payload });
      createdStudyId = study.id;

      setCreatePhase("Connecting Kobo…");
      setEditingId(study.id);
      setActiveStudyId(study.id);
      await updateStudyKobo.mutateAsync({
        studyId: study.id,
        data: {
          serverUrl: koboServerUrl,
          apiToken: koboApiToken,
          username: koboUsername,
        },
      });

      setCreatePhase("Pulling forms from Kobo…");
      const syncResult = await syncProjects.mutateAsync({
        params: { studyId: study.id },
      });

      await queryClient.refetchQueries({ queryKey: getGetProjectsQueryKey() });
      await queryClient.refetchQueries({ queryKey: getGetStudiesQueryKey() });
      await refetch();

      const syncedForms =
        (queryClient.getQueryData(getGetProjectsQueryKey()) as typeof projects | undefined) ?? [];
      const studyForms = syncedForms.filter((p) => p.studyId === study.id);
      const drafts: Record<string, FormLabelDraft> = {};
      studyForms.forEach((p, index) => {
        drafts[p.id] = {
          toolCode: (p.toolCode || defaultToolCode(index)).toUpperCase(),
          label: p.name || defaultToolCode(index),
          targetCount: 0,
        };
      });
      setFormLabels(drafts);

      const syncedCount = syncResult.projectsSynced ?? studyForms.length;
      const errNote =
        (syncResult.errors?.length ?? 0) > 0
          ? ` ${syncResult.errors.length} form(s) had sync errors.`
          : "";
      applyStudyToForm(
        study,
        `Study “${study.name}” created. Pulled ${syncedCount} form(s).${errNote} Assign a tool code and label to each form below.`,
      );
      setCreatePhase(null);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Create failed");
      setCreatePhase(null);
      if (createdStudyId) {
        setPanelMode("edit");
        setEditingId(createdStudyId);
        setActiveStudyId(createdStudyId);
        invalidateStudyQueries();
        setMessage(
          "Study was created, but setup did not finish. Connect Kobo and pull forms to continue.",
        );
      }
    } finally {
      setIsCreating(false);
    }
  };

  const removeStudy = async (id: string) => {
    setActionError(null);
    try {
      await deleteStudy.mutateAsync({ studyId: id });
      setMessage("Study deleted.");
      clearPanel();
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
    const picked = projects.find((p) => p.id === assignProjectId);
    const label = assignLabel.trim() || picked?.name || undefined;
    try {
      await assignStudyProject.mutateAsync({
        studyId: editingId,
        data: {
          projectId: assignProjectId,
          toolCode: assignTool || undefined,
          label,
        },
      });
      setMessage("Form assigned to study.");
      setAssignProjectId("");
      setAssignLabel("");
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
      setFormLabels((prev) => {
        const next = { ...prev };
        delete next[projectId];
        return next;
      });
      queryClient.invalidateQueries({ queryKey: getGetStudiesQueryKey() });
      queryClient.invalidateQueries({ queryKey: getGetProjectsQueryKey() });
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Unassign failed");
    }
  };

  const saveFormLabels = async () => {
    if (!editingId) return;
    setActionError(null);
    setIsSavingLabels(true);
    try {
      const entries = studyProjects.map((p) => {
        const draft = formLabels[p.id];
        return {
          projectId: p.id,
          formName: p.name,
          toolCode: (draft?.toolCode || "").trim().toUpperCase(),
          label: (draft?.label || "").trim() || p.name,
          targetCount: Number(draft?.targetCount ?? 0),
        };
      });
      const missing = entries.find((e) => !e.toolCode);
      if (missing) {
        setActionError("Every form needs a tool code (T1, T2, …)");
        return;
      }

      const toolsByCode = new Map<string, StudyToolIn>();
      entries.forEach((e, index) => {
        const prev = toolsByCode.get(e.toolCode);
        const existingId = (form.tools ?? []).find(
          (t) => t.code.toUpperCase() === e.toolCode,
        )?.id;
        toolsByCode.set(e.toolCode, {
          code: e.toolCode,
          label: e.label,
          targetCount: e.targetCount || prev?.targetCount || 0,
          sortOrder: prev?.sortOrder ?? index,
          id: existingId,
        });
      });
      const tools = [...toolsByCode.values()];

      const study = await updateStudy.mutateAsync({
        studyId: editingId,
        data: { tools },
      });

      for (const entry of entries) {
        await assignStudyProject.mutateAsync({
          studyId: editingId,
          data: {
            projectId: entry.projectId,
            toolCode: entry.toolCode,
            label: entry.label,
          },
        });
      }

      applyStudyToForm(study, "Tools saved.");
      setForm({
        name: study.name,
        description: study.description ?? "",
        startDate: study.startDate ?? "",
        endDate: study.endDate ?? "",
        timezone: study.timezone || "Asia/Kolkata",
        dailyDqaPromptId: study.dailyDqaPromptId ?? null,
        finalDqaPromptId: study.finalDqaPromptId ?? null,
        tools: toolsFromStudy(study),
      });
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to save tools");
    } finally {
      setIsSavingLabels(false);
    }
  };

  const pullFormsAgain = async () => {
    if (!editingId) return;
    setActionError(null);
    setCreatePhase("Pulling forms from Kobo…");
    try {
      const syncResult = await syncProjects.mutateAsync({
        params: { studyId: editingId },
      });
      await queryClient.invalidateQueries({ queryKey: getGetProjectsQueryKey() });
      await queryClient.invalidateQueries({ queryKey: getGetStudiesQueryKey() });
      const errNote =
        syncResult.errors?.length > 0
          ? ` ${syncResult.errors.length} form(s) had sync errors.`
          : "";
      setMessage(`Pulled ${syncResult.projectsSynced} form(s).${errNote} Update tool codes below if needed.`);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Sync failed");
    } finally {
      setCreatePhase(null);
    }
  };

  useEffect(() => {
    const cred = studyKoboQuery.data ?? editing?.credential;
    if (!cred || panelMode === "create") return;
    setKoboServerUrl(cred.serverUrl || "https://kf.kobotoolbox.org");
    setKoboApiToken(cred.apiToken || "");
    setKoboUsername(cred.username || "");
  }, [studyKoboQuery.data, editing?.credential, editingId, panelMode]);

  // Keep form/tool drafts in sync when study projects load/change
  useEffect(() => {
    if (panelMode !== "edit" || !editingId) return;
    setFormLabels((prev) => {
      const toolsByCode = new Map(
        (editing?.tools ?? form.tools ?? []).map((t) => [
          t.code.toUpperCase(),
          { label: t.label ?? "", targetCount: t.targetCount ?? 0 },
        ]),
      );
      const next: Record<string, FormLabelDraft> = {};
      studyProjects.forEach((p, index) => {
        if (prev[p.id]) {
          next[p.id] = prev[p.id];
          return;
        }
        const code = (p.toolCode || defaultToolCode(index)).toUpperCase();
        const tool = toolsByCode.get(code);
        next[p.id] = {
          toolCode: code,
          // Default label is the Kobo form name
          label: p.name || tool?.label || code,
          targetCount: tool?.targetCount ?? 0,
        };
      });
      return next;
    });
  }, [studyProjects, editingId, panelMode, editing?.tools, form.tools]);

  const unassignedProjects = projects.filter((p) => !p.studyId);

  const isSaving = updateStudy.isPending;
  const error =
    studiesQuery.error?.message ||
    actionError;

  const primaryBusy = isCreating || syncProjects.isPending;

  return (
    <Layout>
      <Header
        title="Studies"
        description="Create a study with Kobo Credentials"
        action={
          <>
            <Dialog>
              <DialogTrigger asChild>
                <Button variant="outline" size="sm" aria-label="Getting started help">
                  <CircleHelp className="mr-2 h-4 w-4" />
                  Help
                </Button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>Getting started with studies</DialogTitle>
                  <DialogDescription>
                    Follow these steps to connect Kobo forms to a study workspace.
                  </DialogDescription>
                </DialogHeader>
                <ol className="list-decimal pl-5 space-y-2 text-sm text-muted-foreground">
                  <li>Create forms in KoboToolbox</li>
                  <li>
                    Click <strong>New study</strong>, enter study details and your Kobo credentials
                  </li>
                  <li>
                    Forms are pulled automatically — assign each a tool code (T1, T2, …) and label
                  </li>
                  <li>Keep this study selected in the sidebar workspace for DQA and Reports</li>
                </ol>
              </DialogContent>
            </Dialog>
            <Button size="sm" onClick={startCreate}>
              <Plus className="mr-2 h-4 w-4" />
              New study
            </Button>
          </>
        }
      />
      <div className="flex-1 overflow-auto bg-muted/30 p-4 md:p-6 space-y-6">
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
        {createPhase && (
          <div className="flex items-center gap-2 rounded-md border bg-card p-3 text-sm text-muted-foreground">
            <RefreshCw className="h-4 w-4 animate-spin shrink-0" />
            {createPhase}
          </div>
        )}

        {panelMode === "idle" ? (
          studiesQuery.isLoading ? (
            <p className="text-sm text-muted-foreground">Loading studies…</p>
          ) : studies.length === 0 ? (
            <Card>
              <CardContent className="p-8 text-center space-y-3">
                <p className="text-sm text-muted-foreground">
                  No studies yet. Click “New study” to create one with your Kobo credentials.
                </p>
                <Button size="sm" onClick={startCreate}>
                  <Plus className="mr-2 h-4 w-4" />
                  New study
                </Button>
              </CardContent>
            </Card>
          ) : (
            <div className="overflow-x-auto rounded-md border bg-card">
              <table className="w-full min-w-[800px] text-sm">
                <thead className="bg-muted/50 text-left">
                  <tr>
                    <th className="p-3 font-medium">Study</th>
                    <th className="p-3 font-medium">Forms</th>
                    <th className="p-3 font-medium">Submissions</th>
                    <th className="p-3 font-medium">Day</th>
                    <th className="p-3 font-medium">Kobo</th>
                    <th className="p-3 font-medium">Tools</th>
                    <th className="p-3 font-medium text-right">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {studies.map((study) => (
                    <tr
                      key={study.id}
                      className="border-t cursor-pointer hover:bg-muted/40"
                      onClick={() => startEdit(study)}
                    >
                      <td className="p-3 align-top">
                        <div className="flex items-center gap-2">
                          <span className="font-medium">{study.name}</span>
                          {activeStudyId === study.id && (
                            <Badge variant="secondary" className="text-[10px]">
                              Active
                            </Badge>
                          )}
                        </div>
                        {study.description ? (
                          <p className="text-xs text-muted-foreground line-clamp-2 mt-0.5">
                            {study.description}
                          </p>
                        ) : null}
                      </td>
                      <td className="p-3 align-top tabular-nums">
                        {study.projectCount ?? 0}
                      </td>
                      <td className="p-3 align-top tabular-nums">
                        {(study.submissionCount ?? 0).toLocaleString()}
                      </td>
                      <td className="p-3 align-top text-muted-foreground">
                        {study.dayNumber != null ? `Day ${study.dayNumber}` : "—"}
                      </td>
                      <td className="p-3 align-top">
                        {study.credential?.connected ? (
                          <span className="inline-flex items-center gap-1 text-green-700 text-xs font-medium">
                            <CheckCircle2 className="h-3.5 w-3.5" />
                            Connected
                          </span>
                        ) : (
                          <span className="text-xs text-muted-foreground">Not connected</span>
                        )}
                      </td>
                      <td className="p-3 align-top">
                        <div className="flex flex-wrap gap-1">
                          {(study.tools ?? []).length === 0 && (
                            <span className="text-xs text-muted-foreground">—</span>
                          )}
                          {(study.tools ?? []).map((t) => (
                            <Badge key={t.id} variant="outline" className="text-[10px] font-mono">
                              {t.code}
                              {t.label ? ` · ${t.label}` : ""}
                              {t.targetCount ? ` (${t.targetCount})` : ""}
                            </Badge>
                          ))}
                        </div>
                      </td>
                      <td
                        className="p-3 align-top"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <div className="flex justify-end gap-2">
                          {activeStudyId !== study.id && (
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => setActiveStudyId(study.id)}
                            >
                              Set active
                            </Button>
                          )}
                          <Button size="sm" variant="outline" onClick={() => startEdit(study)}>
                            Edit
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        ) : (
          <Card>
            <CardHeader className="py-4 border-b flex flex-row items-center justify-between gap-3">
              <Button
                size="sm"
                className="gap-1 bg-primary text-primary-foreground"
                onClick={clearPanel}
                disabled={primaryBusy}
              >
                <ArrowLeft className="h-4 w-4" />
                Back
              </Button>
              <div className="flex gap-2 shrink-0">
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
                    <Button
                      size="sm"
                      disabled={isSaving || !form.name.trim()}
                      onClick={() => void saveStudy()}
                    >
                      <Save className="mr-1 h-4 w-4" />
                      Save
                    </Button>
                  </>
                )}
                {panelMode === "create" && (
                  <Button
                    size="sm"
                    disabled={primaryBusy || !form.name.trim() || !koboApiToken.trim()}
                    onClick={() => void createStudyAndPullForms()}
                  >
                    {primaryBusy ? (
                      <RefreshCw className="mr-1 h-4 w-4 animate-spin" />
                    ) : (
                      <Plus className="mr-1 h-4 w-4" />
                    )}
                    {primaryBusy ? "Working…" : "Create & pull forms"}
                  </Button>
                )}
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
              </div>

              <div className="border-t pt-4 space-y-3">
                <Label>KoboToolbox connection</Label>
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
                {panelMode === "edit" && editingId && (
                  <div className="flex flex-wrap items-center gap-2">
                    <Button
                      type="button"
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
                      disabled={testStudyKobo.isPending || !koboApiToken}
                      onClick={() => {
                        setKoboFeedback(null);
                        testStudyKobo.mutate({ studyId: editingId });
                      }}
                    >
                      {testStudyKobo.isPending ? "Testing…" : "Test connection"}
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      disabled={syncProjects.isPending || !editingId}
                      onClick={() => void pullFormsAgain()}
                    >
                      <RefreshCw
                        className={`mr-1 h-4 w-4 ${syncProjects.isPending ? "animate-spin" : ""}`}
                      />
                      Pull forms
                    </Button>
                    {(studyKoboQuery.data?.connected || editing?.credential?.connected) && !koboFeedback && (
                      <span className="text-sm text-green-600 dark:text-green-400 flex items-center font-medium">
                        <CheckCircle2 className="w-4 h-4 mr-1" /> Connected
                      </span>
                    )}
                  </div>
                )}
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

              {panelMode === "edit" && editingId && (
                <div className="border-t pt-4 space-y-3">
                  <div className="flex items-center justify-between gap-2">
                    <div>
                      <Label>Tools (codes, labels, coverage targets)</Label>
                      <p className="text-xs text-muted-foreground mt-1">
                        One row per form. Label defaults to the form name — set the coverage target.
                      </p>
                    </div>
                    {studyProjects.length > 0 && (
                      <Button
                        size="sm"
                        disabled={isSavingLabels}
                        onClick={() => void saveFormLabels()}
                      >
                        <Save className="mr-1 h-4 w-4" />
                        {isSavingLabels ? "Saving…" : "Save tools"}
                      </Button>
                    )}
                  </div>
                  <div className="overflow-x-auto rounded-md border">
                    <table className="w-full min-w-[640px] text-sm">
                      <thead className="bg-muted/50 text-left">
                        <tr>
                          <th className="p-2.5 font-medium">Form</th>
                          <th className="p-2.5 font-medium w-24">Code</th>
                          <th className="p-2.5 font-medium">Label</th>
                          <th className="p-2.5 font-medium w-36">Coverage target</th>
                          <th className="p-2.5 font-medium w-20 text-right"> </th>
                        </tr>
                      </thead>
                      <tbody>
                        {studyProjects.length === 0 && (
                          <tr className="border-t">
                            <td colSpan={5} className="p-3 text-muted-foreground">
                              No forms yet. Use <strong>Pull forms</strong> above after connecting
                              Kobo, or assign an unassigned form below.
                            </td>
                          </tr>
                        )}
                        {studyProjects.map((p, index) => {
                          const draft = formLabels[p.id] ?? {
                            toolCode: p.toolCode || defaultToolCode(index),
                            label: p.name,
                            targetCount: 0,
                          };
                          return (
                            <tr key={p.id} className="border-t">
                              <td className="p-2 align-middle">
                                <Link
                                  className="text-primary underline font-medium"
                                  href={`/forms/${p.id}`}
                                >
                                  {p.name}
                                </Link>
                                <span className="ml-2 text-xs text-muted-foreground tabular-nums">
                                  {(p.submissionCount ?? 0).toLocaleString()} submissions
                                </span>
                              </td>
                              <td className="p-2 align-middle">
                                <Input
                                  className="h-8 font-mono text-xs"
                                  value={draft.toolCode}
                                  onChange={(e) =>
                                    setFormLabels((prev) => ({
                                      ...prev,
                                      [p.id]: {
                                        ...draft,
                                        toolCode: e.target.value.toUpperCase(),
                                      },
                                    }))
                                  }
                                  placeholder="T1"
                                />
                              </td>
                              <td className="p-2 align-middle">
                                <Input
                                  className="h-8"
                                  value={draft.label}
                                  onChange={(e) =>
                                    setFormLabels((prev) => ({
                                      ...prev,
                                      [p.id]: {
                                        ...draft,
                                        label: e.target.value,
                                      },
                                    }))
                                  }
                                  placeholder={p.name}
                                />
                              </td>
                              <td className="p-2 align-middle">
                                <Input
                                  className="h-8"
                                  type="number"
                                  value={draft.targetCount}
                                  onChange={(e) =>
                                    setFormLabels((prev) => ({
                                      ...prev,
                                      [p.id]: {
                                        ...draft,
                                        targetCount: Number(e.target.value),
                                      },
                                    }))
                                  }
                                  placeholder="440"
                                />
                              </td>
                              <td className="p-2 align-middle text-right">
                                <Button
                                  size="sm"
                                  variant="destructive"
                                  onClick={() => void unassignProject(p.id)}
                                >
                                  Remove
                                </Button>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                  <div className="space-y-2">
                    <Label className="text-xs text-muted-foreground">
                      Assign a synced form ({unassignedProjects.length} unassigned)
                    </Label>
                    <div className="flex flex-wrap gap-2">
                      <select
                        className="field-control h-9 flex-1 min-w-[180px] px-2 text-sm"
                        value={assignProjectId}
                        onChange={(e) => {
                          const id = e.target.value;
                          setAssignProjectId(id);
                          const picked = unassignedProjects.find((p) => p.id === id);
                          if (picked) setAssignLabel(picked.name);
                        }}
                      >
                        <option value="">Choose a form…</option>
                        {unassignedProjects.map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.name}
                          </option>
                        ))}
                      </select>
                      <Input
                        className="h-9 w-20"
                        value={assignTool}
                        onChange={(e) => setAssignTool(e.target.value.toUpperCase())}
                        placeholder="T1"
                      />
                      <Input
                        className="h-9 w-36"
                        value={assignLabel}
                        onChange={(e) => setAssignLabel(e.target.value)}
                        placeholder="Label"
                      />
                      <Button
                        disabled={!assignProjectId || assignStudyProject.isPending}
                        onClick={() => void assignProject()}
                      >
                        Assign
                      </Button>
                    </div>
                    {unassignedProjects.length === 0 && projects.length > 0 && (
                      <p className="text-xs text-muted-foreground">
                        No unassigned forms. Pull forms above.
                      </p>
                    )}
                    {projects.length === 0 && (
                      <p className="text-xs text-muted-foreground">
                        No forms synced yet. Connect Kobo and pull forms.
                      </p>
                    )}
                  </div>
                </div>
              )}

              {panelMode === "edit" && editingId && (
                <div className="border-t pt-4 space-y-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <Label>DQA report prompts</Label>
                      <p className="text-xs text-muted-foreground mt-0.5">
                        Leave as default to share the built-in prompt across studies. Create a
                        dedicated prompt under Prompt Templates when a study needs its own voice.
                      </p>
                    </div>
                    <Button size="sm" variant="outline" asChild>
                      <Link href="/prompts">Manage prompts</Link>
                    </Button>
                  </div>
                  <div className="grid gap-3 md:grid-cols-2">
                    <div className="space-y-1.5">
                      <Label className="text-xs">Daily DQA</Label>
                      <select
                        className="field-control h-9 w-full px-2 text-sm"
                        value={form.dailyDqaPromptId ?? ""}
                        onChange={(e) =>
                          setForm((f) => ({
                            ...f,
                            dailyDqaPromptId: e.target.value || null,
                          }))
                        }
                      >
                        <option value="">Default (shared Daily DQA)</option>
                        {prompts
                          .filter(
                            (p) =>
                              p.category === "daily-dqa" ||
                              p.id === form.dailyDqaPromptId,
                          )
                          .map((p) => (
                            <option key={p.id} value={p.id}>
                              {p.name}
                              {p.isSystem ? " · default" : ""}
                            </option>
                          ))}
                      </select>
                    </div>
                    <div className="space-y-1.5">
                      <Label className="text-xs">Final DQA</Label>
                      <select
                        className="field-control h-9 w-full px-2 text-sm"
                        value={form.finalDqaPromptId ?? ""}
                        onChange={(e) =>
                          setForm((f) => ({
                            ...f,
                            finalDqaPromptId: e.target.value || null,
                          }))
                        }
                      >
                        <option value="">Default (shared Final DQA)</option>
                        {prompts
                          .filter(
                            (p) =>
                              p.category === "final-dqa" ||
                              p.id === form.finalDqaPromptId,
                          )
                          .map((p) => (
                            <option key={p.id} value={p.id}>
                              {p.name}
                              {p.isSystem ? " · default" : ""}
                            </option>
                          ))}
                      </select>
                    </div>
                  </div>
                </div>
              )}

              {panelMode === "edit" && editingId && (
                <div className="border-t pt-4 space-y-3">
                  <div className="flex items-center justify-between gap-3">
                    <Label>Daily DQA email schedule</Label>
                    <Switch checked={scheduleEnabled} onCheckedChange={setScheduleEnabled} />
                  </div>
                  <div className="grid gap-3 md:grid-cols-2">
                    <div className="space-y-1.5">
                      <Label className="text-xs">Send time (HH:MM)</Label>
                      <Input
                        className="font-mono text-sm"
                        value={scheduleTime}
                        onChange={(e) => setScheduleTime(e.target.value)}
                        placeholder="21:30"
                      />
                    </div>
                    <div className="space-y-1.5">
                      <Label className="text-xs">Timezone</Label>
                      <Input
                        value={scheduleTimezone}
                        onChange={(e) => setScheduleTimezone(e.target.value)}
                        placeholder="Asia/Kolkata"
                      />
                    </div>
                    <div className="space-y-1.5 md:col-span-2">
                      <Label className="text-xs">Recipients (one per line or comma-separated)</Label>
                      <Textarea
                        className="min-h-[80px] font-mono text-sm"
                        value={scheduleRecipients}
                        onChange={(e) => setScheduleRecipients(e.target.value)}
                        placeholder="analyst@example.org"
                      />
                    </div>
                  </div>
                  {studyScheduleQuery.data?.lastSentOn && (
                    <p className="text-xs text-muted-foreground">
                      Last sent: {studyScheduleQuery.data.lastSentOn}
                    </p>
                  )}
                  <div className="flex flex-wrap items-center gap-2">
                    <Button
                      type="button"
                      disabled={updateStudySchedule.isPending}
                      onClick={() => {
                        setScheduleFeedback(null);
                        updateStudySchedule.mutate({
                          studyId: editingId,
                          data: {
                            enabled: scheduleEnabled,
                            time: scheduleTime,
                            timezone: scheduleTimezone,
                            recipients: parseRecipientInput(scheduleRecipients),
                          },
                        });
                      }}
                    >
                      {updateStudySchedule.isPending ? "Saving…" : "Save schedule"}
                    </Button>
                  </div>
                  {scheduleFeedback && (
                    <div
                      className={`flex items-start gap-2 rounded-md border p-3 text-sm ${
                        scheduleFeedback.success
                          ? "border-green-200 bg-green-50 text-green-800"
                          : "border-destructive/30 bg-destructive/5 text-destructive"
                      }`}
                    >
                      {scheduleFeedback.success ? (
                        <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
                      ) : (
                        <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                      )}
                      {scheduleFeedback.message}
                    </div>
                  )}
                </div>
              )}
            </CardContent>
          </Card>
        )}
      </div>
    </Layout>
  );
}
