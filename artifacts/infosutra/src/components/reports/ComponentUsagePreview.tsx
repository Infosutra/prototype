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
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";

const SERIES_COLORS = ["#0f766e", "#b45309", "#b91c1c", "#1d4ed8"];

/** Human titles for catalog component types (catalog itself only exposes type ids). */
export const COMPONENT_TITLES: Record<string, string> = {
  metric: "Metric",
  kpi_group: "KPI group",
  text: "Text",
  table: "Table",
  ranking: "Ranking",
  bar_chart: "Bar chart",
  stacked_bar_chart: "Stacked bar chart",
  line_chart: "Line chart",
  pie_chart: "Pie chart",
  progress: "Progress",
  insight: "Insight",
  warning: "Warning",
  action_plan: "Action plan",
};

export const COMPONENT_BLURBS: Record<string, string> = {
  metric: "A single headline number (e.g. submissions today).",
  kpi_group: "A row of related headline KPIs from one object source.",
  text: "Static author prose — not for figures or tables.",
  table: "A sortable data table with columns bound to a row source.",
  ranking: "A top/bottom list ordered by a numeric field.",
  bar_chart: "Vertical or horizontal bars comparing categories.",
  stacked_bar_chart: "Stacked bars for parts of a whole by category.",
  line_chart: "Trends over a sequence (e.g. study days).",
  pie_chart: "Share of a total across categories.",
  progress: "Bars toward a target (coverage vs plan).",
  insight: "AI narrative summarizing selected data sources.",
  warning: "AI callout of risks or open issues.",
  action_plan: "AI recommended next steps for the field team.",
};

/** Deterministic “Try this” prompts keyed by component type. */
export const COMPONENT_EXAMPLE_PROMPTS: Record<string, string> = {
  metric: "Show today's submissions as a single KPI.",
  kpi_group: "Show today's submissions, flagged percent, and open RED count as a KPI group.",
  text: "Add a short intro paragraph explaining what this daily report covers.",
  table: "Table of enumerator submission quality with clean, RED and AMBER counts.",
  ranking: "Ranking of enumerators by flag rate today, worst first.",
  bar_chart: "Bar chart of RED and AMBER flags by tool.",
  stacked_bar_chart: "Stacked bar chart of clean, AMBER, and RED submissions by tool.",
  line_chart: "Line chart of daily submissions over the last seven study days.",
  pie_chart: "Pie chart of flag severity breakdown for today.",
  progress: "Progress bars of coverage versus target by tool.",
  insight: "Add an insight summarizing today's data quality risks.",
  warning: "Add a warning about enumerators with high flag rates today.",
  action_plan: "Add an action plan for the field team based on today's RED counts.",
};

export function componentTitle(type: string): string {
  return COMPONENT_TITLES[type] ?? type.replace(/_/g, " ");
}

export function componentBlurb(type: string): string {
  return COMPONENT_BLURBS[type] ?? "Report building block.";
}

export function examplePromptFor(type: string): string {
  return (
    COMPONENT_EXAMPLE_PROMPTS[type] ??
    `Add a ${componentTitle(type).toLowerCase()} to the report.`
  );
}

const DEMO_KPI = { submissions: 142, flaggedPct: 8, openRed: 3 };
const DEMO_TABLE = [
  { name: "Asha", clean: 40, red: 2, amber: 4 },
  { name: "Ravi", clean: 35, red: 5, amber: 3 },
  { name: "Meera", clean: 48, red: 1, amber: 2 },
];
const DEMO_RANKING = [
  { name: "Ravi", flagRate: 18 },
  { name: "Asha", flagRate: 12 },
  { name: "Meera", flagRate: 6 },
];
const DEMO_BARS = [
  { tool: "HH", red: 4, amber: 7 },
  { tool: "IND", red: 2, amber: 5 },
  { tool: "LIST", red: 6, amber: 3 },
];
const DEMO_STACKED = [
  { tool: "HH", clean: 80, amber: 12, red: 8 },
  { tool: "IND", clean: 70, amber: 18, red: 12 },
];
const DEMO_LINE = [
  { day: "D1", submissions: 90 },
  { day: "D2", submissions: 110 },
  { day: "D3", submissions: 105 },
  { day: "D4", submissions: 142 },
];
const DEMO_PIE = [
  { label: "Clean", value: 82 },
  { label: "Amber", value: 12 },
  { label: "Red", value: 6 },
];
const DEMO_PROGRESS = [
  { label: "HH", value: 180, target: 200 },
  { label: "IND", value: 95, target: 150 },
];

