export function reportPreviewUrl(id: string): string {
  return `/api/reports/${encodeURIComponent(id)}/preview`;
}

export function reportDownloadUrl(id: string, format: "pdf" | "docx" = "pdf"): string {
  return `/api/reports/${encodeURIComponent(id)}/download?format=${format}`;
}
