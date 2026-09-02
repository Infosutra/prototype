import React from "react";
import { Badge } from "@/components/ui/badge";
import { Loader2 } from "lucide-react";

export function formatDuration(seconds: number | null | undefined): string {
  if (!seconds || seconds <= 0) return "—";
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

/** Format seconds with centisecond precision when sub-second detail is available. */
export function formatDurationPrecise(seconds: number | null | undefined): string {
  if (seconds == null || seconds < 0) return "—";
  const mins = Math.floor(seconds / 60);
  const rem = seconds % 60;
  const wholeSecs = Math.floor(rem);
  const centis = Math.round((rem - wholeSecs) * 100);
  if (centis > 0) {
    return `${mins}:${wholeSecs.toString().padStart(2, "0")}.${centis.toString().padStart(2, "0")}`;
  }
  return `${mins}:${wholeSecs.toString().padStart(2, "0")}`;
}

export function formatTimeRange(startSeconds: number, endSeconds: number): string {
  return `${formatDurationPrecise(startSeconds)} – ${formatDurationPrecise(endSeconds)}`;
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString();
}

export const transcribeButtonClassName =
  "bg-primary text-primary-foreground hover:bg-primary/90 shadow-sm border-0";

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function speakerLabel(
  speakerId: string | null | undefined,
  labels?: Record<string, string> | null,
): string | null {
  if (speakerId == null || speakerId === "") return null;
  const custom = labels?.[speakerId]?.trim();
  if (custom) return custom;
  const numeric = Number(speakerId);
  if (Number.isFinite(numeric)) return `Speaker ${numeric + 1}`;
  return `Speaker ${speakerId}`;
}

export function uniqueSpeakerIds(
  segments: Array<{ speakerId?: string | null }>,
): string[] {
  const ids = new Set<string>();
  for (const segment of segments) {
    if (segment.speakerId != null && segment.speakerId !== "") {
      ids.add(segment.speakerId);
    }
  }
  return Array.from(ids).sort((left, right) => {
    const leftNum = Number(left);
    const rightNum = Number(right);
    if (Number.isFinite(leftNum) && Number.isFinite(rightNum)) {
      return leftNum - rightNum;
    }
    return left.localeCompare(right);
  });
}

export function isTranscriptionPending(status: string | undefined): boolean {
  return status === "queued" || status === "running";
}

export function requiresRetranscribeConfirmation(status: string | undefined): boolean {
  return status === "succeeded";
}

export function requiresFirstTranscribeConfirmation(status: string | undefined): boolean {
  return status === "none";
}

export function requiresTranscribeConfirmation(status: string | undefined): boolean {
  return requiresFirstTranscribeConfirmation(status) || requiresRetranscribeConfirmation(status);
}

export function formatTranscriptionCost(
  amount: number | null | undefined,
  currency: string | null | undefined,
): string {
  if (amount == null || amount <= 0) {
    return "no charge recorded";
  }
  return `${currency ?? "INR"} ${amount.toFixed(2)}`;
}

export type TranscriptionCostFields = {
  estimatedTranscriptionCostAmount?: number | null;
  estimatedTranscriptionCostCurrency?: string | null;
  estimatedTranscriptionDurationSeconds?: number | null;
  transcriptionRatePerMinute?: number | null;
  transcriptionCostAmount?: number | null;
  transcriptionCostCurrency?: string | null;
};

export function formatEstimatedTranscriptionCost(
  recording: TranscriptionCostFields | null | undefined,
): string {
  if (!recording) return "—";

  const amount = recording.estimatedTranscriptionCostAmount;
  const currency = recording.estimatedTranscriptionCostCurrency ?? "INR";
  const duration = recording.estimatedTranscriptionDurationSeconds;
  const rate = recording.transcriptionRatePerMinute;

  if (amount != null && amount > 0) {
    const durationPart =
      duration != null && duration > 0 ? ` (based on ${formatDuration(duration)} audio)` : "";
    return `${currency} ${amount.toFixed(2)}${durationPart}`;
  }

  if (rate != null && rate > 0) {
    return `${currency} ${rate.toFixed(2)} per minute (duration unknown)`;
  }

  return "no charge configured";
}

/** Index of the segment active at currentTime for linear (non-overlapping) layouts. */
export function getActiveSegmentIndexLinear(
  segments: Array<{ startSeconds: number; endSeconds?: number }>,
  currentTime: number,
): number {
  if (!segments.length) return -1;

  for (let i = 0; i < segments.length; i++) {
    const start = segments[i].startSeconds;
    const end = segments[i].endSeconds ?? start;
    if (currentTime >= start && currentTime < end) {
      return i;
    }
  }

  return -1;
}

/** Index of the segment active at currentTime for provider (overlapping) layouts. */
export function getActiveSegmentIndexProvider(
  segments: Array<{ startSeconds: number; endSeconds?: number }>,
  currentTime: number,
): number {
  if (!segments.length) return -1;

  let bestIndex = -1;
  let bestStart = -Infinity;

  for (let i = 0; i < segments.length; i++) {
    const start = segments[i].startSeconds;
    const end = segments[i].endSeconds ?? start;
    if (currentTime < start || currentTime >= end) {
      continue;
    }
    if (start >= bestStart) {
      bestStart = start;
      bestIndex = i;
    }
  }

  return bestIndex;
}

export function getActiveSegmentIndex(
  segments: Array<{ startSeconds: number; endSeconds?: number }>,
  currentTime: number,
  layout: "linear" | "provider" = "linear",
): number {
  if (layout === "provider") {
    return getActiveSegmentIndexProvider(segments, currentTime);
  }
  return getActiveSegmentIndexLinear(segments, currentTime);
}

export function StatusBadge({ status }: { status: string }) {
  switch (status) {
    case "succeeded":
      return <Badge className="bg-green-600">Transcribed</Badge>;
    case "running":
    case "queued":
      return (
        <Badge variant="secondary" className="gap-1">
          <Loader2 className="h-3 w-3 animate-spin" />
          {status === "queued" ? "Queued" : "Transcribing"}
        </Badge>
      );
    case "failed":
      return <Badge variant="destructive">Failed</Badge>;
    default:
      return <Badge variant="outline">Not transcribed</Badge>;
  }
}
