import React, { useEffect, useMemo, useState } from "react";
import { Link } from "wouter";
import { useQuery } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { ChevronLeft, ChevronRight, Download, Eye, ShieldAlert } from "lucide-react";
import {
  dqaApi,
  type GridCell,
  type GridColumn,
  type GridFlagRef,
  type GridRow,
} from "@/lib/dqa-api";

const SEVERITY_FILTERS = [
  { id: "", label: "All forms" },
  { id: "flagged", label: "Flagged only" },
  { id: "red", label: "RED only" },
  { id: "amber", label: "AMBER only" },
  { id: "clean", label: "Clean only" },
] as const;

const PAGE_SIZES = [25, 50, 100, 200];

type CellDetail = {
  row: GridRow;
  columnLabel: string;
  columnCode: string;
  value: string;
  flags: GridFlagRef[];
};

function severityCellClass(severity?: string | null): string {
  if (severity === "red") {
    return "bg-red-100 text-red-900 dark:bg-red-950/60 dark:text-red-200";
  }
  if (severity === "amber") {
    return "bg-amber-100 text-amber-900 dark:bg-amber-950/60 dark:text-amber-200";
  }
  return "";
}

function formatDateTime(value: string): string {
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
    const flags = [...row.rowFlags, ...columns.flatMap((c) => row.cells[c.key]?.flags ?? [])];
    const ruleIds = [...new Set(flags.map((flag) => `${flag.ruleId}(${flag.severity})`))];
    lines.push(
      [
        row.displayId,
        row.submittedAt,
        row.enumerator,
        row.status,
        ruleIds.join(" "),
        ...columns.map((column) => row.cells[column.key]?.value ?? ""),
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

function FlagList({ projectId, flags }: { projectId: string; flags: GridFlagRef[] }) {
  return (
    <ul className="space-y-3">
      {flags.map((flag) => (
        <li key={`${flag.id}-${flag.ruleId}`} className="rounded-md border p-3">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={flag.severity === "red" ? "destructive" : "secondary"}>
              {flag.severity.toUpperCase()}
            </Badge>
            <span className="font-mono text-xs text-muted-foreground">{flag.ruleId}</span>
            <span className="text-sm font-medium">{flag.title}</span>
          </div>
          <p className="mt-2 text-sm text-muted-foreground">{flag.message}</p>
          <Link
            href={`/dqa?projectId=${encodeURIComponent(projectId)}&ruleId=${encodeURIComponent(flag.ruleId)}`}
            className="mt-2 inline-block text-xs text-primary underline"
          >
            All forms flagged by {flag.ruleId} →
          </Link>
        </li>
      ))}
    </ul>
  );
}

export function SubmissionsGrid({ projectId }: { projectId: string }) {
  const [page, setPage] = useState(1);
  const [limit, setLimit] = useState(50);
  const [severity, setSeverity] = useState("");
  const [enumeratorInput, setEnumeratorInput] = useState("");
  const [enumerator, setEnumerator] = useState("");
  const [hideEmptyColumns, setHideEmptyColumns] = useState(true);
  const [flaggedColumnsOnly, setFlaggedColumnsOnly] = useState(false);
  const [detail, setDetail] = useState<CellDetail | null>(null);

  useEffect(() => {
    const timer = setTimeout(() => {
      setEnumerator(enumeratorInput.trim());
      setPage(1);
    }, 350);
    return () => clearTimeout(timer);
  }, [enumeratorInput]);

  const gridQuery = useQuery({
    queryKey: ["submission-grid", projectId, page, limit, severity, enumerator],
    queryFn: () =>
      dqaApi.dataGrid(projectId, {
        page,
        limit,
        severity: severity || undefined,
        enumerator: enumerator || undefined,
      }),
    enabled: Boolean(projectId),
    placeholderData: (previous) =>
      previous?.projectId === projectId ? previous : undefined,
  });

  const grid = gridQuery.data;

  const columns = useMemo(() => {
    const all = grid?.columns ?? [];
    if (flaggedColumnsOnly) return all.filter((column) => column.flagged > 0);
    if (hideEmptyColumns) return all.filter((column) => column.filled > 0 || column.flagged > 0);
    return all;
  }, [grid?.columns, flaggedColumnsOnly, hideEmptyColumns]);

  const rows = grid?.rows ?? [];
  const hiddenColumns = (grid?.columns.length ?? 0) - columns.length;
  const amberRows = rows.filter((row) => row.severity === "amber").length;
  const redRows = rows.filter((row) => row.severity === "red").length;

  const openCell = (row: GridRow, column: GridColumn, cell: GridCell) => {
    setDetail({
      row,
      columnLabel: column.label,
      columnCode: column.code,
      value: cell.value,
      flags: cell.flags,
    });
  };

  return (
    <div className="space-y-4">
      <Card className="p-3">
        <div className="flex flex-wrap items-center gap-2">
          <select
            className="h-9 rounded-md border bg-background px-2 text-sm"
            value={severity}
            onChange={(event) => {
              setSeverity(event.target.value);
              setPage(1);
            }}
          >
            {SEVERITY_FILTERS.map((option) => (
              <option key={option.id} value={option.id}>
                {option.label}
              </option>
            ))}
          </select>
          <Input
            value={enumeratorInput}
            onChange={(event) => setEnumeratorInput(event.target.value)}
            placeholder="Filter by enumerator"
            className="h-9 w-full sm:w-52"
          />
          <select
            className="h-9 rounded-md border bg-background px-2 text-sm"
            value={limit}
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
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            <input
              type="checkbox"
              checked={hideEmptyColumns}
              disabled={flaggedColumnsOnly}
              onChange={(event) => setHideEmptyColumns(event.target.checked)}
            />
            Hide empty questions
          </label>
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            <input
              type="checkbox"
              checked={flaggedColumnsOnly}
              onChange={(event) => setFlaggedColumnsOnly(event.target.checked)}
            />
            Flagged questions only
          </label>
          <Button
            variant="outline"
            size="sm"
            className="ml-auto"
            title="Download the rows on this page as CSV"
            disabled={rows.length === 0}
            onClick={() =>
              downloadCsv(`${grid?.projectName ?? "submissions"}-page${page}.csv`, columns, rows)
            }
          >
            <Download className="mr-2 h-4 w-4" />
            CSV
          </Button>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
          <span>
            {(grid?.total ?? 0).toLocaleString()} forms · {columns.length} questions shown
            {hiddenColumns > 0 ? ` (${hiddenColumns} hidden)` : ""}
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block h-3 w-3 rounded-sm bg-amber-100 dark:bg-amber-950/60" />
            AMBER cell {amberRows > 0 ? `· ${amberRows} rows` : ""}
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block h-3 w-3 rounded-sm bg-red-100 dark:bg-red-950/60" />
            RED cell {redRows > 0 ? `· ${redRows} rows` : ""}
          </span>
          <span>Click a coloured cell for the DQA reason.</span>
        </div>
      </Card>

      <Card className="overflow-hidden">
        <div className="max-h-[70vh] overflow-auto">
          <table className="w-full border-separate border-spacing-0 text-sm">
            <thead>
              <tr>
                <th className="sticky left-0 top-0 z-30 min-w-[132px] border-b border-r bg-muted px-2 py-2 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground md:min-w-[190px] md:px-3">
                  Form
                </th>
                {columns.map((column) => (
                  <th
                    key={column.key}
                    className="sticky top-0 z-20 min-w-[150px] max-w-[260px] border-b bg-muted px-3 py-2 text-left align-top md:min-w-[180px]"
                    title={`${column.code} — ${column.label}`}
                  >
                    <span className="block font-mono text-[10px] text-muted-foreground">
                      {column.code}
                      {column.flagged > 0 ? ` · ${column.flagged} flagged` : ""}
                    </span>
                    <span className="line-clamp-2 text-xs font-medium normal-case text-foreground">
                      {column.label}
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.submissionId} className="hover:bg-muted/30">
                  <th
                    scope="row"
                    className="sticky left-0 z-10 border-b border-r bg-card px-2 py-2 text-left align-top font-normal md:px-3"
                  >
                    <Link
                      href={`/submissions/${encodeURIComponent(row.submissionId)}`}
                      className="font-mono text-xs text-primary underline"
                    >
                      {row.koboId || row.displayId}
                    </Link>
                    <span className="mt-0.5 block truncate text-xs text-muted-foreground">
                      {row.enumerator || "Unknown"}
                    </span>
                    <span className="block text-[10px] text-muted-foreground">
                      {formatDateTime(row.submittedAt)}
                    </span>
                    {(row.redFlags > 0 || row.amberFlags > 0) && (
                      <span className="mt-1 flex flex-wrap items-center gap-1">
                        {row.redFlags > 0 && (
                          <Badge variant="destructive" className="px-1 py-0 text-[10px]">
                            {row.redFlags} RED
                          </Badge>
                        )}
                        {row.amberFlags > 0 && (
                          <Badge variant="secondary" className="px-1 py-0 text-[10px]">
                            {row.amberFlags} AMBER
                          </Badge>
                        )}
                      </span>
                    )}
                    {row.rowFlags.length > 0 && (
                      <button
                        type="button"
                        className="mt-1 flex items-center gap-1 text-[10px] text-primary underline"
                        onClick={() =>
                          setDetail({
                            row,
                            columnLabel: "Form-level checks",
                            columnCode: row.displayId,
                            value: "",
                            flags: row.rowFlags,
                          })
                        }
                      >
                        <ShieldAlert className="h-3 w-3" />
                        {row.rowFlags.length} form-level
                      </button>
                    )}
                  </th>
                  {columns.map((column) => {
                    const cell = row.cells[column.key];
                    const value = cell?.value ?? "";
                    const flags = cell?.flags ?? [];
                    const className = `border-b px-3 py-2 align-top ${severityCellClass(cell?.severity)}`;
                    if (flags.length === 0) {
                      return (
                        <td key={column.key} className={className}>
                          <span
                            className="line-clamp-3 break-words"
                            title={value || undefined}
                          >
                            {value || <span className="text-muted-foreground">—</span>}
                          </span>
                        </td>
                      );
                    }
                    return (
                      <td key={column.key} className={className}>
                        <button
                          type="button"
                          onClick={() => openCell(row, column, cell!)}
                          className="w-full text-left"
                          title={flags.map((flag) => `${flag.ruleId}: ${flag.message}`).join("\n")}
                        >
                          <span className="line-clamp-3 break-words underline decoration-dotted">
                            {value || "(blank)"}
                          </span>
                          <span className="mt-1 block font-mono text-[10px] opacity-80">
                            {flags.map((flag) => flag.ruleId).join(", ")}
                          </span>
                        </button>
                      </td>
                    );
                  })}
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td
                    colSpan={columns.length + 1}
                    className="px-4 py-12 text-center text-muted-foreground"
                  >
                    {gridQuery.isLoading ? "Loading form data…" : "No forms match these filters."}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2 border-t p-3">
          <p className="text-xs text-muted-foreground">
            Page {grid?.page ?? page} of {Math.max(grid?.totalPages ?? 1, 1)}
            {gridQuery.isFetching ? " · updating…" : ""}
          </p>
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
      </Card>

      {gridQuery.error && (
        <p className="text-sm text-destructive">{(gridQuery.error as Error).message}</p>
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
              {detail.value && (
                <div className="rounded-md border bg-muted/40 p-3">
                  <p className="text-xs text-muted-foreground">Recorded answer</p>
                  <p className="mt-1 break-words text-sm font-medium">{detail.value}</p>
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
