/** Format DQA flag evaluation details for inline display next to the rule message. */

type Details = Record<string, unknown> | null | undefined;

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function shortField(ref: unknown): string | null {
  if (typeof ref !== "string" || !ref.trim()) return null;
  const parts = ref.split("/").filter(Boolean);
  return parts[parts.length - 1] || ref;
}

function displayValue(value: unknown): string {
  if (value == null || value === "") return "—";
  if (typeof value === "number" && Number.isFinite(value)) {
    return Number.isInteger(value) ? String(value) : value.toFixed(1);
  }
  const text = String(value);
  // Prefer compact local datetime for ISO timestamps.
  if (/^\d{4}-\d{2}-\d{2}T/.test(text)) {
    const d = new Date(text);
    if (!Number.isNaN(d.getTime())) {
      return d.toLocaleString(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
    }
  }
  return text;
}

/** Walk composite/nested detail trees to the leaf failure details. */
export function leafFailureDetails(details: Details): Record<string, unknown> {
  const root = asRecord(details);
  if (!root) return {};
  const op = String(root.op || "");
  if (op === "not") {
    const inner = asRecord(root.inner);
    if (inner) return leafFailureDetails(inner);
  }
  if (op === "all") {
    const failed = asRecord(root.failed);
    if (failed) return leafFailureDetails(failed);
  }
  if (op === "if_then") {
    const thenPart = asRecord(root.then);
    if (thenPart) return leafFailureDetails(thenPart);
  }
  if (op === "any") {
    // any failures usually don't nest a single failed child in details
  }
  return root;
}

function fieldLabels(details: Record<string, unknown>): [string | null, string | null] {
  const highlights = Array.isArray(details.highlightFields)
    ? details.highlightFields.map(shortField).filter(Boolean)
    : [];
  const left =
    shortField(details.field) ||
    (typeof highlights[0] === "string" ? highlights[0] : null) ||
    null;
  const right =
    shortField(details.field_b) ||
    (typeof highlights[1] === "string" ? highlights[1] : null) ||
    null;
  return [left, right];
}

/**
 * Compact failure values for the Message column, e.g.:
 * - "A10=11, D4=21"
 * - "start_time=…, end_time=…, duration=73.3 min (allowed 90–150)"
 */
export function formatFlagFailureDetails(details: Details): string | null {
  const root = asRecord(details);
  if (!root) return null;
  const leaf = { ...leafFailureDetails(root) };
  // highlightFields are attached on the outer flag payload — keep them for labels
  if (!leaf.highlightFields && root.highlightFields) {
    leaf.highlightFields = root.highlightFields;
  }
  const op = String(leaf.op || "");
  if (!op) return null;

  if (op === "duration_minutes_gte") {
    const parts = [
      `start_time=${displayValue(leaf.start)}`,
      `end_time=${displayValue(leaf.end)}`,
    ];
    if (leaf.minutes != null) {
      const band =
        leaf.min != null || leaf.max != null
          ? ` (allowed ${displayValue(leaf.min)}–${displayValue(leaf.max)})`
          : "";
      parts.push(`duration=${displayValue(leaf.minutes)} min${band}`);
    }
    return parts.join(", ");
  }

  if (["equals", "not_equals", "gt", "lt", "gte", "lte"].includes(op)) {
    const [left, right] = fieldLabels(leaf);
    const rightVal = leaf.bound ?? leaf.expected;
    const bits: string[] = [];
    if (left) bits.push(`${left}=${displayValue(leaf.value)}`);
    else if (leaf.value != null) bits.push(`value=${displayValue(leaf.value)}`);
    if (right) bits.push(`${right}=${displayValue(rightVal)}`);
    else if (rightVal != null) bits.push(`expected=${displayValue(rightVal)}`);
    return bits.length ? bits.join(", ") : null;
  }

  if (op === "required" || op === "blank") {
    const [left] = fieldLabels(leaf);
    const name = left || "field";
    return `${name}=${displayValue(leaf.value)}`;
  }

  if (op === "between") {
    const [left] = fieldLabels(leaf);
    const name = left || "value";
    return `${name}=${displayValue(leaf.value)} (allowed ${displayValue(leaf.min)}–${displayValue(leaf.max)})`;
  }

  if (op === "in" || op === "equals_any" || op === "not_in") {
    const [left] = fieldLabels(leaf);
    const name = left || "value";
    const expected = leaf.expected ?? leaf.forbidden;
    return `${name}=${displayValue(leaf.value)}${
      expected != null ? `, expected=${displayValue(Array.isArray(expected) ? expected.join("|") : expected)}` : ""
    }`;
  }

  if (leaf.value != null) {
    const [left] = fieldLabels(leaf);
    return left ? `${left}=${displayValue(leaf.value)}` : `value=${displayValue(leaf.value)}`;
  }

  if (leaf.minutes != null) {
    return `duration=${displayValue(leaf.minutes)} min`;
  }

  return null;
}
