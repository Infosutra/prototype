/**
 * Renders hydrated ExecuteResult from a report execute job.
 * Used by template authoring (inline) and the execute-preview page.
 */
import React, { useMemo } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Label,
  Line,
  LineChart,
  Pie,
  PieChart,
  XAxis,
  YAxis,
} from "recharts";
import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";

export type ExecuteResult = {
  reportId?: string;
  title?: string;
  window?: { from?: string; to?: string };
  sections?: Array<{
    id: string;
    title: string;
    components: Array<{
      id: string;
      type: string;
      data?: unknown;
      error?: string;
      display?: {
        kind?: string;
        x?: string;
        y?: string[];
        seriesField?: string;
        stacked?: boolean;
        limit?: number;
        columns?: string[];
      };
    }>;
  }>;
  artifacts?: { pdf?: string };
};

const SERIES_COLORS = ["#0f766e", "#b45309", "#b91c1c", "#1d4ed8", "#7c3aed", "#a16207"];

const KNOWN_LABELS: Record<string, string> = {
  toolCode: "Tool",
  tool_code: "Tool",
  ruleTitle: "Rule",
  rule_title: "Rule",
  enumerator: "Enumerator",
  new_submissions_today: "New today",
  cumulative_submissions: "Cumulative",
  red_today: "RED today",
  amber_today: "AMBER today",
  total_failures: "Failures",
  records_submitted_today: "Submitted today",
  flag_rate: "Flag rate",
  median_interview_time: "Median mins",
  reason_flagged: "Reason flagged",
  count: "Count",
  total: "Total",
  target: "Target",
  day: "Day",
  red_amber_chart: "RED / AMBER by tool",
  rules_failing_chart: "Rules failing most today",
  submissions_vs_target: "Submissions vs target",
  flags_by_day: "Flags by day",
};

const SERIES_COLOR_BY_KEY: Record<string, string> = {
  red_today: "#b91c1c",
  amber_today: "#b45309",
  total_failures: "#b91c1c",
  total: "#0f766e",
  target: "#64748b",
};

function humanizeLabel(key: string): string {
  if (KNOWN_LABELS[key]) return KNOWN_LABELS[key];
  const spaced = key
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/[_-]+/g, " ")
    .trim();
  if (!spaced) return key;
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

function seriesColor(key: string, index: number): string {
  return SERIES_COLOR_BY_KEY[key] || SERIES_COLORS[index % SERIES_COLORS.length];
}

function formatCellValue(key: string, value: unknown): string {
  if (value == null || value === "") return "—";
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return "—";
    const lower = key.toLowerCase();
    if (lower.includes("rate") || lower.includes("pct") || lower.includes("percent")) {
      const pct = Math.abs(value) <= 1 ? value * 100 : value;
      return `${pct.toFixed(pct % 1 === 0 ? 0 : 1)}%`;
    }
    if (lower.includes("time") || lower.includes("duration") || lower.includes("mins")) {
      return value.toLocaleString(undefined, { maximumFractionDigits: 1 });
    }
    if (Number.isInteger(value)) return value.toLocaleString();
    return value.toLocaleString(undefined, { maximumFractionDigits: 1 });
  }
  return String(value);
}

function formatKpiValue(value: unknown): string {
  if (value == null || value === "") return "—";
  if (typeof value === "number" && Number.isFinite(value)) {
    return Number.isInteger(value)
      ? value.toLocaleString()
      : value.toLocaleString(undefined, { maximumFractionDigits: 1 });
  }
  const asNum = Number(value);
  if (typeof value === "string" && value.trim() !== "" && Number.isFinite(asNum)) {
    return Number.isInteger(asNum)
      ? asNum.toLocaleString()
      : asNum.toLocaleString(undefined, { maximumFractionDigits: 1 });
  }
  return String(value);
}

function isNarrativeStub(text: string): boolean {
  const lower = text.toLowerCase();
  return (
    lower.includes("phase 3 narrative stub") ||
    lower.includes("llm analyst deferred") ||
    lower.includes("narrative stub")
  );
}

function ChartErrorFallback({ message }: { message: string }) {
  return (
    <p className="text-xs text-destructive whitespace-pre-wrap">
      Chart failed to render: {message}
    </p>
  );
}

