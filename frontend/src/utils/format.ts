import type { TableRow } from "../types";

export function classNames(...parts: Array<string | false | undefined>) {
  return parts.filter(Boolean).join(" ");
}

export function asString(value: unknown, fallback = ""): string {
  if (typeof value === "string") return value;
  if (value === null || value === undefined) return fallback;
  return String(value);
}

export function asRows(value: unknown): TableRow[] {
  return Array.isArray(value)
    ? value.filter((item): item is TableRow => item !== null && typeof item === "object" && !Array.isArray(item))
    : [];
}

export function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (Array.isArray(value)) {
    if (!value.length) return "0 items";
    if (value.length <= 3 && value.every((item) => item === null || ["string", "number", "boolean"].includes(typeof item))) {
      return value.map((item) => asString(item)).join(", ");
    }
    return `${value.length} items`;
  }
  if (typeof value === "object") {
    const record = value as Record<string, unknown>;
    const label = record.display_name || record.name || record.title || record.label || record.id;
    if (label !== undefined) return asString(label);
    const keys = Object.keys(record);
    return keys.length ? `${keys.length} fields` : "empty";
  }
  return String(value);
}
