import React, { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "wouter";
import {
  useGetProjectDataGrid,
  type GridCell,
  type GridColumn,
  type GridFlagRef,
  type GridRow,
  type SubmissionGrid,
} from "@workspace/api-client-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { cn } from "@/lib/utils";
import { ChevronLeft, ChevronRight, Download, Eye } from "lucide-react";

const PAGE_SIZES = [25, 50, 100, 200];

const INSTRUMENT_CODES = new Set([
  "today",
  "deviceid",
  "username",
  "start",
  "end",
  "audit",
  "phonenumber",
  "simserial",
  "subscriberid",
  "imei",
]);

const INSTRUMENT_TYPES = new Set([
  "today",
  "deviceid",
  "username",
  "start",
  "end",
  "audit",
  "phonenumber",
  "simserial",
  "subscriberid",
  "imei",
]);

const PIN_DISTRICT_CODES = ["district", "District"];
const CENTRE_CODES = ["centre_code", "center_code", "centre", "center"];

type SeverityFilter = "" | "flagged" | "red" | "amber" | "clean";
type ColumnMode = "review" | "all";
type SectionId = "flagged" | string;

type CellDetail = {
  row: GridRow;
  columnLabel: string;
  columnCode: string;
  columnKey: string | null;
  value: string;
  flags: GridFlagRef[];
  formLevel?: boolean;
};

function isInstrumentColumn(column: GridColumn): boolean {
  const code = (column.code || column.key || "").toLowerCase();
  const type = (column.type || "").toLowerCase();
  if (INSTRUMENT_CODES.has(code) || INSTRUMENT_TYPES.has(type)) return true;
  if (column.extra && (column.flagged ?? 0) === 0) return true;
  return false;
}

function findColumnByCodes(columns: GridColumn[], codes: string[]): GridColumn | undefined {
  const lower = codes.map((c) => c.toLowerCase());
  return columns.find((column) => lower.includes((column.code || column.key).toLowerCase()));
}

function cellValue(row: GridRow, column?: GridColumn): string {
  if (!column) return "";
  return row.cells?.[column.key]?.value ?? "";
}

function formatDateTime(value?: string): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString(undefined, {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatCellDisplay(value: string): string {
  if (!value) return "";
  // ISO datetime with offset
  if (/^\d{4}-\d{2}-\d{2}T/.test(value)) {
    return formatDateTime(value);
  }
  // Time with fractional seconds / offset e.g. 08:30:00.000+05:30
  const timeMatch = value.match(/^(\d{1,2}):(\d{2})(?::\d{2}(?:\.\d+)?)?(?:[+-]\d{2}:\d{2}|Z)?$/);
  if (timeMatch) {
    return `${timeMatch[1].padStart(2, "0")}:${timeMatch[2]}`;
  }
  return value;
}

function csvEscape(value: string): string {
  return /[",\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
}

function downloadCsv(fileName: string, columns: GridColumn[], rows: GridRow[]) {
  const header = [
    "Submission",
    "Submitted",
    "Enumerator",
    "Status",
    "DQA",
    ...columns.map((column) => `${column.code} — ${column.label}`),
  ];
  const lines = [header.map(csvEscape).join(",")];
  for (const row of rows) {
    const flags = [
      ...(row.rowFlags ?? []),
      ...columns.flatMap((c) => row.cells?.[c.key]?.flags ?? []),
    ];
    const ruleIds = [...new Set(flags.map((flag) => `${flag.ruleId}(${flag.severity})`))];
    lines.push(
      [
        row.displayId,
        row.submittedAt ?? "",
        row.enumerator ?? "",
        row.status ?? "",
        ruleIds.join(" "),
        ...columns.map((column) => row.cells?.[column.key]?.value ?? ""),
      ]
        .map((value) => csvEscape(String(value ?? "")))
        .join(","),
    );
  }
  const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  link.click();
  URL.revokeObjectURL(url);
}

function SeverityPip({ severity }: { severity?: string | null }) {
  return (
    <span
      className={cn(
        "mt-1.5 inline-block h-2 w-2 shrink-0 rounded-full",
        severity === "red" && "bg-red-500",
        severity === "amber" && "bg-amber-500",
        severity !== "red" && severity !== "amber" && "bg-muted-foreground/30",
      )}
      aria-hidden
    />
  );
}

function severityBarClass(severity?: string | null): string {
  if (severity === "red") return "border-l-[3px] border-l-red-500 bg-red-50 dark:bg-red-950/40";
  if (severity === "amber") {
    return "border-l-[3px] border-l-amber-500 bg-amber-50 dark:bg-amber-950/40";
  }
  return "border-l-[3px] border-l-transparent";
}

function FlagList({ projectId, flags }: { projectId: string; flags: GridFlagRef[] }) {
  return (
    <ul className="space-y-3">
      {flags.map((flag) => (
        <li key={`${flag.id}-${flag.ruleId}`} className="space-y-1">
          <div className="flex items-start gap-2">
            <SeverityPip severity={flag.severity} />
            <div className="min-w-0">
              <p className="text-sm font-semibold leading-snug">{flag.title}</p>
              <p className="mt-1 text-sm text-muted-foreground">{flag.message}</p>
              <Link
                href={`/dqa?projectId=${encodeURIComponent(projectId)}&ruleId=${encodeURIComponent(flag.ruleId)}`}
                className="mt-2 inline-block text-xs text-primary underline"
              >
                All forms flagged by {flag.ruleId} →
              </Link>
            </div>
          </div>
        </li>
      ))}
    </ul>
  );
}

function relatedAnswers(
  row: GridRow,
  columns: GridColumn[],
  flags: GridFlagRef[],
  excludeKey?: string | null,
): { code: string; label: string; value: string }[] {
  const ruleIds = new Set(flags.map((flag) => flag.ruleId));
  if (ruleIds.size === 0) return [];
  const found: { code: string; label: string; value: string }[] = [];
  for (const column of columns) {
    if (excludeKey && column.key === excludeKey) continue;
    const cell = row.cells?.[column.key];
    const shares = (cell?.flags ?? []).some((flag) => ruleIds.has(flag.ruleId));
    if (!shares) continue;
    found.push({
      code: column.code,
      label: column.label,
      value: formatCellDisplay(cell?.value ?? "") || "Blank",
    });
  }
  return found;
}

export function SubmissionsGrid({ projectId }: { projectId: string }) {
  const [searchParams] = useSearchParams();
  const [page, setPage] = useState(1);
  const [limit, setLimit] = useState(50);
  const [severity, setSeverity] = useState<SeverityFilter>("flagged");
  const [enumeratorInput, setEnumeratorInput] = useState("");
  const [enumerator, setEnumerator] = useState("");
  const [columnMode, setColumnMode] = useState<ColumnMode>("review");
  const [section, setSection] = useState<SectionId>("flagged");
  const [detail, setDetail] = useState<CellDetail | null>(null);

  const dateFrom = searchParams.get("dateFrom") || "";
  const dateTo = searchParams.get("dateTo") || "";

  useEffect(() => {
    setPage(1);
  }, [dateFrom, dateTo]);

  useEffect(() => {
    const timer = setTimeout(() => {
      setEnumerator(enumeratorInput.trim());
      setPage(1);
    }, 350);
    return () => clearTimeout(timer);
  }, [enumeratorInput]);

  const dateParams = {
    dateFrom: dateFrom || undefined,
    dateTo: dateTo || undefined,
  };

  // Flagged count within the active date window (ignores enumerator / severity UI).
  const flagProbeQuery = useGetProjectDataGrid(
    projectId,
    { page: 1, limit: 1, severity: "flagged", ...dateParams },
    { query: { enabled: Boolean(projectId) } as never },
  );
  const hasFlaggedSubmissions = (flagProbeQuery.data?.total ?? 0) > 0;
  const dqaFiltersKnown =
    flagProbeQuery.isSuccess || (flagProbeQuery.isError && !flagProbeQuery.isFetching);
  const dqaFiltersDisabled = dqaFiltersKnown && !hasFlaggedSubmissions;

  useEffect(() => {
    if (!dqaFiltersDisabled) return;
    setSeverity("");
    setColumnMode("all");
    setPage(1);
  }, [projectId, dqaFiltersDisabled, dateFrom, dateTo]);

  const gridQuery = useGetProjectDataGrid(
    projectId,
    {
      page,
      limit,
      severity: severity || undefined,
      enumerator: enumerator || undefined,
      ...dateParams,
    },
    {
      query: {
        enabled: Boolean(projectId),
        placeholderData: (previous: SubmissionGrid | undefined) =>
          previous?.projectId === projectId ? previous : undefined,
      } as never,
    },
  );

  const grid = gridQuery.data;
  const allColumns = grid?.columns ?? [];
  const rows = grid?.rows ?? [];

  const districtColumn = useMemo(
    () => findColumnByCodes(allColumns, PIN_DISTRICT_CODES),
    [allColumns],
  );
  const centreColumn = useMemo(
    () => findColumnByCodes(allColumns, CENTRE_CODES),
    [allColumns],
  );

  const groups = useMemo(() => {
    const map = new Map<string, { id: string; label: string }>();
    for (const column of allColumns) {
      if (!column.group || isInstrumentColumn(column)) continue;
      const label = (column.groupLabel || column.group).trim();
      // Skip anonymous / technical nested group ids from XLSForm.
      if (/^group-\d+$/i.test(label)) continue;
      if (/^[A-Za-z0-9_]+group$/i.test(label)) continue;
      if (/^[A-Za-z]\d{0,3}$/.test(label)) continue;
      if (!map.has(column.group)) {
        map.set(column.group, {
          id: column.group,
          label,
        });
      }
    }
    return [...map.values()];
  }, [allColumns]);

  const questionColumns = useMemo(() => {
    const excludeKeys = new Set(
      [districtColumn?.key, centreColumn?.key].filter(Boolean) as string[],
    );

    let base = allColumns.filter((column) => !excludeKeys.has(column.key));

    if (columnMode === "review") {
      base = base.filter((column) => !isInstrumentColumn(column));
      if (section === "flagged") {
        base = base.filter((column) => (column.flagged ?? 0) > 0);
      } else {
        base = base.filter((column) => column.group === section);
      }
    } else {
      base = base.filter(
        (column) => (column.filled ?? 0) > 0 || (column.flagged ?? 0) > 0,
      );
    }

    return base;
  }, [allColumns, columnMode, section, districtColumn, centreColumn]);

  const qualityLabel = (id: SeverityFilter, label: string) => {
    if (!grid) return label;
    if (id === severity || (id === "" && severity === "")) {
      return `${label} · ${grid.total.toLocaleString()}`;
    }
    return label;
  };

  const openCell = (row: GridRow, column: GridColumn, cell: GridCell) => {
    setDetail({
      row,
      columnLabel: column.label,
      columnCode: column.code,
      columnKey: column.key,
      value: cell.value ?? "",
      flags: cell.flags ?? [],
    });
  };

  const openFormLevel = (row: GridRow) => {
    setDetail({
      row,
      columnLabel: "Form-level checks",
      columnCode: row.koboId || row.displayId,
      columnKey: null,
      value: "",
      flags: row.rowFlags ?? [],
      formLevel: true,
    });
  };

  const reviewEmpty =
    columnMode === "review" &&
    section === "flagged" &&
    questionColumns.length === 0 &&
    !gridQuery.isLoading;

  const related = detail
    ? relatedAnswers(detail.row, allColumns, detail.flags, detail.columnKey)
    : [];

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border bg-card">
      <div className="shrink-0 space-y-2 border-b px-3 py-2.5">
        <div className="flex flex-wrap items-center gap-2">
          <ToggleGroup
            type="single"
            variant="outline"
            size="sm"
            value={severity || "all"}
            onValueChange={(next) => {
              if (!next) return;
              const mapped: SeverityFilter =
                next === "all" ? "" : (next as SeverityFilter);
              if (dqaFiltersDisabled && mapped !== "") return;
              setSeverity(mapped);
              setPage(1);
            }}
            className="justify-start flex-wrap"
          >
            <ToggleGroupItem value="all" className="text-xs px-2.5 h-8">
              {qualityLabel("", "All")}
            </ToggleGroupItem>
            <ToggleGroupItem
              value="flagged"
              className="text-xs px-2.5 h-8"
              disabled={dqaFiltersDisabled}
              title={
                dqaFiltersDisabled
                  ? "No flagged submissions in this form"
                  : undefined
              }
            >
              {qualityLabel("flagged", "Flagged")}
            </ToggleGroupItem>
            <ToggleGroupItem
              value="red"
              className="text-xs px-2.5 h-8"
              disabled={dqaFiltersDisabled}
              title={
                dqaFiltersDisabled
                  ? "No flagged submissions in this form"
                  : undefined
              }
            >
              {qualityLabel("red", "Red")}
            </ToggleGroupItem>
            <ToggleGroupItem
              value="amber"
              className="text-xs px-2.5 h-8"
              disabled={dqaFiltersDisabled}
              title={
                dqaFiltersDisabled
                  ? "No flagged submissions in this form"
                  : undefined
              }
            >
              {qualityLabel("amber", "Amber")}
            </ToggleGroupItem>
            <ToggleGroupItem
              value="clean"
              className="text-xs px-2.5 h-8"
              disabled={dqaFiltersDisabled}
              title={
                dqaFiltersDisabled
                  ? "No flagged submissions in this form"
                  : undefined
              }
            >
              {qualityLabel("clean", "Clean")}
            </ToggleGroupItem>
          </ToggleGroup>

          <Input
            value={enumeratorInput}
            onChange={(event) => setEnumeratorInput(event.target.value)}
            placeholder="Enumerator…"
            className="h-8 w-full sm:w-44"
          />

          <div className="ml-auto flex flex-wrap items-center gap-2">
            <ToggleGroup
              type="single"
              variant="outline"
              size="sm"
              value={columnMode}
              onValueChange={(next) => {
                if (next === "all") setColumnMode("all");
                if (next === "review" && !dqaFiltersDisabled) setColumnMode("review");
              }}
              className="justify-start"
            >
              <ToggleGroupItem
                value="review"
                className="text-xs px-2.5 h-8"
                disabled={dqaFiltersDisabled}
                title={
                  dqaFiltersDisabled
                    ? "No flagged submissions to review"
                    : undefined
                }
              >
                Review
              </ToggleGroupItem>
              <ToggleGroupItem value="all" className="text-xs px-2.5 h-8">
                All questions
              </ToggleGroupItem>
            </ToggleGroup>
            <Button
              variant="outline"
              size="sm"
              className="h-8"
              title="Download the rows on this page as CSV"
              disabled={rows.length === 0}
              onClick={() =>
                downloadCsv(
                  `${grid?.projectName ?? "submissions"}-page${page}.csv`,
                  questionColumns,
                  rows,
                )
              }
            >
              <Download className="mr-2 h-4 w-4" />
              Export
            </Button>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[11px] uppercase tracking-wide text-muted-foreground">
            Section
          </span>
          <button
            type="button"
            disabled={dqaFiltersDisabled}
            className={cn(
              "rounded-md px-2 py-1 text-xs transition-colors",
              dqaFiltersDisabled && "cursor-not-allowed opacity-50",
              section === "flagged" && columnMode === "review"
                ? "bg-muted font-medium text-foreground"
                : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
            )}
            title={
              dqaFiltersDisabled
                ? "No flagged submissions in this form"
                : undefined
            }
            onClick={() => {
              if (dqaFiltersDisabled) return;
              setSection("flagged");
              setColumnMode("review");
            }}
          >
            Flagged questions
          </button>
          {groups.map((group) => (
            <button
              key={group.id}
              type="button"
              disabled={dqaFiltersDisabled}
              className={cn(
                "rounded-md px-2 py-1 text-xs transition-colors",
                dqaFiltersDisabled && "cursor-not-allowed opacity-50",
                section === group.id && columnMode === "review"
                  ? "bg-muted font-medium text-foreground"
                  : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
              )}
              title={
                dqaFiltersDisabled
                  ? "No flagged submissions to review"
                  : undefined
              }
              onClick={() => {
                if (dqaFiltersDisabled) return;
                setSection(group.id);
                setColumnMode("review");
              }}
            >
              {group.label}
            </button>
          ))}
          <span className="text-xs text-muted-foreground">
            {columnMode === "review"
              ? `${questionColumns.length} questions in review · instrument fields hidden`
              : `Showing all questions · ${questionColumns.length} columns`}
          </span>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-auto">
        <table className="w-full border-separate border-spacing-0 text-sm">
          <thead>
            <tr>
              <th className="sticky left-0 top-0 z-30 min-w-[200px] border-b border-r bg-muted px-3 py-2 text-left align-top">
                <span className="block text-xs font-semibold">Form</span>
                <span className="block text-[10px] font-normal text-muted-foreground">
                  Enumerator · centre · time
                </span>
              </th>
              {districtColumn && (
                <th className="sticky top-0 z-20 min-w-[96px] border-b bg-muted px-3 py-2 text-left align-top">
                  <span className="block text-xs font-semibold">District</span>
                </th>
              )}
              <th className="sticky top-0 z-20 min-w-[72px] border-b bg-muted px-3 py-2 text-left align-top">
                <span className="block text-xs font-semibold">Flags</span>
              </th>
              {questionColumns.map((column) => (
                <th
                  key={column.key}
                  className="sticky top-0 z-20 min-w-[140px] max-w-[220px] border-b bg-muted px-3 py-2 text-left align-top"
                  title={`${column.code} — ${column.label}`}
                >
                  <span className="block text-xs font-semibold">{column.code}</span>
                  <span className="block truncate text-[10px] font-normal normal-case text-muted-foreground">
                    {column.label}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const centre = cellValue(row, centreColumn);
              const district = cellValue(row, districtColumn);
              const flagBits: string[] = [];
              if ((row.redFlags ?? 0) > 0) flagBits.push(`${row.redFlags} red`);
              if ((row.amberFlags ?? 0) > 0) flagBits.push(`${row.amberFlags} amber`);
              const titleParts = [
                row.koboId || row.displayId,
                formatDateTime(row.submittedAt),
                flagBits.join(" · ") || "Clean",
              ];
              return (
                <tr key={row.submissionId} className="hover:bg-muted/20">
                  <th
                    scope="row"
                    className="sticky left-0 z-10 border-b border-r bg-card px-3 py-2 text-left align-middle font-normal"
                    title={titleParts.join(" · ")}
                  >
                    <div className="flex gap-2">
                      <SeverityPip severity={row.severity} />
                      <div className="min-w-0">
                        <Link
                          href={`/submissions/${encodeURIComponent(row.submissionId)}`}
                          className="block truncate text-sm font-semibold text-foreground hover:text-primary"
                        >
                          {row.enumerator || "Unknown"}
                        </Link>
                        <span className="block truncate text-xs text-muted-foreground">
                          {[centre || null, formatDateTime(row.submittedAt)]
                            .filter(Boolean)
                            .join(" · ")}
                        </span>
                        {(row.rowFlags?.length ?? 0) > 0 && (
                          <button
                            type="button"
                            className="mt-0.5 text-[10px] text-primary underline"
                            onClick={() => openFormLevel(row)}
                          >
                            {row.rowFlags?.length} form-level
                          </button>
                        )}
                      </div>
                    </div>
                  </th>
                  {districtColumn && (
                    <td className="border-b px-3 py-2 align-middle text-sm">
                      <span className="truncate block max-w-[120px]" title={district}>
                        {district || "—"}
                      </span>
                    </td>
                  )}
                  <td className="border-b px-3 py-2 align-middle text-sm text-muted-foreground">
                    {flagBits.length > 0 ? flagBits.join(" · ") : "—"}
                  </td>
                  {questionColumns.map((column) => {
                    const cell = row.cells?.[column.key];
                    const raw = cell?.value ?? "";
                    const display = formatCellDisplay(raw);
                    const flags = cell?.flags ?? [];
                    const className = cn(
                      "border-b px-0 py-0 align-middle",
                      severityBarClass(cell?.severity),
                    );
                    if (flags.length === 0) {
                      return (
                        <td key={column.key} className={className}>
                          <div className="px-3 py-2">
                            <span
                              className="line-clamp-2 break-words text-sm"
                              title={raw || undefined}
                            >
                              {display || (
                                <span className="text-muted-foreground">—</span>
                              )}
                            </span>
                          </div>
                        </td>
                      );
                    }
                    return (
                      <td key={column.key} className={className}>
                        <button
                          type="button"
                          onClick={() => openCell(row, column, cell!)}
                          className="w-full px-3 py-2 text-left"
                          title={flags.map((flag) => flag.title).join(" · ")}
                        >
                          <span className="line-clamp-2 break-words text-sm">
                            {display || (
                              <span className="text-muted-foreground">Blank</span>
                            )}
                          </span>
                        </button>
                      </td>
                    );
                  })}
                </tr>
              );
            })}
            {rows.length === 0 && (
              <tr>
                <td
                  colSpan={
                    questionColumns.length + 2 + (districtColumn ? 1 : 0)
                  }
                  className="px-4 py-12 text-center text-muted-foreground"
                >
                  {gridQuery.isLoading
                    ? "Loading form data…"
                    : "No forms match these filters."}
                </td>
              </tr>
            )}
            {reviewEmpty && rows.length > 0 && (
              <tr>
                <td
                  colSpan={
                    questionColumns.length + 2 + (districtColumn ? 1 : 0)
                  }
                  className="px-4 py-8 text-center text-muted-foreground"
                >
                  No flagged questions in this result.{" "}
                  <button
                    type="button"
                    className="text-primary underline"
                    onClick={() => setColumnMode("all")}
                  >
                    Switch to All questions
                  </button>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 border-t px-3 py-2">
        <div className="flex flex-wrap items-center gap-3">
          <p className="text-xs text-muted-foreground">
            Page {grid?.page ?? page} of {Math.max(grid?.totalPages ?? 1, 1)}
            {gridQuery.isFetching ? " · updating…" : ""}
          </p>
          <select
            className="field-control h-8 px-2 text-xs"
            value={limit}
            aria-label="Rows per page"
            onChange={(event) => {
              setLimit(Number(event.target.value));
              setPage(1);
            }}
          >
            {PAGE_SIZES.map((size) => (
              <option key={size} value={size}>
                {size} rows
              </option>
            ))}
          </select>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={page <= 1 || gridQuery.isFetching}
            onClick={() => setPage((value) => Math.max(1, value - 1))}
          >
            <ChevronLeft className="mr-1 h-4 w-4" />
            Previous
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={!grid || page >= grid.totalPages || gridQuery.isFetching}
            onClick={() => setPage((value) => value + 1)}
          >
            Next
            <ChevronRight className="ml-1 h-4 w-4" />
          </Button>
        </div>
      </div>

      {gridQuery.error && (
        <p className="px-3 pb-2 text-sm text-destructive">
          {(gridQuery.error as Error).message}
        </p>
      )}

      <Sheet open={Boolean(detail)} onOpenChange={(open) => !open && setDetail(null)}>
        <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-md">
          <SheetHeader>
            <SheetTitle className="text-base">
              <span className="block font-mono text-xs text-muted-foreground">
                {detail?.columnCode}
              </span>
              {detail?.columnLabel}
            </SheetTitle>
          </SheetHeader>
          {detail && (
            <div className="mt-4 space-y-4">
              {!detail.formLevel && (
                <div
                  className={cn(
                    "rounded-md border p-3",
                    detail.flags[0]?.severity === "red" &&
                      "border-l-[3px] border-l-red-500 bg-muted/40",
                    detail.flags[0]?.severity === "amber" &&
                      "border-l-[3px] border-l-amber-500 bg-muted/40",
                    !detail.flags[0] && "bg-muted/40",
                  )}
                >
                  <p className="text-xs text-muted-foreground">Recorded answer</p>
                  <p className="mt-1 break-words text-sm font-medium">
                    {formatCellDisplay(detail.value) || "Blank"}
                  </p>
                </div>
              )}
              {related.length > 0 && (
                <div className="space-y-2">
                  <p className="text-xs text-muted-foreground">Related answers</p>
                  <ul className="space-y-1.5">
                    {related.map((item) => (
                      <li key={item.code} className="text-sm">
                        <span className="font-mono text-xs text-muted-foreground">
                          {item.code}
                        </span>{" "}
                        {item.value}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              <FlagList projectId={projectId} flags={detail.flags} />
              <div className="space-y-1 border-t pt-3 text-sm">
                <p className="text-xs text-muted-foreground">
                  {detail.row.enumerator || "Unknown enumerator"} ·{" "}
                  {formatDateTime(detail.row.submittedAt)}
                </p>
                <Link
                  href={`/submissions/${encodeURIComponent(detail.row.submissionId)}`}
                  className="inline-flex items-center gap-2 text-primary underline"
                >
                  <Eye className="h-4 w-4" />
                  Open full form {detail.row.koboId || detail.row.displayId}
                </Link>
              </div>
            </div>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}

export default SubmissionsGrid;