class ChartBoundary extends React.Component<
  { children: React.ReactNode },
  { error: string | null }
> {
  state: { error: string | null } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error: error.message || String(error) };
  }

  render() {
    if (this.state.error) {
      return <ChartErrorFallback message={this.state.error} />;
    }
    return this.props.children;
  }
}

function asRows(data: unknown): Record<string, unknown>[] {
  if (!Array.isArray(data)) return [];
  return data.filter(
    (row): row is Record<string, unknown> => Boolean(row) && typeof row === "object",
  );
}

function numericKeys(rows: Record<string, unknown>[], preferred?: string[]): string[] {
  if (preferred?.length) {
    return preferred.filter((key) => rows.some((row) => row[key] != null));
  }
  if (!rows.length) return [];
  return Object.keys(rows[0]).filter((key) =>
    rows.some((row) => typeof row[key] === "number"),
  );
}

function categoryKey(rows: Record<string, unknown>[], preferred?: string): string {
  if (preferred && rows.some((row) => row[preferred] != null)) return preferred;
  if (!rows.length) return "label";
  const keys = Object.keys(rows[0]);
  const nonNumeric = keys.find((key) =>
    rows.some((row) => typeof row[key] !== "number" && row[key] != null),
  );
  return nonNumeric || keys[0] || "label";
}

function withDisplayLabels(
  rows: Record<string, unknown>[],
  xKey: string,
): Record<string, unknown>[] {
  return rows.map((row) => {
    const raw = row[xKey];
    const label =
      raw == null || String(raw).trim() === "" ? "(unknown)" : String(raw);
    return { ...row, [xKey]: label };
  });
}

