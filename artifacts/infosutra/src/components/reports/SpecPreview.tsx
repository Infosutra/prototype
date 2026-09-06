import type { ReactElement } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

type Json = Record<string, unknown>;

const SERIES_COLORS = ["#0f766e", "#b45309", "#b91c1c", "#1d4ed8", "#7c3aed"];

function asRecord(value: unknown): Json {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Json) : {};
}

function asRows(value: unknown): Json[] {
  if (Array.isArray(value)) {
    return value.filter((row): row is Json => Boolean(row) && typeof row === "object");
  }
  if (value && typeof value === "object") return [value as Json];
  return [];
}

function dataKey(source: string | undefined, params: unknown): string {
  if (!source) return "";
  const entries = Object.entries(asRecord(params)).sort(([a], [b]) => a.localeCompare(b));
  if (!entries.length) return source;
  return `${source}?${entries.map(([k, v]) => `${k}=${v}`).join("&")}`;
}

function formatValue(value: unknown, format?: string): string {
  if (value == null || value === "") return "—";
  if (format === "percent") {
    const n = Number(value);
    return Number.isFinite(n) ? `${n}%` : String(value);
  }
  if (format === "int") {
    const n = Number(value);
    return Number.isFinite(n) ? n.toLocaleString() : String(value);
  }
  if (format === "severity") return String(value).toUpperCase();
  return String(value);
}

function sortRows(rows: Json[], sort: unknown, limit?: number): Json[] {
  const spec = asRecord(sort);
  const field = typeof spec.field === "string" ? spec.field : "";
  const direction = spec.direction === "asc" ? 1 : -1;
  const copy = [...rows];
  if (field) {
    copy.sort((a, b) => {
      const left = a[field];
      const right = b[field];
      if (typeof left === "number" && typeof right === "number") return (left - right) * direction;
      return String(left ?? "").localeCompare(String(right ?? "")) * direction;
    });
  }
  return typeof limit === "number" && limit > 0 ? copy.slice(0, limit) : copy;
}

function payloadFor(component: Json, data: Json): { rows: Json[]; record: Json; error?: string } {
  const key = dataKey(String(component.dataSource || ""), component.params);
  if (key && data[key] === undefined) {
    return { rows: [], record: {}, error: "not available" };
  }
  const value = key ? data[key] : undefined;
  const rows = asRows(value);
  return { rows, record: rows[0] ?? asRecord(value) };
}

function chartConfig(series: Json[]): ChartConfig {
  return Object.fromEntries(
    series.map((item, index) => [
      String(item.field || item.label || index),
      {
        label: String(item.label || item.field || `Series ${index + 1}`),
        color: String(item.color || SERIES_COLORS[index % SERIES_COLORS.length]),
      },
    ]),
  );
}

function ChartFrame({
  title,
  caption,
  config,
  children,
}: {
  title?: string;
  caption?: string;
  config: ChartConfig;
  children: ReactElement;
}) {
  return (
    <Card>
      {title ? (
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium">{title}</CardTitle>
        </CardHeader>
      ) : null}
      <CardContent>
        <ChartContainer config={config} className="aspect-[16/7] w-full">
          {children}
        </ChartContainer>
        {caption ? <p className="mt-2 text-xs text-muted-foreground">{caption}</p> : null}
      </CardContent>
    </Card>
  );
}

