import { api, postJson } from "../api";

// ---------------------------------------------------------------------------
// Fusion — spreadsheets, a deterministic formula engine, and dataset lookups.
// Backend: oms/app/fusion_ops.py (router mounted same-origin).
// ---------------------------------------------------------------------------

/** A computed / raw cell value. The engine renders booleans as "TRUE"/"FALSE"
 * strings and integers as numbers, so in practice this is number | string,
 * but we keep the union wide for safety. Error tokens (#DIV/0!, #CYCLE!, ...)
 * arrive as plain strings. */
export type FusionValue = string | number | boolean | null;

/** Spreadsheet error tokens the engine can emit (fusion_ops.ERROR_TOKENS). */
export const FUSION_ERROR_TOKENS: ReadonlySet<string> = new Set([
  "#REF!",
  "#DIV/0!",
  "#CYCLE!",
  "#NAME?",
  "#VALUE!",
  "#ERR!",
  "#N/A"
]);

export function isFusionError(value: FusionValue): boolean {
  return typeof value === "string" && FUSION_ERROR_TOKENS.has(value);
}

// --- Workbooks -------------------------------------------------------------

export interface Workbook {
  id: string;
  display_name: string;
  owner?: string | null;
  created_at: number;
  updated_at: number;
}

export interface WorkbookCreate {
  id?: string;
  display_name: string;
  owner?: string;
}

export function listWorkbooks(): Promise<Workbook[]> {
  return api<Workbook[]>("/fusion/workbooks");
}

export function createWorkbook(body: WorkbookCreate): Promise<Workbook> {
  return postJson<Workbook>("/fusion/workbooks", body);
}

// --- Sheets ----------------------------------------------------------------

export interface Sheet {
  id: string;
  workbook_id: string;
  name: string;
  created_at: number;
}

export interface SheetCreate {
  id?: string;
  workbook_id: string;
  name: string;
}

export function listSheets(workbookId: string): Promise<Sheet[]> {
  return api<Sheet[]>(`/fusion/workbooks/${encodeURIComponent(workbookId)}/sheets`);
}

export function createSheet(body: SheetCreate): Promise<Sheet> {
  return postJson<Sheet>("/fusion/sheets", body);
}

// --- Cells -----------------------------------------------------------------

export interface CellSpec {
  ref: string;
  raw: string;
}

export interface CellRead extends CellSpec {
  id: string;
  sheet_id: string;
}

/** GET /fusion/sheets/{id} — persisted raw cells for a sheet. */
export interface SheetDetail {
  id: string;
  name: string;
  workbook_id: string;
  cells: CellSpec[];
}

/** POST /fusion/sheets/{id}/evaluate — computed values by A1 ref. */
export interface SheetEvaluation {
  sheet_id: string;
  values: Record<string, FusionValue>;
  cells: Array<{ ref: string; raw: string; value: FusionValue }>;
}

export interface StatelessEvaluation {
  values: Record<string, FusionValue>;
}

export function getSheet(sheetId: string): Promise<SheetDetail> {
  return api<SheetDetail>(`/fusion/sheets/${encodeURIComponent(sheetId)}`);
}

/** PUT the raw values (literals or "=formula") for one or more cells. */
export function saveCells(sheetId: string, cells: CellSpec[]): Promise<CellRead[]> {
  return api<CellRead[]>(`/fusion/sheets/${encodeURIComponent(sheetId)}/cells`, {
    method: "PUT",
    body: JSON.stringify({ cells })
  });
}

/** Compute every cell in the sheet (formulas resolve against saved cells). */
export function evaluateSheet(sheetId: string): Promise<SheetEvaluation> {
  return api<SheetEvaluation>(`/fusion/sheets/${encodeURIComponent(sheetId)}/evaluate`, { method: "POST" });
}

/** Stateless evaluation of an ad-hoc { ref: raw } map. */
export function evaluateFormula(cells: Record<string, string>): Promise<StatelessEvaluation> {
  return postJson<StatelessEvaluation>("/fusion/formula/evaluate", { cells });
}

// --- Lookup ----------------------------------------------------------------

export interface LookupRequest {
  dataset_id: string;
  key_field: string;
  key_value: string;
  value_field: string;
  filters?: Record<string, unknown>;
}

export interface LookupResult {
  found: boolean;
  value: FusionValue;
  match_count: number;
}

export function lookup(body: LookupRequest): Promise<LookupResult> {
  return postJson<LookupResult>("/fusion/lookup", body);
}

// --- Datasets (picker source) ---------------------------------------------

/** Minimal projection of GET /data-assets used to populate the lookup picker. */
export interface DataAssetSummary {
  id: string;
  display_name?: string;
}

export function listDataAssets(): Promise<DataAssetSummary[]> {
  return api<DataAssetSummary[]>("/data-assets");
}
