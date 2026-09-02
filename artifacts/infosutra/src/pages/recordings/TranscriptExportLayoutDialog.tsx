import React, { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import {
  DEFAULT_TRANSCRIPT_SEGMENT_LAYOUT,
  TRANSCRIPT_SEGMENT_LAYOUT_OPTIONS,
  type TranscriptSegmentLayout,
} from "@/lib/transcript-segment-layout";
import { cn } from "@/lib/utils";

type TranscriptExportLayoutDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  format: "pdf" | "docx" | null;
  onConfirm: (layout: TranscriptSegmentLayout) => void;
};

export function TranscriptExportLayoutDialog({
  open,
  onOpenChange,
  format,
  onConfirm,
}: TranscriptExportLayoutDialogProps) {
  const [layout, setLayout] = useState<TranscriptSegmentLayout>(
    DEFAULT_TRANSCRIPT_SEGMENT_LAYOUT,
  );

  useEffect(() => {
    if (open) {
      setLayout(DEFAULT_TRANSCRIPT_SEGMENT_LAYOUT);
    }
  }, [open, format]);

  const formatLabel = format === "docx" ? "DOCX" : "PDF";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="sm:max-w-md"
        onPointerDownOutside={(event) => {
          event.preventDefault();
          onOpenChange(false);
        }}
      >
        <DialogHeader>
          <DialogTitle>Choose transcript layout</DialogTitle>
          <DialogDescription>
            Select how speaker turns should appear in your {formatLabel} export.
          </DialogDescription>
        </DialogHeader>

        <RadioGroup
          value={layout}
          onValueChange={(value) => {
            if (value === "linear" || value === "provider") {
              setLayout(value);
            }
          }}
          className="gap-2"
        >
          {TRANSCRIPT_SEGMENT_LAYOUT_OPTIONS.map((option) => (
            <Label
              key={option.value}
              htmlFor={`export-layout-${option.value}`}
              className={cn(
                "flex cursor-pointer items-start gap-3 rounded-md border p-3 transition-colors",
                layout === option.value
                  ? "border-primary bg-primary/5"
                  : "border-border hover:bg-muted/40",
              )}
            >
              <RadioGroupItem
                id={`export-layout-${option.value}`}
                value={option.value}
                className="mt-0.5"
              />
              <div className="space-y-1">
                <p className="text-sm font-medium leading-none">{option.label}</p>
                <p className="text-xs text-muted-foreground leading-snug">
                  {option.description}
                </p>
              </div>
            </Label>
          ))}
        </RadioGroup>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={(event) => {
              event.stopPropagation();
              onOpenChange(false);
            }}
          >
            Cancel
          </Button>
          <Button
            onClick={() => {
              onConfirm(layout);
              onOpenChange(false);
            }}
          >
            Download {formatLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
