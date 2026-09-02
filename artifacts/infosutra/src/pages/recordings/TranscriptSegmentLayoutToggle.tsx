import React from "react";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  TRANSCRIPT_SEGMENT_LAYOUT_OPTIONS,
  type TranscriptSegmentLayout,
} from "@/lib/transcript-segment-layout";

type TranscriptSegmentLayoutToggleProps = {
  value: TranscriptSegmentLayout;
  onChange: (value: TranscriptSegmentLayout) => void;
  className?: string;
};

export function TranscriptSegmentLayoutToggle({
  value,
  onChange,
  className,
}: TranscriptSegmentLayoutToggleProps) {
  return (
    <div className={className}>
      <ToggleGroup
        type="single"
        variant="outline"
        size="sm"
        value={value}
        onValueChange={(next) => {
          if (next === "linear" || next === "provider") {
            onChange(next);
          }
        }}
        className="justify-start"
      >
        {TRANSCRIPT_SEGMENT_LAYOUT_OPTIONS.map((option) => (
          <ToggleGroupItem
            key={option.value}
            value={option.value}
            aria-label={option.label}
            className="text-xs px-2.5"
          >
            {option.label}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
      <p className="mt-1 text-[11px] leading-snug text-muted-foreground">
        {TRANSCRIPT_SEGMENT_LAYOUT_OPTIONS.find((option) => option.value === value)?.description}
      </p>
    </div>
  );
}