function PreviewChart({
  rows,
  display,
  compact,
}: {
  rows: Record<string, unknown>[];
  display?: NonNullable<ExecuteResult["sections"]>[number]["components"][number]["display"];
  compact?: boolean;
}) {
  const kind = String(display?.kind || "bar").toLowerCase();
  const limit = typeof display?.limit === "number" && display.limit > 0 ? display.limit : 24;
  const xKeyPreferred = display?.x;
  const yPreferred = display?.y;
  const stacked = kind === "stacked_bar" || display?.stacked === true;
  const shownRaw = rows.slice(0, limit);
  const xKey = categoryKey(shownRaw, xKeyPreferred);
  const yKeys = numericKeys(shownRaw, yPreferred);
  const looksTemporal = /^(day|date|week|month)$/i.test(xKey) || /date|day|week/i.test(xKey);
  // Multi-series and day trends stay vertical so X/Y axes stay readable.
  // Long single-series category lists go horizontal in the narrow preview.
  const horizontal =
    kind === "bar_horizontal" ||
    (stacked && shownRaw.length <= 4) ||
    (kind === "bar" && !looksTemporal && yKeys.length <= 1 && shownRaw.length > 6);

  const shown = useMemo(() => {
    const labeled = withDisplayLabels(shownRaw, xKey);
    if (kind === "line" || kind === "area") return labeled;
    const sortKey = yKeys[0];
    if (!sortKey) return labeled;
    return [...labeled].sort((a, b) => Number(b[sortKey] ?? 0) - Number(a[sortKey] ?? 0));
  }, [shownRaw, kind, yKeys, xKey]);

  const config = useMemo<ChartConfig>(() => {
    return Object.fromEntries(
      yKeys.map((key, index) => [
        key,
        { label: humanizeLabel(key), color: seriesColor(key, index) },
      ]),
    );
  }, [yKeys]);

  if (!shown.length || (!yKeys.length && kind !== "pie" && kind !== "donut")) {
    return (
      <p className="text-xs text-muted-foreground italic">
        Chart has no plottable rows yet.
      </p>
    );
  }

  const chartHeight = horizontal
    ? Math.min(420, Math.max(compact ? 160 : 200, shown.length * 34 + 48))
    : Math.min(
        compact ? 220 : 280,
        Math.max(compact ? 160 : 200, shown.length * 36 + 72),
      );

  if (kind === "pie" || kind === "donut") {
    const valueKey = yKeys[0] || "total";
    const pieData = shown.map((row, index) => ({
      name: String(row[xKey] ?? index),
      value: Number(row[valueKey] ?? 0),
      fill: SERIES_COLORS[index % SERIES_COLORS.length],
    }));
    return (
      <ChartContainer config={config} className="aspect-auto w-full" style={{ height: chartHeight }}>
        <PieChart>
          <Pie
            data={pieData}
            dataKey="value"
            nameKey="name"
            innerRadius={kind === "donut" ? "55%" : 0}
            outerRadius="80%"
            paddingAngle={1}
          >
            {pieData.map((entry) => (
              <Cell key={entry.name} fill={entry.fill} />
            ))}
          </Pie>
          <ChartTooltip content={<ChartTooltipContent />} />
          <ChartLegend content={<ChartLegendContent />} />
        </PieChart>
      </ChartContainer>
    );
  }

  if (kind === "line" || kind === "area") {
    const categoryAxisTitle = humanizeLabel(xKey);
    const valueAxisTitle =
      yKeys.length === 1 ? humanizeLabel(yKeys[0]) : yKeys.map(humanizeLabel).join(" / ");
    const axisLabelStyle = { fill: "hsl(var(--muted-foreground))", fontSize: 10 };
    return (
      <ChartContainer config={config} className="aspect-auto w-full" style={{ height: chartHeight }}>
        <LineChart data={shown} margin={{ top: 12, right: 16, left: 8, bottom: 36 }}>
          <CartesianGrid vertical={false} strokeDasharray="3 3" />
          <XAxis dataKey={xKey} tickLine={false} axisLine fontSize={11} tickMargin={6}>
            <Label value={categoryAxisTitle} position="insideBottom" offset={-22} style={axisLabelStyle} />
          </XAxis>
          <YAxis tickLine={false} axisLine fontSize={11} width={48}>
            <Label value={valueAxisTitle} angle={-90} position="insideLeft" offset={8} style={axisLabelStyle} />
          </YAxis>
          <ChartTooltip content={<ChartTooltipContent />} />
          <ChartLegend content={<ChartLegendContent />} />
          {yKeys.map((key, index) => (
            <Line
              key={key}
              type="monotone"
              dataKey={key}
              name={humanizeLabel(key)}
              stroke={seriesColor(key, index)}
              strokeWidth={2}
              dot={false}
            />
          ))}
        </LineChart>
      </ChartContainer>
    );
  }

  const labelWidth = horizontal
    ? Math.min(160, Math.max(72, ...shown.map((row) => String(row[xKey] ?? "").length * 7)))
    : undefined;

  const categoryAxisTitle = humanizeLabel(xKey);
  const valueAxisTitle =
    yKeys.length === 1 ? humanizeLabel(yKeys[0]) : yKeys.map(humanizeLabel).join(" / ");

  const axisLabelStyle = { fill: "hsl(var(--muted-foreground))", fontSize: 10 };

  return (
    <ChartContainer config={config} className="aspect-auto w-full" style={{ height: chartHeight }}>
      <BarChart
        data={shown}
        layout={horizontal ? "vertical" : "horizontal"}
        margin={{
          top: 12,
          right: 16,
          left: horizontal ? 8 : 8,
          bottom: horizontal ? 28 : 36,
        }}
        barCategoryGap={horizontal ? "18%" : "22%"}
      >
        <CartesianGrid
          vertical={!horizontal}
          horizontal={horizontal ? false : true}
          strokeDasharray="3 3"
        />
        {horizontal ? (
          <>
            <XAxis type="number" tickLine={false} axisLine fontSize={11} tickMargin={6}>
              <Label value={valueAxisTitle} position="insideBottom" offset={-18} style={axisLabelStyle} />
            </XAxis>
            <YAxis
              type="category"
              dataKey={xKey}
              tickLine={false}
              axisLine
              fontSize={11}
              width={labelWidth}
              tickFormatter={(value) => {
                const text = String(value ?? "");
                return text.length > 22 ? `${text.slice(0, 20)}…` : text;
              }}
            >
              <Label
                value={categoryAxisTitle}
                angle={-90}
                position="insideLeft"
                offset={10}
                style={axisLabelStyle}
              />
            </YAxis>
          </>
        ) : (
          <>
            <XAxis
              dataKey={xKey}
              tickLine={false}
              axisLine
              fontSize={11}
              interval={0}
              angle={shown.length > 5 ? -25 : 0}
              textAnchor={shown.length > 5 ? "end" : "middle"}
              height={shown.length > 5 ? 56 : 32}
              tickMargin={6}
              tickFormatter={(value) => {
                const text = String(value ?? "");
                return text.length > 14 ? `${text.slice(0, 12)}…` : text;
              }}
            >
              <Label value={categoryAxisTitle} position="insideBottom" offset={-22} style={axisLabelStyle} />
            </XAxis>
            <YAxis tickLine={false} axisLine fontSize={11} width={48} tickMargin={4}>
              <Label
                value={valueAxisTitle}
                angle={-90}
                position="insideLeft"
                offset={8}
                style={axisLabelStyle}
              />
            </YAxis>
          </>
        )}
        <ChartTooltip content={<ChartTooltipContent />} />
        <ChartLegend content={<ChartLegendContent />} />
        {yKeys.map((key, index) => (
          <Bar
            key={key}
            dataKey={key}
            name={humanizeLabel(key)}
            fill={seriesColor(key, index)}
            radius={horizontal ? [0, 3, 3, 0] : [3, 3, 0, 0]}
            stackId={stacked ? "stack" : undefined}
            maxBarSize={horizontal ? 22 : 36}
          />
        ))}
      </BarChart>
    </ChartContainer>
  );
}

