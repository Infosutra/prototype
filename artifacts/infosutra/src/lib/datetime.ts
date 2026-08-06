/** Parse API datetimes (UTC-naive ISO strings are treated as UTC). */
export function parseUtcIso(value: string): Date | null {
  const trimmed = value.trim();
  if (!trimmed) return null;

  const hasOffset = /[zZ]$/.test(trimmed) || /[+-]\d{2}:\d{2}$/.test(trimmed);
  const parsed = new Date(hasOffset ? trimmed : `${trimmed}Z`);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

/** Match DQA report headers, e.g. "6 Aug 2026, 12:45 IST". */
export function formatReportDatetime(
  value: string | null | undefined,
  tzName = "Asia/Kolkata",
): string {
  if (!value) return "—";
  const parsed = parseUtcIso(value);
  if (!parsed) return value;

  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-GB", {
      timeZone: tzName,
      day: "numeric",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    })
      .formatToParts(parsed)
      .map((part) => [part.type, part.value]),
  );

  const zoneLabel =
    tzName === "Asia/Kolkata" || tzName === "Asia/Calcutta" ? "IST" : tzName;

  return `${parts.day} ${parts.month} ${parts.year}, ${parts.hour}:${parts.minute} ${zoneLabel}`;
}
