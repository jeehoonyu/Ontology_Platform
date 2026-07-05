import { api, postJson } from "../api";
import type { JsonObject, JsonValue, TableRow } from "../types";

// ---------------------------------------------------------------------------
// Object types (field discovery for the Object Explorer charts)
// ---------------------------------------------------------------------------

export interface ObjectTypeSummary {
  id: string;
  display_name: string;
  description?: string | null;
  properties?: JsonObject;
  created_at?: number;
  updated_at?: number;
}

export function listObjectTypes(): Promise<ObjectTypeSummary[]> {
  return api<ObjectTypeSummary[]>("/object-types");
}

/**
 * Extract candidate property field names from an object type's schema.
 * Mirrors the backend (_object_schema_columns): the schema is either a flat
 * `{field: spec}` map or a nested `{properties: {field: spec}}` map.
 */
export function fieldNames(objectType?: ObjectTypeSummary | null): string[] {
  const props = objectType?.properties;
  if (!props || typeof props !== "object" || Array.isArray(props)) return [];
  const nested = (props as JsonObject).properties;
  const source =
    nested && typeof nested === "object" && !Array.isArray(nested)
      ? (nested as JsonObject)
      : (props as JsonObject);
  return Object.keys(source);
}

// ---------------------------------------------------------------------------
// Histogram — numeric bins OR categorical value counts (auto-detected)
// ---------------------------------------------------------------------------

export interface HistogramBucket {
  range?: number[]; // present for numeric buckets: [lo, hi]
  value?: string; // present for categorical buckets
  count: number;
}

export interface HistogramResponse {
  type: string; // "numeric" | "categorical"
  field: string;
  min?: number;
  max?: number;
  buckets: HistogramBucket[];
}

export function fetchHistogram(objectTypeId: string, field: string, bins: number): Promise<HistogramResponse> {
  return postJson<HistogramResponse>("/object-explorer/histogram", {
    object_type_id: objectTypeId,
    field,
    bins
  });
}

// ---------------------------------------------------------------------------
// Listogram — categorical counts with keep/exclude filtering
// ---------------------------------------------------------------------------

export interface CategoryCount {
  value: string;
  count: number;
}

export interface ListogramResponse {
  field: string;
  categories: CategoryCount[];
  total: number;
}

export function fetchListogram(
  objectTypeId: string,
  field: string,
  keep?: string[],
  exclude?: string[]
): Promise<ListogramResponse> {
  return postJson<ListogramResponse>("/object-explorer/listogram", {
    object_type_id: objectTypeId,
    field,
    keep,
    exclude
  });
}

// ---------------------------------------------------------------------------
// Statistics table — per-field count/distinct/min/max/avg/sum
// ---------------------------------------------------------------------------

export interface StatisticsRow {
  [key: string]: JsonValue | undefined;
  field: string;
  count: number;
  distinct: number;
  min?: number;
  max?: number;
  avg?: number;
  sum?: number;
}

export interface StatisticsTableResponse {
  object_type_id: string;
  rows: StatisticsRow[];
}

export function fetchStatisticsTable(objectTypeId: string, fields: string[]): Promise<StatisticsTableResponse> {
  return postJson<StatisticsTableResponse>("/object-explorer/statistics-table", {
    object_type_id: objectTypeId,
    fields
  });
}

// ---------------------------------------------------------------------------
// Single statistic — one aggregate value over one field
// ---------------------------------------------------------------------------

export type StatisticName = "count" | "sum" | "avg" | "min" | "max" | "distinct";

export interface SingleStatisticResponse {
  field: string;
  statistic: string;
  value: number | null;
}

export function fetchSingleStatistic(
  objectTypeId: string,
  field: string,
  statistic: StatisticName
): Promise<SingleStatisticResponse> {
  return postJson<SingleStatisticResponse>("/object-explorer/single-statistic", {
    object_type_id: objectTypeId,
    field,
    statistic
  });
}

// ---------------------------------------------------------------------------
// Grid plot — two-way (row_field x col_field) count grid
// ---------------------------------------------------------------------------

export interface GridCell {
  row: string;
  col: string;
  count: number;
}

export interface GridPlotResponse {
  row_field: string;
  col_field: string;
  row_values: string[];
  col_values: string[];
  cells: GridCell[];
}

export function fetchGridPlot(objectTypeId: string, rowField: string, colField: string): Promise<GridPlotResponse> {
  return postJson<GridPlotResponse>("/object-explorer/grid-plot", {
    object_type_id: objectTypeId,
    row_field: rowField,
    col_field: colField
  });
}

// ---------------------------------------------------------------------------
// Contour board runner — stateless board pipeline over supplied records
// ---------------------------------------------------------------------------

export interface ContourApplyResponse {
  row_count: number;
  records: TableRow[];
  trace: TableRow[];
  summary?: JsonObject;
  distribution?: JsonObject;
}

export function applyContour(records: TableRow[], boards: JsonObject[]): Promise<ContourApplyResponse> {
  return postJson<ContourApplyResponse>("/analytics/contour/apply", { records, boards });
}
