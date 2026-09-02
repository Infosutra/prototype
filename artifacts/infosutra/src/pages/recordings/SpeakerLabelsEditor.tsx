import React, { useEffect, useState } from "react";
import {
  getGetAudioRecordingQueryKey,
  useUpdateAudioRecordingSpeakerLabels,
} from "@workspace/api-client-react";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import { speakerLabel } from "@/pages/recordings/recording-ui";
import { ChevronDown } from "lucide-react";

type SpeakerLabelsEditorProps = {
  recordingId: string;
  speakerIds: string[];
  labels: Record<string, string>;
  className?: string;
};

export function SpeakerLabelsEditor({
  recordingId,
  speakerIds,
  labels,
  className,
}: SpeakerLabelsEditorProps) {
  const queryClient = useQueryClient();
  const updateLabels = useUpdateAudioRecordingSpeakerLabels();
  const [draft, setDraft] = useState<Record<string, string>>(labels);
  const [savedMessage, setSavedMessage] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    setDraft(labels);
  }, [labels]);

  if (speakerIds.length === 0) return null;

  const hasChanges = speakerIds.some(
    (speakerId) => (draft[speakerId] ?? "").trim() !== (labels[speakerId] ?? "").trim(),
  );
  const namedCount = speakerIds.filter((speakerId) => labels[speakerId]?.trim()).length;

  const save = async () => {
    setSavedMessage(null);
    const payload = Object.fromEntries(
      speakerIds.map((speakerId) => [speakerId, (draft[speakerId] ?? "").trim()]),
    );
    try {
      const updated = await updateLabels.mutateAsync({
        recordingId,
        data: { labels: payload },
      });
      queryClient.setQueryData(getGetAudioRecordingQueryKey(recordingId), updated);
      setSavedMessage("Speaker names saved");
    } catch {
      setSavedMessage("Could not save speaker names");
    }
  };

  return (
    <Collapsible
      open={open}
      onOpenChange={setOpen}
      className={cn("rounded-md border bg-card shadow-sm overflow-hidden", className)}
    >
      <CollapsibleTrigger className="group flex w-full items-center justify-between gap-3 px-3 py-2.5 text-left hover:bg-muted/50 transition-colors">
        <div className="min-w-0">
          <p className="text-sm font-medium">Speaker names</p>
          <p className="text-xs text-muted-foreground truncate">
            {speakerIds.length} speaker{speakerIds.length === 1 ? "" : "s"}
            {namedCount > 0 ? ` · ${namedCount} named` : ""}
            {hasChanges ? " · unsaved changes" : ""}
          </p>
        </div>
        <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-data-[state=open]:rotate-180" />
      </CollapsibleTrigger>
      <CollapsibleContent className="px-3 pb-3 space-y-3">
        <p className="text-xs text-muted-foreground">
          Assign names to diarized speakers. These are saved with the recording.
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          {speakerIds.map((speakerId) => (
            <div key={speakerId} className="space-y-1.5">
              <Label htmlFor={`speaker-${speakerId}`} className="text-xs text-muted-foreground">
                {speakerLabel(speakerId)}
              </Label>
              <Input
                id={`speaker-${speakerId}`}
                value={draft[speakerId] ?? ""}
                placeholder={speakerLabel(speakerId) ?? "Speaker"}
                onChange={(event) =>
                  setDraft((current) => ({ ...current, [speakerId]: event.target.value }))
                }
              />
            </div>
          ))}
        </div>
        <div className="flex items-center gap-3">
          <Button
            size="sm"
            variant="secondary"
            disabled={!hasChanges || updateLabels.isPending}
            onClick={() => void save()}
          >
            {updateLabels.isPending ? "Saving…" : "Save names"}
          </Button>
          {savedMessage && <span className="text-xs text-muted-foreground">{savedMessage}</span>}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
