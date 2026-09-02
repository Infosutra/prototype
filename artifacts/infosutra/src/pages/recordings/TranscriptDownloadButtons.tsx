import React, { useState } from "react";
import { Button } from "@/components/ui/button";
import { recordingTranscriptDownloadUrl } from "@/lib/recording-download-urls";
import type { TranscriptSegmentLayout } from "@/lib/transcript-segment-layout";
import { TranscriptExportLayoutDialog } from "@/pages/recordings/TranscriptExportLayoutDialog";
import { Download } from "lucide-react";

type TranscriptDownloadButtonsProps = {
  recordingId: string;
  size?: "sm" | "default";
  className?: string;
  onClick?: (event: React.MouseEvent) => void;
};

function triggerDownload(url: string) {
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "";
  anchor.click();
}

export function TranscriptDownloadButtons({
  recordingId,
  size = "sm",
  className,
  onClick,
}: TranscriptDownloadButtonsProps) {
  const [exportFormat, setExportFormat] = useState<"pdf" | "docx" | null>(null);

  const openExportDialog = (
    format: "pdf" | "docx",
    event: React.MouseEvent<HTMLButtonElement>,
  ) => {
    event.preventDefault();
    event.stopPropagation();
    onClick?.(event);
    setExportFormat(format);
  };

  const handleExportConfirm = (layout: TranscriptSegmentLayout) => {
    if (!exportFormat) return;
    triggerDownload(recordingTranscriptDownloadUrl(recordingId, exportFormat, layout));
    setExportFormat(null);
  };

  return (
    <>
      <div
        className={className ?? "flex gap-2"}
        onClick={(event) => event.stopPropagation()}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <Button
          variant="outline"
          size={size}
          onClick={(event) => openExportDialog("pdf", event)}
        >
          <Download className="h-3.5 w-3.5 mr-1.5" />
          PDF
        </Button>
        <Button
          variant="outline"
          size={size}
          onClick={(event) => openExportDialog("docx", event)}
        >
          <Download className="h-3.5 w-3.5 mr-1.5" />
          DOCX
        </Button>
      </div>

      <TranscriptExportLayoutDialog
        open={exportFormat != null}
        onOpenChange={(open) => {
          if (!open) setExportFormat(null);
        }}
        format={exportFormat}
        onConfirm={handleExportConfirm}
      />
    </>
  );
}
