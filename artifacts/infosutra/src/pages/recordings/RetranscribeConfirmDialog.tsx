import React from "react";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  formatEstimatedTranscriptionCost,
  formatTranscriptionCost,
  type TranscriptionCostFields,
} from "@/pages/recordings/recording-ui";

export type TranscribeConfirmMode = "first" | "retry";

type TranscribeConfirmRecording = TranscriptionCostFields & {
  name: string;
  transcriptionStatus: string;
};

type TranscribeConfirmDialogProps = {
  recording: TranscribeConfirmRecording | null;
  mode: TranscribeConfirmMode | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
  isPending?: boolean;
};

/** @deprecated Use TranscribeConfirmDialog */
export const RetranscribeConfirmDialog = TranscribeConfirmDialog;

export function TranscribeConfirmDialog({
  recording,
  mode,
  open,
  onOpenChange,
  onConfirm,
  isPending = false,
}: TranscribeConfirmDialogProps) {
  const isFirst = mode === "first";
  const costLabel = isFirst
    ? formatEstimatedTranscriptionCost(recording)
    : formatTranscriptionCost(
        recording?.transcriptionCostAmount,
        recording?.transcriptionCostCurrency,
      );

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>
            {isFirst ? "Start transcription?" : "Transcribe again?"}
          </AlertDialogTitle>
          <AlertDialogDescription asChild>
            <div className="space-y-2 text-sm text-muted-foreground">
              {isFirst ? (
                <p>
                  Transcribe{" "}
                  <span className="font-medium text-foreground">{recording?.name}</span>? This
                  will send the audio to your configured transcription provider.
                </p>
              ) : (
                <p>
                  <span className="font-medium text-foreground">{recording?.name}</span> has
                  already been transcribed. Running transcription again will replace the current
                  transcript.
                </p>
              )}
              <p>
                Estimated charge:{" "}
                <span className="font-medium text-foreground">{costLabel}</span>
              </p>
              <p>Do you want to continue?</p>
            </div>
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={isPending}>No</AlertDialogCancel>
          <AlertDialogAction disabled={isPending} onClick={onConfirm}>
            {isPending ? "Starting…" : "Yes, transcribe"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
