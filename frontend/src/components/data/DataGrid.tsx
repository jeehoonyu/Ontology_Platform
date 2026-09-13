import { useEffect, useId, useMemo, useRef, useState } from "react";
import {
  columnFilteringFeature,
  columnOrderingFeature,
  columnPinningFeature,
  columnSizingFeature,
  columnVisibilityFeature,
  createColumnHelper,
  createFilteredRowModel,
  createSortedRowModel,
  filterFn_includesString,
  rowSortingFeature,
  sortFn_alphanumeric,
  tableFeatures,
  useTable,
  type ColumnFiltersState
} from "@tanstack/react-table";
import { formatValue } from "../../utils/format";
import type { TableRow } from "../../types";
import { EmptyState, TABLE_ROW_LIMIT } from "./DataDisplay";

/**
 * The product's grid: a table a person can sort, trim, widen, reorder, pin and filter.
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
 *
 * N7b adds width, place and pin, each from a control that is not a drag: a width
 * select, Earlier and Later buttons, and a Pin checkbox, in each column's row of
 * the same disclosure. There is no drag handle. The library's resize handler puts
 * its listeners on `document`, where `audit_drag_affordances` cannot see them, and
 * it has no Escape, so a drag waits for a condition of its own. Nothing is saved:
 * a saved arrangement is a saved view, which is its own scope.
 *
 * N7c adds a "contains" filter per column, and is the one cut here that the gate
 * cannot see in a `.slice`: the library drops the rows. So whenever a filter applies,
 * the grid counts what matched against every row it was given -- the model from
 * before filtering -- and `audit_table_truncation` reads that binding. A filter on a
 * hidden column still applies, and is named as one. There is no row selection:
 * nothing in the product acts on selected rows, and a checkbox that does nothing is
 * the first defect this goal removes.
 *
 * A filter matches the text a cell shows, lowercased on both sides. So `1` matches
 * `10`, `BREAKING` matches `NON_BREAKING`, an empty cell never matches, and a list
 * or object matches its summary (`3 items`), not its contents.
 *
 * Library behaviour this relies on, read in the installed source:
 *
 *   - `column.getIndex()` with no argument is not split by pin region. Every call
 *     here passes the region.
 *   - Pinning never writes `columnOrder`, so unpinning puts a column back where it
 *     was. A non-empty `columnOrder` puts its ids first, in its order, whatever
 *     order the rows now list their fields in.
 *   - Filtering runs before sorting, and a filter on a column that no longer exists
 *     cuts nothing but stays in state.
 */
const features = tableFeatures({
  rowSortingFeature,
  sortedRowModel: createSortedRowModel(),
  // Natural order, so "10" sorts after "9": cells are compared as the text they
  // display, which is what a person sorting by eye expects.
  sortFns: { alphanumeric: sortFn_alphanumeric },
  columnVisibilityFeature,
  columnSizingFeature,
  columnOrderingFeature,
  columnPinningFeature,
  // Not columnResizingFeature: its only entry point is a drag.
  columnFilteringFeature,
  filteredRowModel: createFilteredRowModel(),
  // By name rather than through the deprecated registry. This saves no bytes:
  // `createFilteredRowModel` imports every built-in filter function itself.
  filterFns: { includesString: filterFn_includesString }
  // Not globalFilteringFeature: by default it searches hidden columns too.
});

const helper = createColumnHelper<typeof features, TableRow>();
// A fresh fallback array on every render would invalidate the row models each time.
const NO_ROWS: TableRow[] = [];
// Widths come only from these presets, so the select's value is always one of its options.
const COLUMN_WIDTHS: Array<[string, number]> = [["Narrow", 100], ["Default", 180], ["Wide", 280], ["Widest", 400]];
const DEFAULT_COLUMN_PX = 180;

type NoticeKind = "moved" | "first" | "last" | "hidden" | "shown" | "concealed" | "pinned" | "unpinned" | "width" | "reset" | "unchanged";
type Notice = { seq: number; kind: NoticeKind; id?: string };
type FilterNoticeKind = "filtered" | "unfiltered" | "none" | "cleared";
type FilterNotice = { seq: number; kind: FilterNoticeKind; id?: string };

