export type FormattedTranscriptionError = {
  message: string;
  detail: string | null;
};

const XML_ENTITY: Record<string, string> = {
  "&apos;": "'",
  "&quot;": '"',
  "&lt;": "<",
  "&gt;": ">",
  "&amp;": "&",
};

function decodeXmlEntities(value: string): string {
  return value.replace(/&apos;|&quot;|&lt;|&gt;|&amp;/g, (match) => XML_ENTITY[match] ?? match);
}

function xmlTag(xml: string, tag: string): string | null {
  const match = xml.match(new RegExp(`<${tag}>([\\s\\S]*?)</${tag}>`, "i"));
  return match ? decodeXmlEntities(match[1].trim()) : null;
}

function looksLikeXml(value: string): boolean {
  const trimmed = value.trimStart();
  return trimmed.startsWith("<?xml") || trimmed.includes("<Error>") || trimmed.includes("<Code>");
}

export function formatTranscriptionError(raw: string | null | undefined): FormattedTranscriptionError | null {
  if (!raw) return null;
  const text = raw.replace(/\uFEFF/g, "").trim();
  if (!text) return null;

  if (looksLikeXml(text) || text.includes("MissingRequiredHeader") || text.includes("x-ms-blob-type")) {
    const code = xmlTag(text, "Code");
    const header = xmlTag(text, "HeaderName");
    const azureMessage = xmlTag(text, "Message");
    const parts = [
      code ? `Azure ${code}` : "Azure Blob upload failed",
      header ? `missing header ${header}` : null,
    ].filter(Boolean);
    return {
      message: parts.join(": "),
      detail: azureMessage || text.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim(),
    };
  }

  return { message: text, detail: null };
}