const chartConfig = (keys: { key: string; label: string; color: string }[]): ChartConfig =>
  Object.fromEntries(keys.map((item) => [item.key, { label: item.label, color: item.color }]));

function MiniChart({
  config,
  children,
  className = "aspect-[16/7] h-28 w-full",
}: {
  config: ChartConfig;
  children: ReactElement;
  className?: string;
}) {
  return (
    <ChartContainer config={config} className={className}>
      {children}
    </ChartContainer>
  );
}

function MetricPreview() {
  return (
    <div className="rounded-md border bg-background px-3 py-2">
      <p className="text-xl font-semibold tabular-nums">{DEMO_KPI.submissions}</p>
      <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Submissions today</p>
    </div>
  );
}

function KpiGroupPreview() {
  const items = [
    { label: "Submissions", value: DEMO_KPI.submissions },
    { label: "Flagged", value: `${DEMO_KPI.flaggedPct}%` },
    { label: "Open RED", value: DEMO_KPI.openRed },
  ];
  return (
    <div className="grid grid-cols-3 gap-2">
      {items.map((item) => (
        <div key={item.label} className="rounded-md border bg-background px-2 py-2">
          <p className="text-base font-semibold tabular-nums">{item.value}</p>
          <p className="text-[10px] uppercase tracking-wide text-muted-foreground">{item.label}</p>
        </div>
      ))}
    </div>
  );
}