// Filter by id, then splice: `audit_table_truncation` reads a `.slice` as a cut.
function moveBeside(ids: string[], id: string, neighbour: string, after: boolean): string[] {
  const rest = ids.filter((item) => item !== id);
  rest.splice(rest.indexOf(neighbour) + (after ? 1 : 0), 0, id);
  return rest;
}

// The same array when nothing in it is stale, so an unchanged slice stays unchanged.
function keptIds(ids: string[], live: Set<string>): string[] {
  return ids.every((id) => live.has(id)) ? ids : ids.filter((id) => live.has(id));
}

function keptEntries<T>(record: Record<string, T>, live: Set<string>): Record<string, T> {
  return Object.keys(record).every((id) => live.has(id))
    ? record
    : Object.fromEntries(Object.entries(record).filter(([id]) => live.has(id)));
}

function keptFilters(filters: ColumnFiltersState, live: Set<string>): ColumnFiltersState {
  return filters.every((filter) => live.has(filter.id)) ? filters : filters.filter((filter) => live.has(filter.id));
}

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
    sortFn: "alphanumeric",
    filterFn: "includesString",
    size: DEFAULT_COLUMN_PX,
    minSize: COLUMN_WIDTHS[0][1],
    maxSize: COLUMN_WIDTHS[COLUMN_WIDTHS.length - 1][1]
  }))), [keys]);
  const table = useTable({ features, columns, data });
  // Clamped rather than reset, for the reason `DataTable` gives: callers that
  // rebuild `rows` every render would otherwise throw a reader back to page one.
  const [page, setPage] = useState(0);
  const [notice, setNotice] = useState<Notice | null>(null);
  // The sentence each notice was given when it happened. See `describe` below.
  const announced = useRef<{ seq: number; text: string; filters?: ColumnFiltersState; aboutFilters?: boolean }>({ seq: 0, text: "" });
  const filterId = useId();
  const [filterNotice, setFilterNotice] = useState<FilterNotice | null>(null);
  const filterAnnounced = useRef<{ seq: number; text: string; filters?: ColumnFiltersState; data?: TableRow[] }>({ seq: 0, text: "" });
  // What each box last announced, so leaving a box says something only if it changed.
  const lastFilterAnnounced = useRef<Record<string, string>>({});
  const filterSummary = useRef<HTMLElement>(null);
  // A callback ref, because the wrap mounts only once an empty grid gets rows.
  const [wrap, setWrap] = useState<HTMLDivElement | null>(null);
  const [wrapWidth, setWrapWidth] = useState(0);

  useEffect(() => {
    if (!wrap) return;
    const observer = new ResizeObserver(() => setWrapWidth(wrap.clientWidth));
    observer.observe(wrap);
    return () => observer.disconnect();
  }, [wrap]);

  // The grid stays mounted when its dataset reloads, and a replacement file can
  // drop fields. An arrangement or a filter naming a field that is gone would apply
  // again the moment a later file brought the field back.
  useEffect(() => {
    const live = new Set(keys);
    table.setColumnOrder((old) => keptIds(old, live));
    table.setColumnPinning((old) => {
      const start = keptIds(old.start, live);
      const end = keptIds(old.end, live);
      return start === old.start && end === old.end ? old : { start, end };
    });
    table.setColumnSizing((old) => keptEntries(old, live));
    table.setColumnVisibility((old) => keptEntries(old, live));
    table.setColumnFilters((old) => keptFilters(old, live));
    lastFilterAnnounced.current = keptEntries(lastFilterAnnounced.current, live);
    // `table` is the same object for the life of the grid; only the fields change.
  }, [keys]); // eslint-disable-line react-hooks/exhaustive-deps

  // The shared empty state, not a raw `.empty` div: `audit_ui_states` ratchets the
  // hand-written ones down, and the grid's first version added one back.
  if (!data.length) return <EmptyState inline>{empty}</EmptyState>;

  // Every row the grid was given, before any filter: what a filtered count is out of.
  const total = table.getPreFilteredRowModel().rows;
  const allRows = table.getRowModel().rows;
  const pages = Math.ceil(allRows.length / TABLE_ROW_LIMIT);
  const current = Math.min(page, pages - 1);
  const first = current * TABLE_ROW_LIMIT;
  const shown = allRows.slice(first, first + TABLE_ROW_LIMIT);
  // In `columnOrder` order, hidden columns included.
  const leafColumns = table.getAllLeafColumns();
  const visibleColumns = table.getVisibleLeafColumns();
  type GridColumn = (typeof leafColumns)[number];

  const announce = (kind: NoticeKind, id?: string) => setNotice((old) => ({ seq: (old?.seq ?? 0) + 1, kind, id }));
  const regionOf = (column: GridColumn) => (column.getIsPinned() === "start" ? "start" : "center");
  const startShown = table.getStartVisibleLeafColumns().length;
  const pinnedWidth = table.getStartTotalSize();
  const positionOf = (column: GridColumn) =>
    (regionOf(column) === "start" ? 0 : startShown) + column.getIndex(regionOf(column)) + 1;

  const move = (column: GridColumn, step: -1 | 1) => {
    const region = regionOf(column);
    const index = column.getIndex(region);
    if (index < 0) {
      announce("hidden", column.id);
      return;
    }
    // Among shown columns only, so a press never swaps with a hidden column and
    // appears to do nothing.
    const neighbour = table.getPinnedVisibleLeafColumns(region)[index + step];
    if (!neighbour) {
      announce(step < 0 ? "first" : "last", column.id);
      return;
    }
    if (region === "start") {
      table.setColumnPinning((old) => ({ ...old, start: moveBeside(old.start, column.id, neighbour.id, step > 0) }));
    } else {
      const next = moveBeside(leafColumns.map((item) => item.id), column.id, neighbour.id, step > 0);
      // Back in the dataset's own order, no order is stored, so a file that lists
      // its fields differently is shown the way it lists them.
      table.setColumnOrder(next.every((id, place) => id === keys[place]) ? [] : next);
    }
    announce("moved", column.id);
  };

  // Read through the columns that exist, in column order, hidden ones included: a
  // filter on a hidden column still cuts rows.
  const filteredColumns = leafColumns.filter((column) => column.getIsFiltered());
  const filtered = filteredColumns.length > 0;
  const nameOf = (column: GridColumn) => (column.getIsVisible() ? column.id : `${column.id} (hidden)`);
  const filterNames = filteredColumns.map(nameOf).join(", ");
  const onWhat = `the filter${filteredColumns.length === 1 ? "" : "s"} on ${filterNames}`;
  const hiddenFiltered = filteredColumns.filter((column) => !column.getIsVisible()).length;
  const filterPart = !filtered ? "" : ` · ${filteredColumns.length} filter${filteredColumns.length === 1 ? "" : "s"}`
    + (!hiddenFiltered ? "" : filteredColumns.length === 1 ? ", on a hidden column"
      : `, ${hiddenFiltered} on ${hiddenFiltered === 1 ? "a hidden column" : "hidden columns"}`);

  const announceFilters = (kind: FilterNoticeKind, id?: string) =>
    setFilterNotice((old) => ({ seq: (old?.seq ?? 0) + 1, kind, id }));
  // Typing filters as you go and announces nothing: a sentence per keystroke would
  // talk over the typing. Enter always announces; leaving a box announces only a change.
  const settleFilter = (column: GridColumn, pressed: boolean) => {
    const value = String(column.getFilterValue() ?? "");
    const before = lastFilterAnnounced.current[column.id] ?? "";
    if (!pressed && value === before) return;
    lastFilterAnnounced.current = { ...lastFilterAnnounced.current, [column.id]: value };
    announceFilters(column.getIsFiltered() ? "filtered" : before ? "unfiltered" : "none", column.id);
  };

  // Pinned columns stay in view only while one default column still has room to
  // scroll beside them. Past that they would cover the grid they are meant to anchor.
  const sticky = startShown > 0 && wrapWidth > 0 && pinnedWidth + DEFAULT_COLUMN_PX <= wrapWidth;
  // Read through the columns that exist, so moving a column and moving it back, or a
  // pin on a field the data no longer has, leaves nothing to reset. Filters are not
  // columns, and Reset columns does not claim them.
  const changed = table.getStartLeafColumns().length > 0 || !table.getIsAllColumnsVisible()
    || leafColumns.some((column, index) => column.id !== keys[index] || column.getSize() !== DEFAULT_COLUMN_PX);

  const at = (column: GridColumn) =>
    column.getIsVisible() ? `column ${positionOf(column)} of ${visibleColumns.length}` : "hidden";
  const widthName = (px: number) => COLUMN_WIDTHS.find(([, value]) => value === px)?.[0] ?? `${px}px`;
  const describe = ({ kind, id }: Notice) => {
    const filtersKept = filtered ? " Filters are unchanged." : "";
    if (kind === "reset") return `Columns reset: every column shown, unpinned, at the default width, in the dataset's order. Sorting is unchanged.${filtersKept}`;
    if (kind === "unchanged") return `Nothing to reset: every column is shown, unpinned, at the default width, in the dataset's order.${filtersKept}`;
    const column = leafColumns.find((item) => item.id === id);
    if (!column) return "";
    if (kind === "moved") return `${column.id} moved, ${at(column)}`;
    if (kind === "shown") return `${column.id} shown, ${at(column)}`;
    if (kind === "concealed") {
      return `${column.id} hidden, ${visibleColumns.length} of ${leafColumns.length} columns shown${column.getIsFiltered() ? "; its filter still applies" : ""}`;
    }
    if (kind === "pinned") {
      return `${column.id} pinned, ${at(column)}${sticky && column.getIsVisible() ? "; it stays in view when the grid scrolls sideways" : ""}`;
    }
    if (kind === "unpinned") return `${column.id} unpinned, back in its place, ${at(column)}`;
    if (kind === "width") return `${column.id} is ${widthName(column.getSize())} · ${column.getSize()}px`;
    if (kind === "hidden") return `${column.id} is hidden; show it to move it`;
    return `${column.id} is already the ${kind} ${regionOf(column) === "start" ? "pinned" : "unpinned"} column`;
  };
  const describeFilter = ({ kind, id }: FilterNotice) => {
    const count = filteredColumns.length;
    const matches = count
      ? `${allRows.length.toLocaleString()} of ${total.length.toLocaleString()} rows match`
      // Not "all shown": past forty rows the grid pages, and only a filter hides rows.
      : `${total.length.toLocaleString()} rows, none filtered out`;
    if (kind === "cleared") return `Filters cleared: ${matches}`;
    const column = leafColumns.find((item) => item.id === id);
    if (!column) return "";
    if (kind === "filtered") {
      return `${nameOf(column)} contains "${String(column.getFilterValue())}": ${matches}${count > 1 ? `, ${count} filters` : ""}`;
    }
    const rest = count ? `${matches}, ${count} filter${count === 1 ? "" : "s"}` : matches;
    return `${kind === "unfiltered" ? `Filter on ${column.id} removed` : `No filter on ${column.id}`}: ${rest}`;
  };
  // Worked out once, in the render the action produced, and then left alone. Built
  // afresh on every render, a sentence went stale when a column was shown, and was
  // rewritten -- and so announced again -- when a later hide or a narrower window
  // changed the numbers in it.
  //
  // Left alone, but not left standing once it is untrue. A sentence giving counts, or
  // one about filters, is withdrawn when the filters or the rows it described change,
  // and nothing new is announced: text taken out of a live region is not read out.
  const columnFilters = table.state.columnFilters;
  if (notice && notice.seq !== announced.current.seq) {
    const noticed = leafColumns.find((item) => item.id === notice.id);
    announced.current = {
      seq: notice.seq,
      text: describe(notice),
      filters: columnFilters,
      aboutFilters: (filtered && (notice.kind === "reset" || notice.kind === "unchanged"))
        || (notice.kind === "concealed" && Boolean(noticed?.getIsFiltered()))
    };
  } else if (announced.current.aboutFilters && announced.current.filters !== columnFilters) {
    announced.current = { ...announced.current, text: "", aboutFilters: false };
  }
  if (filterNotice && filterNotice.seq !== filterAnnounced.current.seq) {
    filterAnnounced.current = { seq: filterNotice.seq, text: describeFilter(filterNotice), filters: columnFilters, data };
  } else if (filterAnnounced.current.text
    && (filterAnnounced.current.filters !== columnFilters || filterAnnounced.current.data !== data)) {
    filterAnnounced.current = { ...filterAnnounced.current, text: "" };
  }

  return (
    <>
      <details className="grid-filters">
        <summary ref={filterSummary}>Filter rows{filterPart}</summary>
        <ol className="grid-columns-list" aria-label="Filters, one for each column">
          {[...table.getStartLeafColumns(), ...table.getCenterLeafColumns()].map((column, place) => (
            <li key={column.id} className="grid-column-row">
              {/* A real label, so the box is named by the words beside it. */}
              <label htmlFor={`${filterId}-${place}`}>Rows where {column.id} contains</label>
              <input
                id={`${filterId}-${place}`}
                type="text"
                autoComplete="off"
                spellCheck={false}
                value={String(column.getFilterValue() ?? "")}
                onChange={(event) => {
                  column.setFilterValue(event.target.value);
                  // The page a person was on belongs to the rows before this filter.
                  setPage(0);
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter") settleFilter(column, true);
                }}
                onBlur={() => settleFilter(column, false)}
                aria-describedby={column.getIsVisible() ? undefined : `${filterId}-${place}-hidden`}
              />
              {column.getIsVisible() ? null : <span id={`${filterId}-${place}-hidden`}>hidden column</span>}
            </li>
          ))}
        </ol>
      </details>
      <details className="grid-columns">
        <summary>Columns · {visibleColumns.length.toLocaleString()} of {leafColumns.length.toLocaleString()} shown{startShown > 0 ? ` · ${startShown.toLocaleString()} pinned` : null}</summary>
        <ol className="grid-columns-list" aria-label="Columns, in the order the grid shows them">
          {[...table.getStartLeafColumns(), ...table.getCenterLeafColumns()].map((column) => {
            const region = regionOf(column);
            const index = column.getIndex(region);
            return (
              <li key={column.id} className="grid-column-row">
                <label>
                  <input
                    type="checkbox"
                    checked={column.getIsVisible()}
                    disabled={!column.getCanHide()}
                    onChange={(event) => {
                      column.getToggleVisibilityHandler()(event);
                      announce(event.target.checked ? "shown" : "concealed", column.id);
                    }}
                  />
                  {column.id}
                </label>
                <select
                  aria-label={`Width of ${column.id}`}
                  value={column.getSize()}
                  onChange={(event) => {
                    table.setColumnSizing((old) => ({ ...old, [column.id]: Number(event.target.value) }));
                    announce("width", column.id);
                  }}
                >
                  {COLUMN_WIDTHS.map(([name, px]) => <option key={px} value={px}>{name} · {px}px</option>)}
                </select>
                {/* aria-disabled, never disabled: a disabled button cannot take focus, so
                    reaching an edge would throw keyboard focus away. These stay focusable,
                    and a press says why nothing moved. */}
                <button type="button" aria-label={`Move ${column.id} earlier`}
                        aria-disabled={index <= 0} onClick={() => move(column, -1)}>Earlier</button>
                <button type="button" aria-label={`Move ${column.id} later`}
                        aria-disabled={index < 0 || column.getIsLastColumn(region)} onClick={() => move(column, 1)}>Later</button>
                <label>
                  <input
                    type="checkbox"
                    aria-label={`Pin ${column.id}`}
                    checked={column.getIsPinned() === "start"}
                    disabled={!column.getCanPin()}
                    onChange={(event) => {
                      column.pin(event.target.checked ? "start" : false);
                      announce(event.target.checked ? "pinned" : "unpinned", column.id);
                    }}
                  />
                  Pin
                </label>
              </li>
            );
          })}
        </ol>
        {/* Width, place, pin and visibility; not sorting or filters, which its name does not claim. */}
        <button type="button" className="grid-columns-reset" aria-disabled={!changed} onClick={() => {
          if (!changed) {
            announce("unchanged");
            return;
          }
          table.resetColumnSizing(true);
          table.resetColumnOrder(true);
          table.resetColumnPinning(true);
          table.resetColumnVisibility(true);
          announce("reset");
        }}>Reset columns</button>
        {/* Rendered empty from the first paint: a live region inserted together with
            its first message is not announced. Each notice is a new node, so pressing
            an edge button twice is announced twice rather than once. */}
        <p className="grid-columns-status" role="status" aria-live="polite">
          {announced.current.text ? <span key={announced.current.seq}>{announced.current.text}</span> : null}
        </p>
      </details>
      {/* The filters in force, and the way back to every row, outside both disclosures:
          with them closed, a filtered grid must still say it is filtered. */}
      {filtered ? (
        <div className="grid-filter-bar">
          <span>Filtered: {filteredColumns.map((column) => `${nameOf(column)} contains "${String(column.getFilterValue())}"`).join(", ")}</span>
          <button type="button" onClick={() => {
            table.resetColumnFilters(true);
            setPage(0);
            lastFilterAnnounced.current = {};
            announceFilters("cleared");
            // The button unmounts with the bar, so focus goes to the filters' summary.
            filterSummary.current?.focus();
          }}>Clear filters</button>
        </div>
      ) : null}
      {/* Outside both disclosures, since a closed one does not render its content,
          and present from the first paint for the same reason as the columns status. */}
      <p className="grid-rows-status" role="status" aria-live="polite">
        {filterAnnounced.current.text ? <span key={filterAnnounced.current.seq}>{filterAnnounced.current.text}</span> : null}
      </p>
      {startShown > 0 && wrapWidth > 0 && !sticky ? (
        <p className="grid-pin-note">Pinned columns leave no room to scroll beside them at this width, so they scroll with the grid. Unpin one or choose a narrower width to keep them in view.</p>
      ) : null}
      <div className="table-wrap" ref={setWrap} tabIndex={0} role="region" aria-label={label}>
        <table className="grid-table" style={{ width: table.getTotalSize() }}>
          {filtered || shown.length < allRows.length ? (
            // The text sits in a sticky span: a caption is as wide as its table, so
            // it has no room to stick itself, and would scroll away with the columns.
            <caption className="table-truncated">
              {filtered && pages > 1 ? (
                <span>Showing {(first + 1).toLocaleString()}–{(first + shown.length).toLocaleString()} of {allRows.length.toLocaleString()} matching rows · {total.length.toLocaleString()} rows in all · filtered on {filterNames}</span>
              ) : filtered ? (
                <span>{allRows.length.toLocaleString()} of {total.length.toLocaleString()} rows match {onWhat}</span>
              ) : (
                <span>Showing {(first + 1).toLocaleString()}–{(first + shown.length).toLocaleString()} of {allRows.length.toLocaleString()} rows</span>
              )}
            </caption>
          ) : null}
          <colgroup>
            {(table.getHeaderGroups()[0]?.headers ?? []).map((header) => <col key={header.id} style={{ width: header.getSize() }} />)}
          </colgroup>
          <thead>
            {table.getHeaderGroups().map((group) => (
              <tr key={group.id}>
                {group.headers.map((header) => {
                  const sorted = header.column.getIsSorted();
                  const pinned = sticky && header.column.getIsPinned() === "start";
                  return (
                    <th
                      key={header.id}
                      aria-sort={sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : "none"}
                      data-pinned={pinned ? "start" : undefined}
                      data-pinned-edge={pinned && header.column.getIsLastColumn("start") ? "true" : undefined}
                      style={pinned ? { left: header.column.getStart("start") } : undefined}
                      // A header focused while it sits under the pinned columns is
                      // already inside the scrollport, so the browser does not scroll
                      // it, and the pins hide the button and its focus ring.
                      onFocus={sticky && !pinned ? (event) => {
                        const cell = event.currentTarget;
                        if (wrap && cell.offsetLeft - wrap.scrollLeft < pinnedWidth) wrap.scrollLeft = cell.offsetLeft - pinnedWidth;
                      } : undefined}
                    >
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
                  const pinned = sticky && cell.column.getIsPinned() === "start";
                  return (
                    <td
                      key={cell.id}
                      title={text}
                      data-pinned={pinned ? "start" : undefined}
                      data-pinned-edge={pinned && cell.column.getIsLastColumn("start") ? "true" : undefined}
                      style={pinned ? { left: cell.column.getStart("start") } : undefined}
                    >{text}</td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {/* The headers stay, so a person can see which columns the filter ran over. */}
      {filtered && !allRows.length ? <EmptyState inline>No row matches {onWhat}.</EmptyState> : null}
      {pages > 1 ? (
        <div className="table-pager">
          <button type="button" onClick={() => setPage(current - 1)} disabled={current === 0}>Previous rows</button>
          <button type="button" onClick={() => setPage(current + 1)} disabled={current >= pages - 1}>Next rows</button>
        </div>
      ) : null}
    </>
  );
}
