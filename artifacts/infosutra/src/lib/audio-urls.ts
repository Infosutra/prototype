export function audioFileUrl(id: string): string {
  return `/api/audio/${encodeURIComponent(id)}/file`;
}
