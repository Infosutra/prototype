import React, { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useParams } from "wouter";
import {
  getGetAudioRecordingQueryKey,
  getGetAudioRecordingQueryOptions,
  getGetAudioRecordingsQueryKey,
  useDeleteAudioRecording,
  useGetAudioRecording,
  useTranscribeAudioRecording,
} from "@workspace/api-client-react";
import { useQueryClient } from "@tanstack/react-query";
import { Layout } from "@/components/layout/Layout";
import { Header } from "@/components/layout/Header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { usePlayableAudioSrc } from "@/lib/use-playable-audio-src";
import { formatTranscriptionError } from "@/lib/transcription-error";
import {
  DEFAULT_TRANSCRIPT_SEGMENT_LAYOUT,
  type TranscriptSegmentLayout,
} from "@/lib/transcript-segment-layout";
import { cn } from "@/lib/utils";
import {
  countWords,
  RecordingInsightsPanel,
} from "@/pages/recordings/RecordingInsightsPanel";
import {
  TranscribeConfirmDialog,
  type TranscribeConfirmMode,
} from "@/pages/recordings/RetranscribeConfirmDialog";
import {
  formatTimeRange,
  getActiveSegmentIndex,
  isTranscriptionPending,
  requiresFirstTranscribeConfirmation,
  requiresRetranscribeConfirmation,
  speakerLabel,
  StatusBadge,
  transcribeButtonClassName,
  uniqueSpeakerIds,
} from "@/pages/recordings/recording-ui";
import { SpeakerLabelsEditor } from "@/pages/recordings/SpeakerLabelsEditor";
import { TranscriptDownloadButtons } from "@/pages/recordings/TranscriptDownloadButtons";
import { TranscriptSegmentLayoutToggle } from "@/pages/recordings/TranscriptSegmentLayoutToggle";
import { useTranscriptBatchScroll } from "@/pages/recordings/use-transcript-batch-scroll";
import { AlertCircle, ArrowLeft, Loader2, Sparkles, Trash2 } from "lucide-react";

