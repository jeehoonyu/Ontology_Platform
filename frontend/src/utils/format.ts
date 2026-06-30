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
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
