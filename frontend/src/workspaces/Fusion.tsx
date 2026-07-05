import { useEffect, useRef, useState, type CSSProperties } from "react";
import { Page } from "../components/workbench/Workbench";
import {
  EmptyState,
  ErrorBanner,
  LoadingState,
  Metric,
  Panel,
  StatusBadge
} from "../components/data/DataDisplay";
import { useAsyncState } from "../hooks/useAsyncState";
import { classNames } from "../utils/format";
import {
  createSheet,
  createWorkbook,
  evaluateFormula,
  evaluateSheet,
  getSheet,
  isFusionError,
  listDataAssets,
  listSheets,
  listWorkbooks,
  lookup,
  saveCells,
  type DataAssetSummary,
  type FusionValue,
  type LookupResult,
  type Sheet,
  type Workbook
} from "../api/fusionApi";

// Grid geometry — columns A..H, rows 1..N (N grows to fit loaded cells).
const COLS = ["A", "B", "C", "D", "E", "F", "G", "H"];
const DEFAULT_ROWS = 12;
const ADD_ROWS = 6;

const ERROR_STYLE: CSSProperties = { color: "#c0362c", fontWeight: 700 };

function valueToString(value: FusionValue): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "boolean") return value ? "TRUE" : "FALSE";
  return String(value);
}

function rowOfRef(ref: string): number {
  const match = /([0-9]+)$/.exec(ref);
  return match ? parseInt(match[1], 10) : 0;
}

// ---------------------------------------------------------------------------
// Workspace
// ---------------------------------------------------------------------------

