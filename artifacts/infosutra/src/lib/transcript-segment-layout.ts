export type TranscriptSegmentLayout = "linear" | "provider";

export const DEFAULT_TRANSCRIPT_SEGMENT_LAYOUT: TranscriptSegmentLayout = "provider";

export const TRANSCRIPT_SEGMENT_LAYOUT_OPTIONS: Array<{
  value: TranscriptSegmentLayout;
  label: string;
  description: string;
}> = [
  {
    value: "provider",
    label: "Provider original",
    description: "Use Sarvam diarization blocks as returned",
  },
  {
    value: "linear",
    label: "Linear timeline",
    description: "Split overlapping turns for chronological playback",
  },
];