function ComponentView({
  component,
  data,
  narratives,
  unavailable,
}: {
  component: Json;
  data: Json;
  narratives: Record<string, string>;
  unavailable: Record<string, string>;
}) {
  const type = String(component.type || "");
  const key = dataKey(String(component.dataSource || ""), component.params);
  const failed = (key && unavailable[key]) || "";
  const { rows, record, error } = payloadFor(component, data);
  const reason = failed || error;

  if (type === "text") {
    return <p className="text-sm text-muted-foreground">{String(component.body || "")}</p>;
  }

  if (type === "insight" || type === "warning" || type === "action_plan") {
    const text = narratives[String(component.id || "")] || "";
    if (!text) return null;
    const tone =
      type === "warning"
        ? "border-amber-300 bg-amber-50"
        : type === "action_plan"
          ? "border-teal-700 bg-teal-50"
          : "border-teal-600 bg-muted/40";
    return (
      <div className={`rounded-md border-l-4 px-4 py-3 text-sm ${tone}`}>
        <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          {String(component.title || type.replace("_", " "))}
        </p>
        <p className="whitespace-pre-wrap">{text}</p>
      </div>
    );
  }

  if (reason && ["metric", "kpi_group", "table", "ranking", "bar_chart", "stacked_bar_chart", "line_chart", "pie_chart", "progress"].includes(type)) {
    return <p className="text-sm italic text-muted-foreground">{String(reason)}</p>;
  }

  if (type === "metric") {
    return (
      <Card>
        <CardContent className="p-4">
          <p className="text-2xl font-semibold tabular-nums">
            {formatValue(record[String(component.field)], String(component.format || ""))}
          </p>
          <p className="text-xs uppercase tracking-wide text-muted-foreground">
            {String(component.label || component.field || "")}
          </p>
        </CardContent>
      </Card>
    );
  }

  if (type === "kpi_group") {
    const items = Array.isArray(component.items) ? (component.items as Json[]) : [];
    return (
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {items.map((item) => (
          <Card key={String(item.field || item.label)}>
            <CardContent className="p-4">
              <p className="text-2xl font-semibold tabular-nums">
                {formatValue(record[String(item.field)], String(item.format || ""))}
              </p>
              <p className="text-xs uppercase tracking-wide text-muted-foreground">
                {String(item.label || item.field)}
              </p>
            </CardContent>
          </Card>
        ))}
      </div>
    );
  }

  if (type === "table") {
    const columns = Array.isArray(component.columns) ? (component.columns as Json[]) : [];
    const shown = sortRows(rows, component.sort, Number(component.limit) || undefined);
    if (!shown.length) {
      return <p className="text-sm text-muted-foreground">{String(component.emptyText || "No rows.")}</p>;
    }
    return (
      <Table>
        <TableHeader>
          <TableRow>
            {columns.map((col) => (
              <TableHead key={String(col.field)} className={col.align === "right" ? "text-right" : ""}>
                {String(col.label || col.field)}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {shown.map((row, index) => (
            <TableRow key={index}>
              {columns.map((col) => (
                <TableCell key={String(col.field)} className={col.align === "right" ? "text-right tabular-nums" : ""}>
                  {formatValue(row[String(col.field)], String(col.format || ""))}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    );
  }

  if (type === "ranking") {
    const shown = sortRows(rows, component.sort, Number(component.limit) || 8);
    return (
      <ol className="space-y-1">
        {shown.map((row, index) => (
          <li key={index} className="flex justify-between gap-4 rounded-md px-3 py-2 text-sm hover:bg-muted/50">
            <span>{String(row[String(component.labelField)] ?? "—")}</span>
            <span className="tabular-nums font-medium">
              {formatValue(row[String(component.valueField)], String(component.valueFormat || ""))}
            </span>
          </li>
        ))}
      </ol>
    );
  }

  const series = Array.isArray(component.series) ? (component.series as Json[]) : [];
  const x = String(component.x || component.labelField || "label");
  const shown = sortRows(rows, component.sort, Number(component.limit) || undefined);
  const config = chartConfig(
    series.length
      ? series
      : [{ field: String(component.valueField || "value"), label: String(component.title || "Value") }],
  );

  if (type === "line_chart") {
    return (
      <ChartFrame title={String(component.title || "")} caption={String(component.caption || "")} config={config}>
        <LineChart data={shown}>
          <CartesianGrid vertical={false} />
          <XAxis dataKey={x} tickLine={false} axisLine={false} />
          <YAxis tickLine={false} axisLine={false} />
          <ChartTooltip content={<ChartTooltipContent />} />
          <ChartLegend content={<ChartLegendContent />} />
          {series.map((item, index) => (
            <Line
              key={String(item.field)}
              type="monotone"
              dataKey={String(item.field)}
              stroke={`var(--color-${item.field})`}
              strokeWidth={2}
              dot={false}
              name={String(item.label || item.field)}
            />
          ))}
        </LineChart>
      </ChartFrame>
    );
  }

  if (type === "pie_chart") {
    const labelField = String(component.labelField || "label");
    const valueField = String(component.valueField || "value");
    return (
      <ChartFrame title={String(component.title || "")} caption={String(component.caption || "")} config={config}>
        <PieChart>
          <Pie data={shown} dataKey={valueField} nameKey={labelField} innerRadius={40} outerRadius={80}>
            {shown.map((_, index) => (
              <Cell key={index} fill={SERIES_COLORS[index % SERIES_COLORS.length]} />
            ))}
          </Pie>
          <ChartTooltip content={<ChartTooltipContent />} />
        </PieChart>
      </ChartFrame>
    );
  }

  if (type === "progress") {
    const labelField = String(component.labelField || "label");
    const valueField = String(component.valueField || "value");
    const targetField = String(component.targetField || "target");
    return (
      <div className="space-y-3">
        {component.title ? <h4 className="text-sm font-medium">{String(component.title)}</h4> : null}
        {shown.map((row, index) => {
          const value = Number(row[valueField]) || 0;
          const target = Number(row[targetField]) || 0;
          const pct = target > 0 ? Math.min(100, Math.round((value / target) * 100)) : 0;
          return (
            <div key={index}>
              <div className="mb-1 flex justify-between text-xs">
                <span>{String(row[labelField] ?? "—")}</span>
                <span className="tabular-nums text-muted-foreground">
                  {formatValue(value, "int")} / {formatValue(target, "int")} ({pct}%)
                </span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-muted">
                <div className="h-full bg-teal-700" style={{ width: `${pct}%` }} />
              </div>
            </div>
          );
        })}
      </div>
    );
  }

  if (type === "bar_chart" || type === "stacked_bar_chart") {
    return (
      <ChartFrame title={String(component.title || "")} caption={String(component.caption || "")} config={config}>
        <BarChart data={shown} layout={component.orientation === "horizontal" ? "vertical" : "horizontal"}>
          <CartesianGrid vertical={false} />
          {component.orientation === "horizontal" ? (
            <>
              <XAxis type="number" tickLine={false} axisLine={false} />
              <YAxis type="category" dataKey={x} tickLine={false} axisLine={false} width={72} />
            </>
          ) : (
            <>
              <XAxis dataKey={x} tickLine={false} axisLine={false} />
              <YAxis tickLine={false} axisLine={false} />
            </>
          )}
          <ChartTooltip content={<ChartTooltipContent />} />
          <ChartLegend content={<ChartLegendContent />} />
          {series.map((item) => (
            <Bar
              key={String(item.field)}
              dataKey={String(item.field)}
              fill={`var(--color-${item.field})`}
              name={String(item.label || item.field)}
              stackId={type === "stacked_bar_chart" ? "stack" : undefined}
              radius={3}
            />
          ))}
        </BarChart>
      </ChartFrame>
    );
  }

  return null;
}

export function SpecPreview({
  spec,
  data,
  narratives = {},
  unavailable = {},
}: {
  spec: Json;
  data: Json;
  narratives?: Record<string, string>;
  unavailable?: Record<string, string>;
}) {
  const sections = Array.isArray(spec.sections) ? (spec.sections as Json[]) : [];
  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-xl font-semibold">{String(spec.title || "Untitled report")}</h2>
        {spec.subtitle ? (
          <p className="text-sm text-muted-foreground">{String(spec.subtitle)}</p>
        ) : null}
      </div>
      {sections.map((section, index) => (
        <section key={String(section.id || index)} className="space-y-4">
          <div className="flex items-center gap-2">
            <h3 className="text-base font-semibold">{String(section.title || `Section ${index + 1}`)}</h3>
            <Badge variant="outline" className="text-[10px]">
              {Array.isArray(section.components) ? section.components.length : 0} components
            </Badge>
          </div>
          {Array.isArray(section.components)
            ? section.components.map((component, componentIndex) => (
                <ComponentView
                  key={String((component as Json).id || componentIndex)}
                  component={asRecord(component)}
                  data={data}
                  narratives={narratives}
                  unavailable={unavailable}
                />
              ))
            : null}
        </section>
      ))}
    </div>
  );
}
