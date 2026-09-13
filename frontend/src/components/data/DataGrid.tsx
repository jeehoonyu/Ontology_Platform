import { useMemo, useState } from "react";
import {
  columnVisibilityFeature,
  createColumnHelper,
  createSortedRowModel,
  rowSortingFeature,
  sortFn_alphanumeric,
  tableFeatures,
  useTable
} from "@tanstack/react-table";
import { formatValue } from "../../utils/format";
import type { TableRow } from "../../types";
import { EmptyState, TABLE_ROW_LIMIT } from "./DataDisplay";

/**
 * The product's grid: a table a person can sort and trim to the columns they want.
 *
 * N7a of `GOAL_HONEST_UI_2026-09-11.md`, built on `@tanstack/react-table`. It is a
 * separate module from `DataTable` on purpose. `DataDisplay.tsx` is imported by
 * every screen, so a grid defined there would put the table library in the closure
 * all seventeen routes download; here it lands only in the routes that use it.
 *
 * It keeps everything N3 and N5 made true of the table it grows out of:
 *
 *   - every column any row has, not a sample;
 *   - a caption with the true count whenever it shows fewer rows than it was given;
 *   - every row reachable, forty a page.
 *
 * Paging is a slice over the sorted rows rather than the library's paginated row
 * model, and that is a choice about the gate as much as the grid:
 * `audit_table_truncation` sees a `.slice` and asks for the rendered total beside
 * it, and it cannot see a cut made inside a library's row model. The cut stays
 * where the gate can hold it to its caption.
 *
 * Hiding a column is counted the same way: the control reads `8 of 11 shown`, so a
 * narrower grid never looks like a dataset with fewer fields.
 */
const features = tableFeatures({
  rowSortingFeature,
  sortedRowModel: createSortedRowModel(),
  // Natural order, so "10" sorts after "9": cells are compared as the text they
  // display, which is what a person sorting by eye expects.
  sortFns: { alphanumeric: sortFn_alphanumeric },
  columnVisibilityFeature
});

const helper = createColumnHelper<typeof features, TableRow>();
// A fresh fallback array on every render would invalidate the row models each time.
const NO_ROWS: TableRow[] = [];

export function DataGrid({ rows, empty = "No records", label = "Scrollable data grid" }: {
  rows?: TableRow[];
  empty?: string;
  label?: string;
}) {
  const data = rows || NO_ROWS;
  const keys = useMemo(() => {
    const seen = new Set<string>();
    for (const row of data) Object.keys(row || {}).forEach((key) => seen.add(key));
    return Array.from(seen);
  }, [data]);
  // `helper.columns` is the library's own way to hand a column list to the table:
  // a plain array of string-valued accessors does not type-check against it.
  const columns = useMemo(() => helper.columns(keys.map((key) => helper.accessor((row) => formatValue(row[key]), {
    id: key,
    header: key,
    sortFn: "alphanumeric"
  }))), [keys]);
  const table = useTable({ features, columns, data });
  // Clamped rather than reset, for the reason `DataTable` gives: callers that
  // rebuild `rows` every render would otherwise throw a reader back to page one.
  const [page, setPage] = useState(0);

  // The shared empty state, not a raw `.empty` div: `audit_ui_states` ratchets the
  // hand-written ones down, and the grid's first version added one back.
  if (!data.length) return <EmptyState inline>{empty}</EmptyState>;

  const allRows = table.getRowModel().rows;
  const pages = Math.ceil(allRows.length / TABLE_ROW_LIMIT);
  const current = Math.min(page, pages - 1);
  const first = current * TABLE_ROW_LIMIT;
  const shown = allRows.slice(first, first + TABLE_ROW_LIMIT);
  const leafColumns = table.getAllLeafColumns();
  const visibleColumns = table.getVisibleLeafColumns();

  return (
    <>
      <details className="grid-columns">
        <summary>Columns · {visibleColumns.length.toLocaleString()} of {leafColumns.length.toLocaleString()} shown</summary>
        <div className="grid-columns-list">
          {leafColumns.map((column) => (
            <label key={column.id}>
              <input
                type="checkbox"
                checked={column.getIsVisible()}
                disabled={!column.getCanHide()}
                onChange={column.getToggleVisibilityHandler()}
              />
              {column.id}
            </label>
          ))}
        </div>
      </details>
      <div className="table-wrap" tabIndex={0} role="region" aria-label={label}>
        <table>
          {shown.length < allRows.length ? (
            <caption className="table-truncated">
              Showing {(first + 1).toLocaleString()}–{(first + shown.length).toLocaleString()} of {allRows.length.toLocaleString()} rows
            </caption>
          ) : null}
          <thead>
            {table.getHeaderGroups().map((group) => (
              <tr key={group.id}>
                {group.headers.map((header) => {
                  const sorted = header.column.getIsSorted();
                  return (
                    <th key={header.id} aria-sort={sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : "none"}>
                      <button type="button" className="grid-sort" onClick={header.column.getToggleSortingHandler()}>
                        <table.FlexRender header={header} />
                        <span aria-hidden="true">{sorted === "asc" ? " ▲" : sorted === "desc" ? " ▼" : ""}</span>
                      </button>
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {shown.map((row) => (
              <tr key={row.id}>
                {row.getVisibleCells().map((cell) => {
                  const text = String(cell.getValue() ?? "");
                  return <td key={cell.id} title={text}>{text}</td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {pages > 1 ? (
        <div className="table-pager">
          <button type="button" onClick={() => setPage(current - 1)} disabled={current === 0}>Previous rows</button>
          <button type="button" onClick={() => setPage(current + 1)} disabled={current >= pages - 1}>Next rows</button>
        </div>
      ) : null}
    </>
  );
}
