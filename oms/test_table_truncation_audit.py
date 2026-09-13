"""A table that hides rows must trip the rule, and one that says so must not.

Also this check's home: `audit_table_truncation` declares `every suite run`.

The census in `docs/TABLE_TRUNCATION.md` is worth nothing until the rule has been
shown to refuse something, so the assertions below run the real scanner over
synthetic components. Two groups carry the weight.

The first is the table this goal started from. `DataTable` as it stood before N3
truncated three ways -- rows past forty, columns from a ten-row sample, eight
keys a row -- and the rule must find all three, including the column sample,
which reaches the table only through a `columns` binding four lines above it.

The second is the ways round the rule: cutting the rows at the call site so the
component has nothing to caption, rendering the count of what was kept instead
of what was cut, spelling the cut as an index filter, and -- N9, found after the
first three -- rendering the true count beside rows cut before a table that pages
them. Each of those would leave this gate reporting a number that is wrong rather
than high.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from audit_table_truncation import (  # noqa: E402
    BASELINE, FRONTEND_SRC, REFERENCE, compare, cuts_in, render, scan, silent_per_file,
    source_of, table_extents, totals,
)

checks = 0


def check(condition, message):
    global checks
    assert condition, message
    checks += 1


def only(text):
    """The one truncation a synthetic component holds."""
    found = cuts_in(text)
    assert len(found) == 1, f"expected one truncation, found {found}"
    return found[0]


found = scan()
tables, reaching, silent = totals(found)

# --- the rule sees tables at all ----------------------------------------------
check(tables > 50, f"only {tables} table elements found; the table rule is not matching")
check(any(name.endswith("DataDisplay.tsx") for name in found["files"]),
      "the shared table's own file is not scanned")

# --- a string shortened for display is not a truncation -----------------------
check(not cuts_in("""
export function Runs({ runs }) {
  return <table><tbody>{runs.map((run) => <tr key={run.id}><td>{run.id.slice(0, 8)}</td></tr>)}</tbody></table>;
}
"""), "an id cut to eight characters reads as a table dropping rows")
check(not cuts_in("""
export function Name({ label }) {
  const id = `${label}_x`.toLowerCase().slice(0, 96);
  return <DataTable rows={[{ id }]} />;
}
"""), "a string bound to a name reads as a collection because the name reaches a table")

# --- a cut inside a table, with and without its count -------------------------
silent_rows = only("""
export function Feed({ rows }) {
  return <table><tbody>{rows.slice(0, 40).map((row) => <tr key={row.id} />)}</tbody></table>;
}
""")
check(silent_rows["table"] and not silent_rows["counted"],
      f"forty rows cut inside a <table> with no count is not silent: {silent_rows}")

counted_rows = only("""
export function Feed({ rows }) {
  return <table><caption>Showing 40 of {rows.length.toLocaleString()}</caption>
    <tbody>{rows.slice(0, 40).map((row) => <tr key={row.id} />)}</tbody></table>;
}
""")
check(counted_rows["table"] and counted_rows["counted"],
      f"a cut beside the length of its source is refused anyway: {counted_rows}")

grid = only("""
export function Release({ revisions }) {
  return <div role="table">{revisions.slice(0, 5).map((r) => <div role="row" key={r.id} />)}</div>;
}
""")
check(grid["table"], "an element with role=\"table\" is not read as a table")

# --- the three ways round it ---------------------------------------------------
# 1. Cut at the call site. DataTable captions its own cut, so this is the cheapest
#    way to make a table silent again, and the operations feed was already doing it.
call_site = only("""
export function Contract({ issues }) {
  return <DataTable rows={issues.slice(0, 25)} />;
}
""")
check(call_site["table"] and not call_site["counted"] and call_site["how"] == "passed as rows",
      f"rows cut before they reach DataTable pass because DataTable has nothing to caption: {call_site}")
check(call_site["paging"], f"a cut handed to DataTable is not read as a cut into a table that pages: {call_site}")

grid_call_site = only("""
export function Records({ rows }) {
  return <DataGrid rows={rows.slice(0, 25)} />;
}
""")
check(grid_call_site["table"] and not grid_call_site["counted"] and grid_call_site["paging"],
      f"rows cut before they reach DataGrid pass; the grid is a table as DataTable is: {grid_call_site}")

held_then_passed = only("""
function CommandTab({ events }) {
  const rows = events.slice(0, 25).map((event) => ({ title: event.title }));
  return <Panel title="Feed"><DataTable rows={rows} /></Panel>;
}
""")
check(held_then_passed["table"] and not held_then_passed["counted"] and held_then_passed["paging"],
      f"the operations feed's own shape -- cut, mapped, bound, passed -- is not seen: {held_then_passed}")

# 2. The count of what was kept.
kept = only("""
export function Feed({ rows }) {
  const shown = rows.slice(0, 40);
  return <table><caption>{shown.length} rows</caption><tbody>{shown.map((row) => <tr key={row.id} />)}</tbody></table>;
}
""")
check(kept["table"] and not kept["counted"],
      "rendering the length of the cut result passes as a true count; it can only ever say 40")

condition = only("""
export function Contract({ issues }) {
  return issues.length ? <DataTable rows={issues.slice(0, 25)} /> : null;
}
""")
check(not condition["counted"], "a length used as a condition passes as a rendered count")

# 3. The index filter.
filtered = only("""
export function Feed({ rows }) {
  return <DataTable rows={rows.filter((_, index) => index < 25)} />;
}
""")
check(filtered["spelling"] == "index filter" and filtered["table"] and not filtered["counted"],
      f"the same cut spelled as an index filter walks past the rule: {filtered}")

# 4. The true count beside rows the table was never given. N9 of the goal: the
#    pipeline builder's contract panel summarised every issue and handed its table
#    twenty-five, and this gate read that as counted. DataTable pages what it
#    receives, so the rows past the cut were not missing from the count; they were
#    missing from the screen. Found by the N7d census, not by this gate.
counted_call_site = only("""
function OntologyContractPanel({ issues }) {
  return <details open><summary>{issues.length} contract issues</summary><DataTable rows={issues.slice(0, 25)} /></details>;
}
""")
check(counted_call_site["counted"] and counted_call_site["paging"],
      f"the contract panel's shape is not read as counted and cut into a paging table: {counted_call_site}")
check(silent_per_file({"files": {"x.tsx": {"cuts": [counted_call_site]}}}) == {"x.tsx": 1},
      "a counted cut into a table that pages passes: the count names rows nobody can reach")
check(not counted_rows["paging"] and silent_per_file({"files": {"x.tsx": {"cuts": [counted_rows]}}}) == {},
      "a counted cut inside a plain <table>, which pages nothing, is refused along with the paging ones")

# 5. A filter, which cuts inside the library and never through a `.slice`. N7c of the
#    goal: a grid captioning only the rows that matched reads as the whole dataset.
FILTERED = """
const features = tableFeatures({ columnFilteringFeature, filteredRowModel: createFilteredRowModel() });