export function Fusion() {
  const [refreshKey, setRefreshKey] = useState(0);
  const reload = () => setRefreshKey((key) => key + 1);
  const [selectedWorkbookId, setSelectedWorkbookId] = useState("");
  const [selectedSheetId, setSelectedSheetId] = useState("");
  const [newWorkbookName, setNewWorkbookName] = useState("");
  const [newSheetName, setNewSheetName] = useState("");
  const [actionError, setActionError] = useState("");
  const [busy, setBusy] = useState(false);

  const workbooks = useAsyncState<Workbook[]>(listWorkbooks, [refreshKey]);
  const sheets = useAsyncState<Sheet[]>(
    () => (selectedWorkbookId ? listSheets(selectedWorkbookId) : Promise.resolve([])),
    [selectedWorkbookId, refreshKey]
  );
  const datasets = useAsyncState<DataAssetSummary[]>(listDataAssets, [refreshKey]);

  useEffect(() => {
    if (!selectedWorkbookId && workbooks.value && workbooks.value.length) {
      setSelectedWorkbookId(workbooks.value[0].id);
    }
  }, [workbooks.value, selectedWorkbookId]);

  // Keep a valid sheet selected for the active workbook.
  useEffect(() => {
    const list = sheets.value;
    if (!list) return;
    if (list.length && !list.some((sheet) => sheet.id === selectedSheetId)) {
      setSelectedSheetId(list[0].id);
    } else if (!list.length) {
      setSelectedSheetId("");
    }
  }, [sheets.value, selectedSheetId]);

  async function onCreateWorkbook() {
    const name = newWorkbookName.trim();
    if (!name) return;
    setActionError("");
    setBusy(true);
    try {
      const created = await createWorkbook({ display_name: name });
      setNewWorkbookName("");
      setSelectedWorkbookId(created.id);
      setSelectedSheetId("");
      reload();
    } catch (error) {
      setActionError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function onCreateSheet() {
    const name = newSheetName.trim();
    if (!name || !selectedWorkbookId) return;
    setActionError("");
    setBusy(true);
    try {
      const created = await createSheet({ workbook_id: selectedWorkbookId, name });
      setNewSheetName("");
      setSelectedSheetId(created.id);
      reload();
    } catch (error) {
      setActionError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const workbookList = workbooks.value || [];
  const sheetList = sheets.value || [];
  const activeSheet = sheetList.find((sheet) => sheet.id === selectedSheetId);

  return (
    <Page
      title="Fusion"
      subtitle="Spreadsheets backed by a deterministic formula engine. Type =formulas into A1-referenced cells, evaluate them, test formulas ad-hoc, and pull values from datasets with LOOKUP."
    >
      <div className="grid metrics">
        <Metric label="Workbooks" value={workbookList.length} />
        <Metric label="Sheets in workbook" value={sheetList.length} />
        <Metric label="Datasets" value={datasets.value?.length ?? 0} />
      </div>

      <ErrorBanner message={actionError || workbooks.error || sheets.error} />
      {(workbooks.loading || sheets.loading) && <LoadingState label="Loading Fusion workbooks..." />}

      <div className="two-col">
        <Panel title={`Workbooks ${workbookList.length}`}>
          <div className="button-row" style={{ flexWrap: "wrap" }}>
            <input
              className="compact-input"
              placeholder="New workbook name"
              value={newWorkbookName}
              onChange={(event) => setNewWorkbookName(event.target.value)}
            />
            <button onClick={onCreateWorkbook} disabled={busy || !newWorkbookName.trim()}>Create workbook</button>
          </div>
          {workbookList.length ? (
            workbookList.map((workbook) => (
              <button
                key={workbook.id}
                className={classNames("resource-row", selectedWorkbookId === workbook.id && "selected")}
                onClick={() => {
                  setSelectedWorkbookId(workbook.id);
                  setSelectedSheetId("");
                }}
              >
                <strong>{workbook.display_name || workbook.id}</strong>
                <span>{workbook.owner ? `owner: ${workbook.owner}` : workbook.id}</span>
              </button>
            ))
          ) : (
            <EmptyState title="No workbooks yet" description="Create a workbook, then add a sheet and start entering cells." />
          )}
        </Panel>

        <Panel title={`Sheets ${sheetList.length}`}>
          {selectedWorkbookId ? (
            <>
              <div className="button-row" style={{ flexWrap: "wrap" }}>
                <input
                  className="compact-input"
                  placeholder="New sheet name"
                  value={newSheetName}
                  onChange={(event) => setNewSheetName(event.target.value)}
                />
                <button onClick={onCreateSheet} disabled={busy || !newSheetName.trim()}>Create sheet</button>
              </div>
              {sheetList.length ? (
                sheetList.map((sheet) => (
                  <button
                    key={sheet.id}
                    className={classNames("resource-row", selectedSheetId === sheet.id && "selected")}
                    onClick={() => setSelectedSheetId(sheet.id)}
                  >
                    <strong>{sheet.name}</strong>
                    <span>{sheet.id}</span>
                  </button>
                ))
              ) : (
                <EmptyState title="No sheets yet" description="Create a sheet to open the editable grid." />
              )}
            </>
          ) : (
            <EmptyState title="Select a workbook" description="Pick a workbook on the left to list and create its sheets." />
          )}
        </Panel>
      </div>

      <Panel title={activeSheet ? `Grid — ${activeSheet.name}` : "Grid"}>
        {selectedSheetId ? (
          <SheetGrid key={selectedSheetId} sheetId={selectedSheetId} />
        ) : (
          <EmptyState title="No sheet selected" description="Create or select a sheet to edit its cells." />
        )}
      </Panel>

      <div className="two-col">
        <FormulaTester />
        <LookupPanel datasets={datasets.value || []} />
      </div>
    </Page>
  );
}

// ---------------------------------------------------------------------------
// Editable grid
// ---------------------------------------------------------------------------

function SheetGrid({ sheetId }: { sheetId: string }) {
  const [raw, setRaw] = useState<Record<string, string>>({});
  const [values, setValues] = useState<Record<string, FusionValue>>({});
  const [editingRef, setEditingRef] = useState("");
  const [rowCount, setRowCount] = useState(DEFAULT_ROWS);
  const [showFormulas, setShowFormulas] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const dirty = useRef<Set<string>>(new Set());

  useEffect(() => {
    let cancelled = false;
    setError("");
    setBusy(true);
    dirty.current = new Set();
    getSheet(sheetId)
      .then(async (detail) => {
        if (cancelled) return;
        const nextRaw: Record<string, string> = {};
        let maxRow = DEFAULT_ROWS;
        for (const cell of detail.cells) {
          nextRaw[cell.ref] = cell.raw;
          maxRow = Math.max(maxRow, rowOfRef(cell.ref));
        }
        setRaw(nextRaw);
        setRowCount(maxRow);
        const evaluation = await evaluateSheet(sheetId);
        if (!cancelled) setValues(evaluation.values);
      })
      .catch((err) => !cancelled && setError((err as Error).message))
      .finally(() => !cancelled && setBusy(false));
    return () => {
      cancelled = true;
    };
  }, [sheetId]);

  async function recalculate() {
    setBusy(true);
    setError("");
    try {
      const evaluation = await evaluateSheet(sheetId);
      setValues(evaluation.values);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function onChangeCell(ref: string, next: string) {
    setRaw((current) => ({ ...current, [ref]: next }));
    dirty.current.add(ref);
  }

  async function onBlurCell(ref: string, next: string) {
    setEditingRef("");
    if (!dirty.current.has(ref)) return;
    dirty.current.delete(ref);
    setRaw((current) => ({ ...current, [ref]: next }));
    setBusy(true);
    setError("");
    try {
      await saveCells(sheetId, [{ ref, raw: next }]);
      const evaluation = await evaluateSheet(sheetId);
      setValues(evaluation.values);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function cellDisplay(ref: string): string {
    if (editingRef === ref) return raw[ref] ?? "";
    if (showFormulas) return raw[ref] ?? "";
    if (ref in values) return valueToString(values[ref]);
    return raw[ref] ?? "";
  }

  const rows: number[] = [];
  for (let r = 1; r <= rowCount; r += 1) rows.push(r);

  return (
    <>
      <div className="button-row" style={{ flexWrap: "wrap", alignItems: "center" }}>
        <button onClick={recalculate} disabled={busy}>Recalculate</button>
        <button onClick={() => setRowCount((count) => count + ADD_ROWS)} disabled={busy}>Add rows</button>
        <label style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <input type="checkbox" checked={showFormulas} onChange={(event) => setShowFormulas(event.target.checked)} />
          Show formulas
        </label>
        <span className="empty" style={{ margin: 0 }}>
          Editing a cell shows its raw value; blur to save and recompute. Enter <code>=</code> to start a formula.
        </span>
      </div>
      <ErrorBanner message={error} />
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th style={{ width: 44, maxWidth: 44 }} />
              {COLS.map((col) => (
                <th key={col} style={{ textAlign: "center" }}>{col}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row}>
                <th style={{ width: 44, maxWidth: 44, textAlign: "center" }}>{row}</th>
                {COLS.map((col) => {
                  const ref = `${col}${row}`;
                  const showsError = editingRef !== ref && !showFormulas && isFusionError(values[ref]);
                  return (
                    <td key={ref} style={{ padding: 0, maxWidth: 160 }}>
                      <input
                        aria-label={ref}
                        value={cellDisplay(ref)}
                        onFocus={() => setEditingRef(ref)}
                        onChange={(event) => onChangeCell(ref, event.target.value)}
                        onBlur={(event) => onBlurCell(ref, event.target.value)}
                        style={{
                          width: "100%",
                          boxSizing: "border-box",
                          border: "none",
                          background: "transparent",
                          padding: "6px 8px",
                          font: "inherit",
                          ...(showsError ? ERROR_STYLE : null)
                        }}
                      />
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Stateless formula tester
// ---------------------------------------------------------------------------

interface FormulaEntry {
  ref: string;
  raw: string;
}

function FormulaTester() {
  const [entries, setEntries] = useState<FormulaEntry[]>([
    { ref: "A1", raw: "10" },
    { ref: "A2", raw: "=A1*2" }
  ]);
  const [result, setResult] = useState<Record<string, FusionValue> | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  function updateEntry(index: number, patch: Partial<FormulaEntry>) {
    setEntries((current) => current.map((entry, i) => (i === index ? { ...entry, ...patch } : entry)));
  }

  function addEntry() {
    setEntries((current) => [...current, { ref: "", raw: "" }]);
  }

  function removeEntry(index: number) {
    setEntries((current) => current.filter((_, i) => i !== index));
  }

  async function run() {
    const cells: Record<string, string> = {};
    for (const entry of entries) {
      const ref = entry.ref.trim();
      if (ref) cells[ref] = entry.raw;
    }
    setBusy(true);
    setError("");
    try {
      const evaluation = await evaluateFormula(cells);
      setResult(evaluation.values);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel title="Formula Tester" action={<button onClick={run} disabled={busy}>Evaluate</button>}>
      <p className="empty" style={{ marginTop: 0 }}>
        Stateless <code>/fusion/formula/evaluate</code> — enter a ref and a literal or <code>=formula</code> for each cell.
      </p>
      {entries.map((entry, index) => (
        <div key={index} className="button-row" style={{ flexWrap: "nowrap", alignItems: "center" }}>
          <input
            className="compact-input"
            style={{ maxWidth: 80 }}
            placeholder="A1"
            value={entry.ref}
            onChange={(event) => updateEntry(index, { ref: event.target.value })}
          />
          <input
            className="compact-input"
            style={{ flex: 1 }}
            placeholder="=A1*2"
            value={entry.raw}
            onChange={(event) => updateEntry(index, { raw: event.target.value })}
          />
          <button onClick={() => removeEntry(index)} disabled={entries.length <= 1}>Remove</button>
        </div>
      ))}
      <div className="button-row">
        <button onClick={addEntry}>Add cell</button>
      </div>
      <ErrorBanner message={error} />
      {result ? <ValueTable values={result} empty="No cells evaluated." /> : null}
    </Panel>
  );
}

// ---------------------------------------------------------------------------
// Lookup panel
// ---------------------------------------------------------------------------

function LookupPanel({ datasets }: { datasets: DataAssetSummary[] }) {
  const [datasetId, setDatasetId] = useState("");
  const [keyField, setKeyField] = useState("");
  const [keyValue, setKeyValue] = useState("");
  const [valueField, setValueField] = useState("");
  const [result, setResult] = useState<LookupResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function run() {
    if (!datasetId || !keyField.trim() || !valueField.trim()) return;
    setBusy(true);
    setError("");
    try {
      const res = await lookup({
        dataset_id: datasetId,
        key_field: keyField.trim(),
        key_value: keyValue,
        value_field: valueField.trim()
      });
      setResult(res);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const canRun = Boolean(datasetId && keyField.trim() && valueField.trim());

  return (
    <Panel title="Lookup" action={<button onClick={run} disabled={busy || !canRun}>Lookup</button>}>
      <p className="empty" style={{ marginTop: 0 }}>
        First <code>value_field</code> where <code>key_field == key_value</code> in a dataset (<code>/fusion/lookup</code>).
      </p>
      <label style={{ display: "block", marginBottom: 8 }}>
        <span style={{ display: "block", marginBottom: 4 }}>Dataset</span>
        <select value={datasetId} onChange={(event) => setDatasetId(event.target.value)} style={{ width: "100%" }}>
          <option value="">Choose dataset</option>
          {datasets.map((dataset) => (
            <option key={dataset.id} value={dataset.id}>{dataset.display_name || dataset.id}</option>
          ))}
        </select>
      </label>
      <div className="button-row" style={{ flexWrap: "wrap" }}>
        <input className="compact-input" placeholder="key_field" value={keyField} onChange={(event) => setKeyField(event.target.value)} />
        <input className="compact-input" placeholder="key_value" value={keyValue} onChange={(event) => setKeyValue(event.target.value)} />
        <input className="compact-input" placeholder="value_field" value={valueField} onChange={(event) => setValueField(event.target.value)} />
      </div>
      <ErrorBanner message={error} />
      {result ? (
        <div className="button-row" style={{ alignItems: "center", gap: 10 }}>
          <StatusBadge value={result.found ? "found" : "not found"} />
          <strong style={isFusionError(result.value) ? ERROR_STYLE : undefined}>{valueToString(result.value) || "(empty)"}</strong>
          <span className="empty" style={{ margin: 0 }}>{result.match_count} match{result.match_count === 1 ? "" : "es"}</span>
        </div>
      ) : null}
    </Panel>
  );
}

// ---------------------------------------------------------------------------
// Shared value table (ref -> computed value, error tokens highlighted)
// ---------------------------------------------------------------------------

function ValueTable({ values, empty }: { values: Record<string, FusionValue>; empty: string }) {
  const entries = Object.entries(values);
  if (!entries.length) return <div className="empty">{empty}</div>;
  return (
    <div className="table-wrap">
      <table style={{ minWidth: 0 }}>
        <thead>
          <tr>
            <th>ref</th>
            <th>value</th>
          </tr>
        </thead>
        <tbody>
          {entries.map(([ref, value]) => (
            <tr key={ref}>
              <td>{ref}</td>
              <td style={isFusionError(value) ? ERROR_STYLE : undefined}>{valueToString(value)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
