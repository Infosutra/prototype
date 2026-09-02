import { useCallback, useEffect, useState } from "react";
import { audioFileUrl } from "@/lib/audio-urls";

async function playbackErrorMessage(url: string): Promise<string> {
  try {
    const response = await fetch(url, { method: "HEAD" });
    if (response.status === 404) {
      const detailResponse = await fetch(url);
      try {
        const payload = (await detailResponse.json()) as { detail?: string };
        if (payload.detail) return payload.detail;
      } catch {
        // ignore non-JSON bodies
      }
      return "Audio file is missing on the server. Re-sync with ./scripts/sync-to-rpi.sh --with-db.";
    }
    if (!response.ok) {
      return `Audio could not be loaded (HTTP ${response.status}).`;
    }
  } catch {
    // HEAD may be blocked; fall through to generic message.
  }
  return "Audio could not be played. The file may be missing or in an unsupported format.";
}

/** Native <audio> src with a helpful message when the browser cannot decode the stream. */
export function usePlayableAudioSrc(recordingId: string) {
  const src = recordingId ? audioFileUrl(recordingId) : "";
  const [playbackError, setPlaybackError] = useState<string | null>(null);

  useEffect(() => {
    setPlaybackError(null);
  }, [recordingId]);

  const onError = useCallback(() => {
    if (!src) return;
    void playbackErrorMessage(src).then(setPlaybackError);
  }, [src]);

  return { src, playbackError, onError };
}
