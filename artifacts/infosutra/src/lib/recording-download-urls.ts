import { DEFAULT_TRANSCRIPT_SEGMENT_LAYOUT } from "@/lib/transcript-segment-layout";

export function recordingTranscriptDownloadUrl(
  id: string,
  format: "pdf" | "docx" = "pdf",
  segmentLayout: "linear" | "provider" = DEFAULT_TRANSCRIPT_SEGMENT_LAYOUT,
): string {
  const params = new URLSearchParams({ format, segmentLayout });
  return `/api/audio/${encodeURIComponent(id)}/download?${params.toString()}`;
}