function TablePreview() {
  return (
    <table className="w-full text-left text-xs">
      <thead>
        <tr className="border-b text-muted-foreground">
          <th className="py-1 font-medium">Enumerator</th>
          <th className="py-1 text-right font-medium">Clean</th>
          <th className="py-1 text-right font-medium">RED</th>
          <th className="py-1 text-right font-medium">AMBER</th>
        </tr>
      </thead>
      <tbody>
        {DEMO_TABLE.map((row) => (
          <tr key={row.name} className="border-b border-border/60">
            <td className="py-1">{row.name}</td>
            <td className="py-1 text-right tabular-nums">{row.clean}</td>
            <td className="py-1 text-right tabular-nums">{row.red}</td>
            <td className="py-1 text-right tabular-nums">{row.amber}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function RankingPreview() {
  return (
    <ol className="space-y-1 text-xs">
      {DEMO_RANKING.map((row, index) => (
        <li key={row.name} className="flex justify-between gap-3 rounded-md bg-background px-2 py-1.5">
          <span>
            {index + 1}. {row.name}
          </span>
          <span className="tabular-nums font-medium">{row.flagRate}%</span>
        </li>
      ))}
    </ol>
  );
}

function ProgressPreview() {
  return (
    <div className="space-y-2">
      {DEMO_PROGRESS.map((row) => {
        const pct = Math.round((row.value / row.target) * 100);
        return (
          <div key={row.label}>
            <div className="mb-0.5 flex justify-between text-[10px]">
              <span>{row.label}</span>
              <span className="tabular-nums text-muted-foreground">
                {row.value}/{row.target} ({pct}%)
              </span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-muted">
              <div className="h-full bg-teal-700" style={{ width: `${Math.min(100, pct)}%` }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function BarPreview({ stacked = false }: { stacked?: boolean }) {
  const data = stacked ? DEMO_STACKED : DEMO_BARS;
  const series = stacked
    ? [
        { key: "clean", label: "Clean", color: SERIES_COLORS[0] },
        { key: "amber", label: "Amber", color: SERIES_COLORS[1] },
        { key: "red", label: "Red", color: SERIES_COLORS[2] },
      ]
    : [
        { key: "red", label: "RED", color: SERIES_COLORS[2] },
        { key: "amber", label: "AMBER", color: SERIES_COLORS[1] },
      ];
  return (
    <MiniChart config={chartConfig(series)}>
      <BarChart data={data} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
        <CartesianGrid vertical={false} strokeDasharray="3 3" />
        <XAxis dataKey="tool" tickLine={false} axisLine={false} fontSize={10} />
        <YAxis tickLine={false} axisLine={false} fontSize={10} width={28} />
        <ChartTooltip content={<ChartTooltipContent />} />
        {series.map((item) => (
          <Bar
            key={item.key}
            dataKey={item.key}
            fill={`var(--color-${item.key})`}
            stackId={stacked ? "stack" : undefined}
            radius={2}
          />
        ))}
      </BarChart>
    </MiniChart>
  );
}

function LinePreview() {
  const series = [{ key: "submissions", label: "Submissions", color: SERIES_COLORS[0] }];
  return (
    <MiniChart config={chartConfig(series)}>
      <LineChart data={DEMO_LINE} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
        <CartesianGrid vertical={false} strokeDasharray="3 3" />
        <XAxis dataKey="day" tickLine={false} axisLine={false} fontSize={10} />
        <YAxis tickLine={false} axisLine={false} fontSize={10} width={28} />
        <ChartTooltip content={<ChartTooltipContent />} />
        <Line
          type="monotone"
          dataKey="submissions"
          stroke="var(--color-submissions)"
          strokeWidth={2}
          dot={false}
        />
      </LineChart>
    </MiniChart>
  );
}

function PiePreview() {
  const series = DEMO_PIE.map((row, index) => ({
    key: row.label.toLowerCase(),
    label: row.label,
    color: SERIES_COLORS[index % SERIES_COLORS.length],
  }));
  return (
    <MiniChart config={chartConfig(series)} className="aspect-square h-28 w-full max-w-[7.5rem]">
      <PieChart>
        <Pie data={DEMO_PIE} dataKey="value" nameKey="label" innerRadius={22} outerRadius={42}>
          {DEMO_PIE.map((_, index) => (
            <Cell key={index} fill={SERIES_COLORS[index % SERIES_COLORS.length]} />
          ))}
        </Pie>
        <ChartTooltip content={<ChartTooltipContent />} />
      </PieChart>
    </MiniChart>
  );
}

function NarrativePreview({
  type,
  body,
}: {
  type: "insight" | "warning" | "action_plan";
  body: string;
}) {
  const tone =
    type === "warning"
      ? "border-amber-300 bg-amber-50"
      : type === "action_plan"
        ? "border-teal-700 bg-teal-50"
        : "border-teal-600 bg-muted/40";
  return (
    <div className={`rounded-md border-l-4 px-3 py-2 text-xs ${tone}`}>
      <p className="mb-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
        {componentTitle(type)}
      </p>
      <p>{body}</p>
    </div>
  );
}

function TextPreview() {
  return (
    <p className="text-xs text-muted-foreground">
      This daily report summarizes submissions and data-quality flags for the active study day.
    </p>
  );
}

/** Compact, non-interactive sample render for one catalog component type. */
export function ComponentUsagePreview({ type }: { type: string }) {
  let body: ReactElement | null = null;
  switch (type) {
    case "metric":
      body = <MetricPreview />;
      break;
    case "kpi_group":
      body = <KpiGroupPreview />;
      break;
    case "table":
      body = <TablePreview />;
      break;
    case "ranking":
      body = <RankingPreview />;
      break;
    case "progress":
      body = <ProgressPreview />;
      break;
    case "bar_chart":
      body = <BarPreview />;
      break;
    case "stacked_bar_chart":
      body = <BarPreview stacked />;
      break;
    case "line_chart":
      body = <LinePreview />;
      break;
    case "pie_chart":
      body = <PiePreview />;
      break;
    case "insight":
      body = (
        <NarrativePreview
          type="insight"
          body="Flag rates rose on LIST tools; three enumerators account for most RED cases."
        />
      );
      break;
    case "warning":
      body = (
        <NarrativePreview
          type="warning"
          body="Two enumerators exceeded the 15% flag threshold today."
        />
      );
      break;
    case "action_plan":
      body = (
        <NarrativePreview
          type="action_plan"
          body="Coach Ravi on RED patterns; re-check LIST forms before end of day."
        />
      );
      break;
    case "text":
      body = <TextPreview />;
      break;
    default:
      body = (
        <p className="text-xs italic text-muted-foreground">No sample preview for this type yet.</p>
      );
  }

  return (
    <div className="pointer-events-none select-none rounded-md border border-dashed bg-muted/20 p-2" aria-hidden>
      {body}
    </div>
  );
}

/** Prefer showing visual previews for these types first in the help panel. */
export const PREVIEW_PRIORITY: string[] = [
  "metric",
  "kpi_group",
  "table",
  "ranking",
  "progress",
  "bar_chart",
  "line_chart",
  "pie_chart",
  "insight",
  "stacked_bar_chart",
  "warning",
  "action_plan",
  "text",
];

export function sortComponentTypes(types: string[]): string[] {
  return [...types].sort((a, b) => {
    const ai = PREVIEW_PRIORITY.indexOf(a);
    const bi = PREVIEW_PRIORITY.indexOf(b);
    const av = ai === -1 ? 999 : ai;
    const bv = bi === -1 ? 999 : bi;
    if (av !== bv) return av - bv;
    return a.localeCompare(b);
  });
}