export default function RecordingDetail() {
  const params = useParams<{ id: string }>();
  const recordingId = params.id ?? "";
  const [, setLocation] = useLocation();
  const queryClient = useQueryClient();
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [pollDetail, setPollDetail] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [segmentLayout, setSegmentLayout] = useState<TranscriptSegmentLayout>(
    DEFAULT_TRANSCRIPT_SEGMENT_LAYOUT,
  );
  const [transcribeConfirm, setTranscribeConfirm] = useState<{
    mode: TranscribeConfirmMode;
  } | null>(null);

  useEffect(() => {
    setSegmentLayout(DEFAULT_TRANSCRIPT_SEGMENT_LAYOUT);
  }, [recordingId]);

  const detailQuery = useGetAudioRecording(
    recordingId,
    { segmentLayout },
    {
      query: {
        enabled: Boolean(recordingId),
        staleTime: 0,
        refetchOnMount: "always",
        refetchInterval: pollDetail ? 3000 : false,
      } as never,
    },
  );

  const recording = detailQuery.data;
  const playableAudio = usePlayableAudioSrc(recording?.id ?? "");

  useEffect(() => {
    if (!recordingId) return;
    const alternateLayout: TranscriptSegmentLayout =
      segmentLayout === "linear" ? "provider" : "linear";
    void queryClient.prefetchQuery(
      getGetAudioRecordingQueryOptions(recordingId, { segmentLayout: alternateLayout }),
    );
  }, [recordingId, segmentLayout, queryClient]);

  useEffect(() => {
    setPollDetail(isTranscriptionPending(recording?.transcriptionStatus));
  }, [recording?.transcriptionStatus]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;

    let frameId = 0;
    const syncTime = () => setCurrentTime(audio.currentTime);
    const tick = () => {
      syncTime();
      if (!audio.paused) {
        frameId = requestAnimationFrame(tick);
      }
    };
    const onPlay = () => {
      cancelAnimationFrame(frameId);
      frameId = requestAnimationFrame(tick);
    };
    const onPause = () => {
      cancelAnimationFrame(frameId);
      syncTime();
    };

    audio.addEventListener("play", onPlay);
    audio.addEventListener("pause", onPause);
    audio.addEventListener("ended", onPause);
    audio.addEventListener("seeked", syncTime);
    if (!audio.paused) {
      onPlay();
    }

    return () => {
      cancelAnimationFrame(frameId);
      audio.removeEventListener("play", onPlay);
      audio.removeEventListener("pause", onPause);
      audio.removeEventListener("ended", onPause);
      audio.removeEventListener("seeked", syncTime);
    };
  }, [recording?.id]);

  const deleteRecording = useDeleteAudioRecording();
  const transcribeRecording = useTranscribeAudioRecording();

  const segments = useMemo(() => {
    const raw = recording?.transcript?.segments ?? [];
    if (segmentLayout === "provider") {
      return raw;
    }
    return [...raw].sort((left, right) => {
      if (left.startSeconds !== right.startSeconds) {
        return left.startSeconds - right.startSeconds;
      }
      return left.endSeconds - right.endSeconds;
    });
  }, [recording?.transcript?.segments, segmentLayout]);
  const speakerLabels = recording?.transcript?.speakerLabels ?? {};
  const speakerIds = useMemo(() => uniqueSpeakerIds(segments), [segments]);
  const activeSegmentIndex = useMemo(
    () => getActiveSegmentIndex(segments, currentTime, segmentLayout),
    [segments, currentTime, segmentLayout],
  );
  const {
    containerRef: transcriptContainerRef,
    segmentRefs,
    resetScrollState,
    scrollSegmentToTop,
  } = useTranscriptBatchScroll(activeSegmentIndex, segments.length);

  const handleSegmentLayoutChange = (nextLayout: TranscriptSegmentLayout) => {
    setSegmentLayout(nextLayout);
    resetScrollState();
  };
  const wordCount = useMemo(
    () => countWords(recording?.transcript?.fullText),
    [recording?.transcript?.fullText],
  );

  const seekTo = (seconds: number) => {
    const el = audioRef.current;
    if (!el) return;
    el.currentTime = seconds;
    setCurrentTime(seconds);
    resetScrollState();
    if (el.paused) void el.play();

    const index = getActiveSegmentIndex(segments, seconds, segmentLayout);
    if (index < 0) return;
    requestAnimationFrame(() => scrollSegmentToTop(index));
  };

  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: getGetAudioRecordingQueryKey(recordingId) });
    await queryClient.invalidateQueries({ queryKey: getGetAudioRecordingsQueryKey() });
  };

  const transcribe = async () => {
    setActionError(null);
    try {
      const updated = await transcribeRecording.mutateAsync({ recordingId, data: {} });
      queryClient.setQueryData(getGetAudioRecordingQueryKey(recordingId), updated);
      await invalidate();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Transcription failed to start");
    }
  };

  const requestTranscribe = () => {
    if (!recording) return;
    if (requiresFirstTranscribeConfirmation(recording.transcriptionStatus)) {
      setTranscribeConfirm({ mode: "first" });
      return;
    }
    if (requiresRetranscribeConfirmation(recording.transcriptionStatus)) {
      setTranscribeConfirm({ mode: "retry" });
      return;
    }
    void transcribe();
  };

  const confirmTranscribe = () => {
    void transcribe().finally(() => setTranscribeConfirm(null));
  };

  const remove = async () => {
    if (!recording) return;
    if (!confirm(`Delete recording “${recording.name}”?`)) return;
    try {
      await deleteRecording.mutateAsync({ recordingId });
      await queryClient.invalidateQueries({ queryKey: getGetAudioRecordingsQueryKey() });
      setLocation("/recordings");
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Delete failed");
    }
  };

  const formattedError = formatTranscriptionError(recording?.transcriptionError);
  const pending = isTranscriptionPending(recording?.transcriptionStatus);

  return (
    <Layout>
      <Header
        title={recording?.name ?? "Recording"}
        description={recording?.description || recording?.originalFilename}
        action={
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="outline" asChild>
              <Link href="/recordings">
                <ArrowLeft className="h-4 w-4 mr-1.5" />
                All recordings
              </Link>
            </Button>
            {recording && (
              <>
                {recording.transcriptionStatus === "succeeded" && (
                  <TranscriptDownloadButtons recordingId={recording.id} />
                )}
                <Button
                  size="sm"
                  className={transcribeButtonClassName}
                  disabled={pending || transcribeRecording.isPending}
                  onClick={requestTranscribe}
                >
                  <Sparkles className="h-4 w-4 mr-1.5" />
                  {recording.transcriptionStatus === "failed" ? "Retry" : "Transcribe"}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="text-destructive hover:bg-destructive/10"
                  disabled={deleteRecording.isPending}
                  onClick={() => void remove()}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </>
            )}
          </div>
        }
      />
      {recording && (
        <div className="shrink-0 border-b border-border bg-muted/30 px-4 pt-2 pb-2 md:px-6">
          <div className="mx-auto max-w-7xl">
            <Card className="shadow-sm">
              <CardHeader className="py-2.5 px-4">
                <div className="flex flex-wrap items-center gap-2">
                  <CardTitle className="text-sm">Playback</CardTitle>
                  <StatusBadge status={recording.transcriptionStatus} />
                </div>
              </CardHeader>
              <CardContent className="px-4 pb-3 pt-0">
                <audio
                  ref={audioRef}
                  controls
                  preload="metadata"
                  src={playableAudio.src || undefined}
                  onError={playableAudio.onError}
                  className="w-full h-9"
                />
                {playableAudio.playbackError && (
                  <p className="mt-1.5 text-xs text-destructive">{playableAudio.playbackError}</p>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      )}
      <div className="flex-1 overflow-auto px-4 py-2 md:px-6 md:py-3 bg-muted/30 min-h-0">
        {detailQuery.isLoading && (
          <p className="text-sm text-muted-foreground">Loading recording…</p>
        )}
        {detailQuery.error && (
          <div className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
            <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
            {detailQuery.error.message}
          </div>
        )}
        {actionError && (
          <div className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
            <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
            {actionError}
          </div>
        )}

        {recording && (
          <div className="mx-auto max-w-7xl grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_300px] gap-3 items-start h-full">
            <div className="min-w-0 flex flex-col min-h-0">
              {recording.transcriptionStatus === "failed" && formattedError && (
                <div className="mb-3 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive space-y-2">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-start gap-2 min-w-0">
                      <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
                      <div className="min-w-0">
                        <p>{formattedError.message}</p>
                        {formattedError.detail && (
                          <p className="mt-1 text-xs text-destructive/80 whitespace-pre-wrap break-words">
                            {formattedError.detail}
                          </p>
                        )}
                      </div>
                    </div>
                    <Button
                      size="sm"
                      className={transcribeButtonClassName}
                      disabled={transcribeRecording.isPending}
                      onClick={requestTranscribe}
                    >
                      Retry
                    </Button>
                  </div>
                </div>
              )}

              <Card className="flex flex-col min-h-0 shadow-sm">
                <CardHeader className="py-2.5 px-4">
                  <CardTitle className="text-sm">Transcript</CardTitle>
                </CardHeader>
                <CardContent className="flex flex-col flex-1 min-h-0 px-4 pb-3 pt-0">
                  {!pending && segments.length > 0 && recording.transcriptionStatus === "succeeded" && (
                    <div className="sticky top-0 z-10 -mx-4 bg-card px-4 pb-2 border-b border-border/60">
                      <TranscriptSegmentLayoutToggle
                        value={segmentLayout}
                        onChange={handleSegmentLayoutChange}
                      />
                    </div>
                  )}
                  {pending && (
                    <p className="text-sm text-muted-foreground flex items-center gap-2">
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Transcription in progress…
                    </p>
                  )}
                  {!pending && segments.length > 0 && (
                      <div
                        ref={transcriptContainerRef}
                        className="flex-1 min-h-0 overflow-y-auto space-y-1.5 pr-1 pt-2 max-h-[calc(100dvh-12.5rem)]"
                      >
                        {segments.map((seg, idx) => (
                          <button
                            key={`${seg.startSeconds}-${idx}`}
                            ref={(el) => {
                              segmentRefs.current[idx] = el;
                            }}
                            type="button"
                            onClick={() => seekTo(seg.startSeconds)}
                            className={cn(
                              "w-full text-left rounded-md px-2.5 py-2 text-sm transition-colors border-l-4",
                              idx === activeSegmentIndex
                                ? "bg-primary/25 text-foreground border-primary shadow-sm ring-1 ring-primary/50"
                                : "border-transparent hover:bg-muted/60 text-foreground/90",
                            )}
                          >
                            <div className="text-xs text-muted-foreground font-mono mb-0.5">
                              {formatTimeRange(seg.startSeconds, seg.endSeconds)}
                              {speakerLabel(seg.speakerId, speakerLabels)
                                ? ` · ${speakerLabel(seg.speakerId, speakerLabels)}`
                                : ""}
                            </div>
                            {seg.text}
                          </button>
                        ))}
                      </div>
                  )}
                  {!pending &&
                    recording.transcriptionStatus === "succeeded" &&
                    segments.length === 0 && (
                      <p className="text-sm text-muted-foreground">
                        No transcript segments returned.
                      </p>
                    )}
                  {!pending &&
                    recording.transcriptionStatus !== "succeeded" &&
                    recording.transcriptionStatus !== "failed" && (
                      <p className="text-sm text-muted-foreground">
                        Transcript will appear here after transcription completes.
                      </p>
                    )}
                </CardContent>
              </Card>
            </div>

            <aside className="xl:sticky xl:top-2 space-y-3">
              {!pending && speakerIds.length > 0 && (
                <SpeakerLabelsEditor
                  recordingId={recording.id}
                  speakerIds={speakerIds}
                  labels={speakerLabels}
                />
              )}
              <RecordingInsightsPanel
                recording={recording}
                segmentCount={segments.length}
                speakerCount={speakerIds.length}
                wordCount={wordCount}
              />
            </aside>
          </div>
        )}
      </div>

      <TranscribeConfirmDialog
        recording={recording ?? null}
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