export function Grid({ table }) {
  const rows = table.getRowModel().rows;
%s
  return <table><caption>%s</caption><tbody>{rows.map((row) => <tr key={row.id} />)}</tbody></table>;
}
"""


def filtered_cuts(binding, caption, head=FILTERED):
    return [cut for cut in cuts_in(head % (binding, caption)) if cut["spelling"] == "filtered row model"]


matched_only = filtered_cuts("", "{rows.length} rows")
check(len(matched_only) == 1 and matched_only[0]["table"] and not matched_only[0]["counted"],
      f"a filtered grid captioning only what matched is not read as a silent cut: {matched_only}")
check(silent_per_file({"files": {"x.tsx": {"cuts": matched_only}}}) == {"x.tsx": 1},
      "a filtered grid counting only its matches is not silent")
bound_total = filtered_cuts("  const total = table.getPreFilteredRowModel().rows;",
                            "{rows.length} of {total.length.toLocaleString()} rows")
check(len(bound_total) == 1 and bound_total[0]["counted"] and bound_total[0]["source"] == "total",
      f"the total from before filtering, bound to a name, is not read as the true count: {bound_total}")
unbound_total = filtered_cuts("", "{rows.length} of {table.getPreFilteredRowModel().rows.length}")
check(len(unbound_total) == 1 and unbound_total[0]["counted"],
      f"the total from before filtering, written inline, is not read as the true count: {unbound_total}")
total_as_condition = filtered_cuts("  const total = table.getPreFilteredRowModel().rows;",
                                   '{total.length ? "some" : "none"}')
check(len(total_as_condition) == 1 and not total_as_condition[0]["counted"],
      "a total used as a condition passes as a rendered count")
kept_as_total = filtered_cuts("", "{rows.length} of {table.getFilteredRowModel().rows.length}")
check(len(kept_as_total) == 1 and not kept_as_total[0]["counted"],
      "the filtered model's own length, which is the count of what was kept, passes as the true count")
kept_bound = filtered_cuts("  const total = table.getFilteredRowModel().rows;", "{rows.length} of {total.length}")
check(len(kept_bound) == 1 and not kept_bound[0]["counted"],
      "the filtered model bound to a name that sounds like a total passes as the true count")
check(not filtered_cuts("", "{rows.length} rows",
                        head=FILTERED.replace("columnFilteringFeature, filteredRowModel: createFilteredRowModel()",
                                              "rowSortingFeature, sortedRowModel: createSortedRowModel()")),
      "a grid that only sorts is read as filtering its rows")
# The total has to be in the markup. A sentence built in a template is shown only
# after Enter, so a caption without the total reads as the dataset while typing.
template_only = filtered_cuts("  const total = table.getPreFilteredRowModel().rows;\n  const said = `${rows.length} of ${total.length} rows`;",
                              "{rows.length} rows")
check(len(template_only) == 1 and not template_only[0]["counted"],
      "a total said only in a template sentence passes as the filtered grid's rendered count")
typed = filtered_cuts("  const total: Row[] = table.getPreFilteredRowModel().rows", "{rows.length} of {total.length} rows")
check(len(typed) == 1 and typed[0]["counted"] and typed[0]["source"] == "total",
      f"a typed binding with no semicolon misreads the total from before filtering: {typed}")
destructured = filtered_cuts("  const { rows: total } = table.getPreFilteredRowModel();", "{rows.length} of {total.length} rows")
check(len(destructured) == 1 and destructured[0]["counted"] and destructured[0]["source"] == "total",
      f"a destructured total from before filtering is misread: {destructured}")
sorted_draw = [cut for cut in cuts_in((FILTERED % ("", "{rows.length} rows")).replace("table.getRowModel().rows", "table.getSortedRowModel().rows"))
               if cut["spelling"] == "filtered row model"]
check(len(sorted_draw) == 1 and not sorted_draw[0]["counted"],
      f"rows drawn from the sorted model, which is downstream of the filter, are not read as a cut: {sorted_draw}")

# ...and on the shipped grid, with the totals taken out of its captions.
grid_source = (FRONTEND_SRC / "components" / "data" / "DataGrid.tsx").read_text(encoding="utf-8")
grid_filtered = [cut for cut in cuts_in(grid_source) if cut["spelling"] == "filtered row model"]
check(len(grid_filtered) == 1 and grid_filtered[0]["counted"],
      f"the shipped DataGrid's filtered rows do not read as counted: {grid_filtered}")
no_totals, taken = re.subn(r"(?<!\$)\{total\.length\.toLocaleString\(\)\}", "", grid_source)
check(taken >= 2, f"the shipped DataGrid renders its total from before filtering in {taken} place(s), fewer than its two captions")
stripped_filtered = [cut for cut in cuts_in(no_totals) if cut["spelling"] == "filtered row model"]
check(len(stripped_filtered) == 1 and not stripped_filtered[0]["counted"],
      "taking the total out of DataGrid's captions leaves its filtered rows reading as counted")

# --- the scope is the table element, not the component -------------------------
# The first version scoped this to the component and counted Object Explorer's
# facet chips and Vertex's seed list, because both components draw a table
# elsewhere. This is the assertion that fails against that version.
beside = cuts_in("""
export function Explorer({ objects, buckets }) {
  return <>
    <DataTable rows={objects} empty={(x) => x > 1 ? "many" : "none"} />
    <div className="chips">{buckets.slice(0, 7).map((bucket) => <button key={bucket.id} />)}</div>
  </>;
}
""")
check(len(beside) == 1 and not beside[0]["table"],
      f"a list cut beside a table is counted as the table's: {beside}")
check(len(table_extents('<DataTable rows={rows} empty={(x) => x > 1} />{after}')) == 1
      and table_extents('<DataTable rows={rows} empty={(x) => x > 1} />{after}')[0][1]
      == len('<DataTable rows={rows} empty={(x) => x > 1} />'),
      "an arrow inside a DataTable prop ends the tag early, or runs the tag past its end")

columns = only("""
export function Explorer({ query }) {
  const columns = query?.columns.slice(0, 8) || [];
  const other = 1;
  return <table><thead><tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr></thead></table>;
}
""")
check(columns["table"] and columns["source"] == "query.columns",
      f"a column cut bound above the table that draws it is not followed: {columns}")

# --- where the count comes from -------------------------------------------------
check(source_of("(drafts.value || [])") == "drafts.value", "a fallback is read as the source")
check(source_of("query?.columns") == "query.columns", "optional chaining is not normalised")
check(source_of("Object.keys(row || {})") == "Object.keys(row || {})",
      "a call's own argument list is split as if it were a fallback")

# --- the table this goal started from -------------------------------------------
BEFORE_N3 = """
export function DataTable({ rows, specs, empty = "No records" }: { rows?: TableRow[]; specs?: Record<string, PropertySpec>; empty?: string }) {
  const safeRows = rows || [];
  const columns = useMemo(() => {
    const seen = new Set<string>();
    for (const row of safeRows.slice(0, 10)) Object.keys(row || {}).slice(0, 8).forEach((key) => seen.add(key));
    return Array.from(seen);
  }, [safeRows]);
  if (!safeRows.length) return <div className="empty">{empty}</div>;
  return (
    <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable data table">
      <table>
        <thead>
          <tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr>
        </thead>
        <tbody>
          {safeRows.slice(0, 40).map((row, index) => (
            <tr key={index}>{columns.map((column) => <td key={column}>{formatValue(row[column])}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
"""
before = cuts_in(BEFORE_N3)
check(len(before) == 3 and all(c["table"] and not c["counted"] for c in before),
      f"the pre-N3 DataTable is not refused three ways: {before}")
check({c["how"] for c in before} == {"iterated", "forEach", "mapped"},
      f"the column sample, the key cap and the row cut are not each found: {before}")

# ...and the shipped one, with its caption taken away.
shipped = (FRONTEND_SRC / "components" / "data" / "DataDisplay.tsx").read_text(encoding="utf-8")
live = [c for c in cuts_in(shipped) if c["declaration"] == "DataTable"]
check(len(live) == 1 and live[0]["table"] and live[0]["counted"],
      f"the shipped DataTable does not read as a counted cut: {live}")
uncaptioned, removed = re.subn(r"<caption\b.*?</caption>", "", shipped, flags=re.DOTALL)
check(removed == 1, "the shipped DataTable has no caption to remove")
stripped = [c for c in cuts_in(uncaptioned) if c["declaration"] == "DataTable"]
check(len(stripped) == 1 and not stripped[0]["counted"],
      "removing DataTable's caption leaves its cut reading as counted")

# --- rendering is a pure function of the scan -----------------------------------
text = render(found)
check(render(found) == text, "rendering twice gives the same bytes")
check(f"**{silent} of {reaching}**" in text, text[:300])
for name, entry in found["files"].items():
    for cut in entry["cuts"]:
        check(f"| `{name}` | {cut['line']} |" in text,
              f"{name}:{cut['line']} is a truncation missing from the reference")


# --- the ratchet refuses a rise, in total and per file ----------------------------
def synthetic(count, name="workspaces/Made.tsx"):
    cuts = [{"line": 10 + index, "declaration": "Made", "source": "rows", "spelling": "slice",
             "how": "mapped", "table": True, "paging": False, "counted": False} for index in range(count)]
    return {"files": {name: {"tables": 1, "cuts": cuts}}, "tables": 1}


two = synthetic(2)
ok, failures, _ = compare(two, {"silent": 1, "per_file": {"workspaces/Made.tsx": 2}})
check(not ok and any("up from" in f for f in failures), f"the total is not a ceiling: {failures}")

ok, failures, _ = compare(two, {"silent": 2, "per_file": {}})
check(not ok and any("this file had none" in f for f in failures),
      f"a file gaining its first silent truncation is not refused: {failures}")

ok, failures, _ = compare(two, {"silent": 2, "per_file": {"workspaces/Made.tsx": 1,
                                                          "workspaces/Gone.tsx": 1}})
check(not ok and any("1 -> 2" in f for f in failures),
      f"a swap that keeps the total level is not refused: {failures}")

ok, _, _ = compare(found, {"silent": silent, "per_file": silent_per_file(found)})
check(ok, "the current tree fails its own baseline")

check(BASELINE.exists(), f"no baseline at {BASELINE}")
check(REFERENCE.exists(), f"no reference at {REFERENCE}")
check(REFERENCE.read_text(encoding="utf-8") == text,
      "the committed reference is stale; run --write")

print(f"Table truncation gate verified: {checks} assertions passed "
      f"({silent} of {reaching} table truncations silent, across {tables} tables).")
