"""A table that hides rows must trip the rule, and one that says so must not.

Also this check's home: `audit_table_truncation` declares `every suite run`.

The census in `docs/TABLE_TRUNCATION.md` is worth nothing until the rule has been
shown to refuse something, so the assertions below run the real scanner over
synthetic components. Two groups carry the weight.

The first is the table this goal started from. `DataTable` as it stood before N3
truncated three ways -- rows past forty, columns from a ten-row sample, eight
keys a row -- and the rule must find all three, including the column sample,
which reaches the table only through a `columns` binding four lines above it.

The second is the three ways round the rule: cutting the rows at the call site
so the component has nothing to caption, rendering the count of what was kept
instead of what was cut, and spelling the cut as an index filter. Each of those
would leave this gate reporting a number that is wrong rather than high.
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

grid_call_site = only("""
export function Records({ rows }) {
  return <DataGrid rows={rows.slice(0, 25)} />;
}
""")
check(grid_call_site["table"] and not grid_call_site["counted"],
      f"rows cut before they reach DataGrid pass; the grid is a table as DataTable is: {grid_call_site}")

held_then_passed = only("""
function CommandTab({ events }) {
  const rows = events.slice(0, 25).map((event) => ({ title: event.title }));
  return <Panel title="Feed"><DataTable rows={rows} /></Panel>;
}
""")
check(held_then_passed["table"] and not held_then_passed["counted"],
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
             "how": "mapped", "table": True, "counted": False} for index in range(count)]
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
