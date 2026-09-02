import React, { useEffect, useState } from "react";
import { Link, useLocation } from "wouter";
import {
  getGetAudioRecordingQueryKey,
  getGetAudioRecordingsQueryKey,
  useCreateAudioRecording,
  useDeleteAudioRecording,
  useGetAudioRecordings,
  useTranscribeAudioRecording,
  type AudioRecordingSummary,
} from "@workspace/api-client-react";
import { useQueryClient } from "@tanstack/react-query";
import { Layout } from "@/components/layout/Layout";
import { Header } from "@/components/layout/Header";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
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
import { useStudy } from "@/components/study/StudyProvider";
import {
  formatBytes,
  formatDuration,
  isTranscriptionPending,
  requiresFirstTranscribeConfirmation,
  requiresRetranscribeConfirmation,
  StatusBadge,
  transcribeButtonClassName,
} from "@/pages/recordings/recording-ui";
import {
  TranscribeConfirmDialog,
  type TranscribeConfirmMode,
} from "@/pages/recordings/RetranscribeConfirmDialog";
import { TranscriptDownloadButtons } from "@/pages/recordings/TranscriptDownloadButtons";
import { FileAudio, Plus, Sparkles, Trash2 } from "lucide-react";

export default function Recordings() {
  const queryClient = useQueryClient();
  const [, setLocation] = useLocation();
  const { activeStudy, activeStudyId } = useStudy();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pollList, setPollList] = useState(false);
  const [transcribeConfirm, setTranscribeConfirm] = useState<{
    recording: AudioRecordingSummary;
    mode: TranscribeConfirmMode;
  } | null>(null);

  const recordingsQuery = useGetAudioRecordings(
    { studyId: activeStudyId ?? undefined },
    {
      query: {
        enabled: Boolean(activeStudyId),
        refetchInterval: pollList ? 3000 : false,
      } as never,
    },
  );

  const recordings = recordingsQuery.data ?? [];

  useEffect(() => {
    setPollList(recordings.some((r) => isTranscriptionPending(r.transcriptionStatus)));
  }, [recordings]);

  const createRecording = useCreateAudioRecording();
  const deleteRecording = useDeleteAudioRecording();
  const transcribeRecording = useTranscribeAudioRecording();

  const invalidate = async (recordingId?: string) => {
    await queryClient.invalidateQueries({
      queryKey: getGetAudioRecordingsQueryKey({ studyId: activeStudyId ?? undefined }),
    });
    if (recordingId) {
      await queryClient.invalidateQueries({ queryKey: getGetAudioRecordingQueryKey(recordingId) });
    }
  };

  const upload = async () => {
    setError(null);
    if (!activeStudyId) {
      setError("Select a study first");
      return;
    }
    if (!name.trim()) {
      setError("Name is required");
      return;
    }
    if (!file) {
      setError("Choose an audio file");
      return;
    }
    try {
      await createRecording.mutateAsync({
        data: {
          study_id: activeStudyId,
          name: name.trim(),
          description: description.trim(),
          file,
        },
      });
      await invalidate();
      setOpen(false);
      setName("");
      setDescription("");
      setFile(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    }
  };

  const remove = async (recording: AudioRecordingSummary) => {
    if (!confirm(`Delete recording “${recording.name}”?`)) return;
    try {
      await deleteRecording.mutateAsync({ recordingId: recording.id });
      await invalidate(recording.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    }
  };

  const transcribe = async (recording: AudioRecordingSummary) => {
    setError(null);
    try {
      const updated = await transcribeRecording.mutateAsync({
        recordingId: recording.id,
        data: {},
      });
      queryClient.setQueryData(getGetAudioRecordingQueryKey(recording.id), updated);
      await invalidate(recording.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Transcription failed to start");
    }
  };

  const requestTranscribe = (recording: AudioRecordingSummary) => {
    if (requiresFirstTranscribeConfirmation(recording.transcriptionStatus)) {
      setTranscribeConfirm({ recording, mode: "first" });
      return;
    }
    if (requiresRetranscribeConfirmation(recording.transcriptionStatus)) {
      setTranscribeConfirm({ recording, mode: "retry" });
      return;
    }
    void transcribe(recording);
  };

  const confirmTranscribe = () => {
    if (!transcribeConfirm) return;
    void transcribe(transcribeConfirm.recording).finally(() => setTranscribeConfirm(null));
  };

  if (!activeStudy) {
    return (
      <Layout>
        <Header title="Recordings" description="Upload and transcribe audio for this study" />
        <div className="flex-1 overflow-auto p-6">
          <Card>
            <CardContent className="p-8 text-center text-sm text-muted-foreground">
              Select or create a study to manage recordings.
            </CardContent>
          </Card>
        </div>
      </Layout>
    );
  }

  return (
    <Layout>
      <Header
        title="Recordings"
        description={`Audio uploads and transcripts for ${activeStudy.name}`}
        action={
          <Button size="sm" className="bg-primary text-primary-foreground" onClick={() => setOpen(true)}>
            <Plus className="w-4 h-4 mr-2" />
            Upload recording
          </Button>
        }
      />
      <div className="flex-1 overflow-auto p-4 md:p-6 bg-muted/30">
        {error && (
          <div className="mb-4 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
            {error}
          </div>
        )}
        {recordingsQuery.isLoading ? (
          <p className="text-sm text-muted-foreground">Loading recordings…</p>
        ) : recordings.length === 0 ? (
          <Card>
            <CardContent className="p-8 text-center text-sm text-muted-foreground">
              No recordings yet. Upload an interview, focus group, or field note to transcribe it.
            </CardContent>
          </Card>
        ) : (
          <div className="overflow-x-auto rounded-md border bg-card">
            <table className="w-full min-w-[720px] text-sm">
              <thead className="bg-muted/50 text-left">
                <tr>
                  <th className="p-3 font-medium">Recording</th>
                  <th className="p-3 font-medium">File</th>
                  <th className="p-3 font-medium">Status</th>
                  <th className="p-3 font-medium text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {recordings.map((recording) => (
                  <tr
                    key={recording.id}
                    className="border-t cursor-pointer hover:bg-muted/40"
                    onClick={() => setLocation(`/recordings/${recording.id}`)}
                  >
                    <td className="p-3 align-top">
                      <div className="flex items-start gap-2">
                        <FileAudio className="h-4 w-4 text-primary mt-0.5 shrink-0" />
                        <div className="min-w-0">
                          <Link
                            href={`/recordings/${recording.id}`}
                            className="font-medium hover:underline"
                            onClick={(e) => e.stopPropagation()}
                          >
                            {recording.name}
                          </Link>
                          <p className="text-xs text-muted-foreground line-clamp-2 mt-0.5">
                            {recording.description || "—"}
                          </p>
                        </div>
                      </div>
                    </td>
                    <td className="p-3 align-top text-muted-foreground">
                      <p className="truncate max-w-[220px]">{recording.originalFilename}</p>
                      <p className="text-xs mt-0.5">
                        {formatBytes(recording.sizeBytes)}
                        {recording.durationSeconds
                          ? ` · ${formatDuration(recording.durationSeconds)}`
                          : ""}
                      </p>
                    </td>
                    <td className="p-3 align-top">
                      <StatusBadge status={recording.transcriptionStatus} />
                      {recording.transcriptionStatus === "failed" && (
                        <p className="text-xs text-muted-foreground mt-1">
                          Transcription failed — open for details
                        </p>
                      )}
                    </td>
                    <td
                      className="p-3 align-top"
                      onClick={(event) => event.stopPropagation()}
                      onMouseDown={(event) => event.stopPropagation()}
                    >
                      <div className="flex justify-end items-center gap-2 flex-wrap">
                        {recording.transcriptionStatus === "succeeded" && (
                          <TranscriptDownloadButtons
                            recordingId={recording.id}
                            onClick={(e) => e.stopPropagation()}
                          />
                        )}
                        <Button
                          size="sm"
                          className={transcribeButtonClassName}
                          disabled={
                            isTranscriptionPending(recording.transcriptionStatus) ||
                            transcribeRecording.isPending
                          }
                          onClick={(e) => {
                            e.stopPropagation();
                            requestTranscribe(recording);
                          }}
                        >
                          <Sparkles className="h-3.5 w-3.5 mr-1.5" />
                          {recording.transcriptionStatus === "failed" ? "Retry" : "Transcribe"}
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          className="text-destructive hover:bg-destructive/10"
                          disabled={deleteRecording.isPending}
                          onClick={(e) => {
                            e.stopPropagation();
                            void remove(recording);
                          }}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Upload recording</DialogTitle>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <div className="space-y-1.5">
              <Label>Name</Label>
              <Input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Enumerator debrief — Block 3"
              />
            </div>
            <div className="space-y-1.5">
              <Label>Description</Label>
              <Textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Context for this recording"
                rows={3}
              />
            </div>
            <div className="space-y-1.5">
              <Label>Audio file</Label>
              <Input
                type="file"
                accept="audio/*,.mp3,.wav,.m4a,.ogg,.webm,.flac"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
              <p className="text-xs text-muted-foreground">mp3, wav, m4a, ogg, webm, or flac</p>
            </div>
            {error && <p className="text-sm text-destructive">{error}</p>}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button disabled={createRecording.isPending} onClick={() => void upload()}>
              {createRecording.isPending ? "Uploading…" : "Upload"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <TranscribeConfirmDialog
        recording={transcribeConfirm?.recording ?? null}
        mode={transcribeConfirm?.mode ?? null}
        open={transcribeConfirm != null}
        onOpenChange={(open) => {
          if (!open) setTranscribeConfirm(null);
        }}
        onConfirm={confirmTranscribe}
        isPending={transcribeRecording.isPending}
      />
    </Layout>
  );
}