function TableView({
  rows,
  columns,
  compact,
}: {
  rows: Record<string, unknown>[];
  columns?: string[];
  compact?: boolean;
}) {
  const keys =
    columns?.filter((key) => rows.some((row) => row[key] != null)) ??
    Object.keys(rows[0] || {});
  const maxRows = compact ? 8 : 40;
  const shown = rows.slice(0, maxRows);
  const hidden = rows.length - shown.length;

  return (
    <div className="overflow-x-auto rounded-md border border-border/60">
      <table className="w-full min-w-max text-sm border-collapse">
        <thead className="sticky top-0 bg-background">
          <tr className="text-left border-b bg-muted/40">
            {keys.map((k) => (
              <th
                key={k}
                className="py-1.5 px-2 text-[11px] font-medium text-muted-foreground whitespace-nowrap"
              >
                {humanizeLabel(k)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {shown.map((row, i) => (
            <tr key={i} className="border-b border-border/50 last:border-0">
              {keys.map((k, colIndex) => {
                const raw = row[k];
                const emptyCategory =
                  colIndex === 0 && (raw == null || String(raw).trim() === "");
                return (
                  <td
                    key={k}
                    className={`py-1.5 px-2 text-xs whitespace-nowrap ${
                      colIndex === 0 ? "font-medium text-foreground" : "tabular-nums text-foreground/90"
                    }`}
                  >
                    {emptyCategory ? "(unknown)" : formatCellValue(k, raw)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {hidden > 0 ? (
        <p className="px-2 py-1 text-[11px] text-muted-foreground border-t border-border/60">
          +{hidden} more row{hidden === 1 ? "" : "s"}
        </p>
      ) : null}
    </div>
  );
}

function ComponentView({
  component,
  compact,
}: {
  component: NonNullable<ExecuteResult["sections"]>[number]["components"][number];
  compact?: boolean;
}) {
  if (component.error) {
    return (
      <p className="text-sm text-destructive">
        {component.id}: {component.error}
      </p>
    );
  }
  const data = component.data;
  if (component.type === "kpi_group" && data && typeof data === "object" && !Array.isArray(data)) {
    const record = data as Record<string, unknown>;
    const items = Array.isArray(record.items)
      ? (record.items as Array<Record<string, unknown>>)
      : null;
    if (items) {
      return (
        <div className={`grid gap-3 ${items.length >= 4 ? "grid-cols-2" : "grid-cols-2"}`}>
          {items.map((item, index) => (
            <div key={String(item.label ?? index)} className="min-w-0">
              <p className="text-xl font-semibold tabular-nums tracking-tight">
                {item.error != null ? "—" : formatKpiValue(item.value)}
              </p>
              <p className="text-xs text-muted-foreground mt-0.5 leading-snug">
                {String(item.label ?? "")}
              </p>
              {item.error != null ? (
                <p className="text-[10px] text-destructive mt-1">{String(item.error)}</p>
              ) : null}
            </div>
          ))}
        </div>
      );
    }
    const entries = Object.entries(record);
    return (
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="text-left border-b">
            <th className="py-1 pr-4">Metric</th>
            <th className="py-1">Value</th>
          </tr>
        </thead>
        <tbody>
          {entries.map(([k, v]) => (
            <tr key={k} className="border-b border-border/60">
              <td className="py-1 pr-4">{humanizeLabel(k)}</td>
              <td className="py-1 tabular-nums">{formatKpiValue(v)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }
  if (component.type === "metric" && data && typeof data === "object" && !Array.isArray(data)) {
    const record = data as Record<string, unknown>;
    const value =
      record.value ??
      record.total ??
      Object.values(record).find((v) => typeof v === "number" || typeof v === "string");
    return (
      <div>
        <p className="text-xl font-semibold tabular-nums">{formatKpiValue(value)}</p>
        <p className="text-xs text-muted-foreground">{humanizeLabel(component.id)}</p>
      </div>
    );
  }
  if (component.type === "narrative" || component.type === "text") {
    const text =
      typeof data === "string"
        ? data
        : data && typeof data === "object" && "text" in (data as object)
          ? String((data as { text?: unknown }).text ?? "")
          : data && typeof data === "object" && "body" in (data as object)
            ? String((data as { body?: unknown }).body ?? "")
            : "";
    if (!text) {
      return <p className="text-xs text-muted-foreground italic">Narrative pending…</p>;
    }
    if (isNarrativeStub(text)) {
      return (
        <p className="text-xs text-muted-foreground italic leading-relaxed">
          Narrative not generated yet — numbers above are live; prose comes in a later phase.
        </p>
      );
    }
    return <p className="text-sm whitespace-pre-wrap leading-relaxed">{text}</p>;
  }

  const rows = asRows(data);
  if (component.type === "chart" && rows.length > 0) {
    const caption = humanizeLabel(component.id);
    const note =
      component.id === "flags_by_day"
        ? "Flag counts by day (not a percentage rate — the catalog has no flag-rate measure yet)."
        : component.id === "submissions_vs_target"
          ? "Cumulative submissions compared with each tool’s target."
          : null;
    return (
      <div className="space-y-1.5">
        {compact ? (
          <div className="space-y-0.5">
            <p className="text-[11px] font-medium text-foreground/80">{caption}</p>
            {note ? <p className="text-[10px] text-muted-foreground leading-snug">{note}</p> : null}
          </div>
        ) : null}
        <ChartBoundary>
          <PreviewChart rows={rows} display={component.display} compact={compact} />
        </ChartBoundary>
      </div>
    );
  }
  if (rows.length > 0) {
    return (
      <TableView rows={rows} columns={component.display?.columns} compact={compact} />
    );
  }
  if (data == null) {
    return <p className="text-xs text-muted-foreground">No data</p>;
  }
  return (
    <pre className="text-[11px] bg-muted/40 p-2 rounded overflow-auto max-h-48">
      {JSON.stringify(data, null, 2)}
    </pre>
  );
}

export function ExecuteResultPreview({
  result,
  compact,
}: {
  result: ExecuteResult;
  compact?: boolean;
}) {
  return (
    <div className={compact ? "space-y-5" : "space-y-6"}>
      <div>
        <h2 className={compact ? "text-base font-semibold tracking-tight" : "text-lg font-medium"}>
          {result.title ?? "Preview"}
        </h2>
        {result.window ? (
          <p className="text-xs text-muted-foreground mt-0.5">
            {result.window.from}
            {result.window.to && result.window.to !== result.window.from
              ? ` → ${result.window.to}`
              : ""}
          </p>
        ) : null}
      </div>
      {(result.sections ?? []).map((section) => {
        const components = [...(section.components ?? [])].sort((a, b) => {
          const rank = (type: string) => (type === "narrative" || type === "text" ? 0 : 1);
          return rank(a.type) - rank(b.type);
        });
        return (
          <section key={section.id} className="space-y-3">
            <h3 className="text-sm font-medium border-b border-border/70 pb-1.5">
              {section.title}
            </h3>
            <div className="space-y-3">
              {components.map((c) => (
                <div key={c.id} className="space-y-1.5">
                  {!compact ? (
                    <p className="text-[10px] text-muted-foreground font-mono">
                      {c.id} · {c.type}
                    </p>
                  ) : null}
                  <ComponentView component={c} compact={compact} />
                </div>
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
