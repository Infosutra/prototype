import React from "react";
import type { AudioRecordingOut } from "@workspace/api-client-react";
import {
  formatBytes,
  formatDateTime,
  formatDuration,
  formatTranscriptionCost,
} from "@/pages/recordings/recording-ui";

type RecordingInsightsPanelProps = {
  recording: AudioRecordingOut;
  segmentCount: number;
  speakerCount: number;
  wordCount: number;
};

function InsightRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2 border-b last:border-b-0">
      <dt className="text-xs text-muted-foreground shrink-0">{label}</dt>
      <dd className="text-sm text-right font-medium break-words">{value}</dd>
    </div>
  );
}

function statusLabel(status: string): string {
  switch (status) {
    case "succeeded":
      return "Transcribed";
    case "failed":
      return "Failed";
    case "running":
      return "Transcribing";
    case "queued":
      return "Queued";
    default:
      return "Not transcribed";
  }
}

export function countWords(text: string | null | undefined): number {
  if (!text?.trim()) return 0;
  return text.trim().split(/\s+/).length;
}

export function RecordingInsightsPanel({
  recording,
  segmentCount,
  speakerCount,
  wordCount,
}: RecordingInsightsPanelProps) {
  return (
    <div className="space-y-3">
      <div className="rounded-lg border bg-card p-3 shadow-sm">
        <h3 className="text-sm font-semibold mb-2">Recording details</h3>
        <dl>
          <InsightRow label="Status" value={statusLabel(recording.transcriptionStatus)} />
          <InsightRow label="File" value={recording.originalFilename} />
          <InsightRow label="Size" value={formatBytes(recording.sizeBytes)} />
          <InsightRow
            label="Duration"
            value={recording.durationSeconds ? formatDuration(recording.durationSeconds) : "—"}
          />
          <InsightRow label="Uploaded" value={formatDateTime(recording.createdAt)} />
        </dl>
      </div>

      <div className="rounded-lg border bg-card p-3 shadow-sm">
        <h3 className="text-sm font-semibold mb-2">Transcription</h3>
        <dl>
          <InsightRow
            label="Provider"
            value={
              recording.transcriptionProvider
                ? recording.transcriptionProvider.toUpperCase()
                : "—"
            }
          />
          <InsightRow label="Model" value={recording.transcriptionModel ?? "—"} />
          <InsightRow label="Language" value={recording.transcriptionLanguage ?? "—"} />
          <InsightRow label="Transcribed" value={formatDateTime(recording.transcribedAt)} />
          <InsightRow
            label="Cost"
            value={formatTranscriptionCost(
              recording.transcriptionCostAmount,
              recording.transcriptionCostCurrency,
            )}
          />
        </dl>
      </div>

      <div className="rounded-lg border bg-card p-3 shadow-sm">
        <h3 className="text-sm font-semibold mb-2">Transcript stats</h3>
        <dl>
          <InsightRow label="Segments" value={segmentCount} />
          <InsightRow label="Speakers" value={speakerCount} />
          <InsightRow label="Words" value={wordCount.toLocaleString()} />
        </dl>
      </div>
    </div>
  );
}
