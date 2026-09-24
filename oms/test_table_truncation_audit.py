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
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from audit_table_truncation import (  # noqa: E402
    BASELINE, DELIBERATE_CUTS, DELIBERATE_VIEWS, FRONTEND_SRC, REFERENCE, accounting, compare, cut_name,
    cuts_in, declared_na, hidden_views_in, others_in, render, scan, silent_per_file, source_of,
    table_extents, totals, unfixed_names,
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

# --- a cut behind a condition is placed, and a list cut is gated ---------------------------
# The Drafts list of the ontology manager: its cut sits in one branch of a ternary, which the
# first version of this gate could not follow, so it read the list as nothing at all.
DRAFTS = """
export function Drafts({ drafts }) {
  const list = drafts || [];
  const [all, setAll] = useState(false);
  return <Panel>
    {list.length > 6 && !all ? <p className="table-truncated" role="note">Showing 6 of {list.length.toLocaleString()}</p> : null}
    {(all ? list : list.slice(0, 6)).map((d) => <span key={d.id} />)}
    {list.length > 6 ? <button type="button" aria-expanded={all} onClick={() => setAll((open) => !open)}>Show all {list.length}</button> : null}
  </Panel>;
}
"""
DRAFTS_NOTE = '{list.length > 6 && !all ? <p className="table-truncated" role="note">Showing 6 of {list.length.toLocaleString()}</p> : null}'
DRAFTS_TOGGLE = '{list.length > 6 ? <button type="button" aria-expanded={all} onClick={() => setAll((open) => !open)}>Show all {list.length}</button> : null}'
assert DRAFTS.count(DRAFTS_NOTE) == 1 and DRAFTS.count(DRAFTS_TOGGLE) == 1

drafts = only(DRAFTS)
check(drafts["how"] == "mapped, all on request" and drafts["source"] == "list" and not drafts["table"],
      f"T1: a cut behind a condition in a consumed group is not placed: {drafts}")
check(drafts["noted"] and drafts["reachable"] and drafts["stated"],
      f"T1: the Drafts shape, with its note and its toggle, is not read as stated: {drafts}")

both = cuts_in(DRAFTS.replace("(all ? list : list.slice(0, 6))", "(all ? list.slice(0, 60) : list.slice(0, 6))"))
check(len(both) == 2 and not any(cut["reachable"] for cut in both),
      f"T2: a ternary whose branches are both cut reads as reachable: {both}")
check(silent_per_file({"files": {"x.tsx": {"cuts": both}}}) == {"x.tsx": 2}, "T2: both cuts are not counted")

label_only = only(DRAFTS.replace(DRAFTS_NOTE, ""))
check(not label_only["noted"] and not label_only["stated"],
      f"T3: a count kept only in the button's label passes as the list's note: {label_only}")

no_control = only(DRAFTS.replace(DRAFTS_TOGGLE, ""))
check(no_control["noted"] and not no_control["reachable"] and not no_control["stated"],
      f"T4: a list with its note and no control to reach the rest passes: {no_control}")

not_a_button = only(DRAFTS.replace(DRAFTS_TOGGLE, '<span onClick={() => setAll(true)}>more</span>'))
check(not not_a_button["reachable"], f"T4: a click handler on a span, which a keyboard cannot reach, passes: {not_a_button}")

MAP = """
export function Features({ items }) {
  return <div>{items.slice(0, 12).map((item) => <button key={item.id} />)}<strong>{items.length} features</strong></div>;
}
"""
map_cut = only(MAP)
check(not map_cut["table"] and not map_cut["stated"], f"T5: the map's feature list reads as stated: {map_cut}")
check(silent_per_file({"files": {"x.tsx": {"cuts": [map_cut]}}}) == {"x.tsx": 1},
      "T5: a list cut beside a count, with no note and no way to the rest, is not silent")
noted_map = only(MAP.replace("<strong>", '<p role="note">Showing 12 of {items.length}</p><strong>'))
check(noted_map["noted"] and not noted_map["stated"], f"T6: a note with no way to the rest passes: {noted_map}")
kept_note = only(MAP.replace("{items.slice(0, 12).map", "{shown.map").replace(
    "return <div>", "const shown = items.slice(0, 12);\n  return <div>").replace("<strong>", '<p role="note">Showing {shown.length}</p><strong>'))
check(not kept_note["noted"], f"T6: a note counting what was kept passes as the true total: {kept_note}")

# ...and on the shipped Drafts list, with its note and then its toggle taken away.
manager = (FRONTEND_SRC / "workspaces" / "OntologyManager.tsx").read_text(encoding="utf-8")


def draft_cuts(source):
    return [cut for cut in cuts_in(source) if cut["source"] == "draftList"]


check(len(draft_cuts(manager)) == 1 and draft_cuts(manager)[0]["stated"],
      f"T7: the shipped Drafts list is not found stated: {draft_cuts(manager)}")
no_note, removed = re.subn(r'<p className="table-truncated" role="note">Showing the \{RECENT_DRAFTS\}.*?</p>', "", manager, flags=re.DOTALL)
check(removed == 1, "T7: the shipped Drafts note is not where the test expects it")
check(len(draft_cuts(no_note)) == 1 and not draft_cuts(no_note)[0]["stated"],
      "T7: the shipped Drafts list with its note removed still reads as stated")
no_toggle, removed = re.subn(r'<button type="button" aria-expanded=\{allDrafts\}.*?</button>', "", manager, flags=re.DOTALL)
check(removed == 1, "T7: the shipped Drafts toggle is not where the test expects it")
check(len(draft_cuts(no_toggle)) == 1 and not draft_cuts(no_toggle)[0]["stated"],
      "T7: the shipped Drafts list with its toggle removed still reads as stated")

# --- a slice that is not a collection is named, and not gated --------------------------------
for snippet, reason in (
        ("export function A({ runs }) { return <table><tbody>{runs.map((run) => <tr><td>{run.id.slice(0, 8)}</td></tr>)}</tbody></table>; }", "text"),
        ("export function B({ label }) { const id = `${label}_x`.toLowerCase().slice(0, 96); return <DataTable rows={[{ id }]} />; }", "text"),
        ("export function C({ id }) { return <span>{id.slice(5)}</span>; }", "prefix dropped"),
        ("export function D() { const [moves, setMoves] = useState([]); return <button onClick={() => setMoves((current) => current.slice(0, -1))}>Undo</button>; }", "last dropped"),
        ("export function E({ name }) { return <i>{name.slice(0, 1).toUpperCase()}</i>; }", "text"),
        ("export function G({ selected }) { return <i>{selected?.checksum?.slice(0, 12) || \"-\"}</i>; }", "text"),
        ("export function H({ text }) { return <i title={`${text.slice(0, 9)}...`} />; }", "text")):
    check(not cuts_in(snippet), f"T8: a {reason} slice reads as a collection cut: {cuts_in(snippet)}")
    check([other["reason"] for other in others_in(snippet)] == [reason],
          f"T8: {snippet[:60]!r} is not read as {reason}: {others_in(snippet)}")

# ...and a slice that could be a list is not excused as text.
bare_child = cuts_in("export function I({ chips }) { return <div>{chips.slice(0, 3)}</div>; }")
check(len(bare_child) == 1 and bare_child[0]["how"] == "unplaced", f"T9: a bare name cut as a JSX child is not gated: {bare_child}")
setter = cuts_in("export function J({ items }) { const [shown, setShown] = useState([]); return <button onClick={() => setShown(items.slice(0, 5))}>More</button>; }")
check(len(setter) == 1 and setter[0]["how"] == "unplaced", f"T9: a cut handed to a setter is read as a request payload: {setter}")
payload = "export function K({ alerts, onCreate }) { return <button onClick={() => onCreate({ ids: alerts.slice(0, 1).map((a) => a.id) })}>Open</button>; }"
check(not cuts_in(payload) and [other["reason"] for other in others_in(payload)] == ["request payload"],
      f"T9: a cut built into a handler's request is gated as a list: {cuts_in(payload)} {others_in(payload)}")

# --- every slice in the frontend is accounted for, in .ts as in .tsx ---------------------------
counts = accounting(found)
every_slice, with_slices = 0, []
for path in sorted(FRONTEND_SRC.rglob("*")):
    if path.suffix in (".ts", ".tsx") and not path.name.endswith(".d.ts"):
        here = len(re.findall(r"\.slice\(", path.read_text(encoding="utf-8")))
        every_slice += here
        if here:
            with_slices.append(str(path.relative_to(FRONTEND_SRC)).replace("\\", "/"))
check(counts["found"] == every_slice,
      f"T10: {every_slice} `.slice(` calls in the frontend and {counts['found']} accounted for: {counts}")
check(all(name in found["files"] for name in with_slices),
      f"T10: a file with a slice is not scanned: {[name for name in with_slices if name not in found['files']]}")


# --- the baseline names what is unfixed -------------------------------------------------------
def made(source, how, table=False):
    return {"line": 10, "declaration": "Made", "source": source, "spelling": "slice", "how": how, "condition": "",
            "table": table, "paging": False, "counted": False, "noted": False, "reachable": False, "stated": False}


unplaced = {"files": {"workspaces/Made.tsx": {"tables": 0, "cuts": [made("chips", "unplaced")], "others": []}}, "tables": 0}
check(unfixed_names(unplaced) == ["cut:Made.tsx::Made::chips"], f"T11: an unplaced cut is not named: {unfixed_names(unplaced)}")
ok, failures, _ = compare(unplaced, {"unfixed": 1, "unfixed_names": [], "per_file": {"workspaces/Made.tsx": 1}, "na": []})
check(not ok and any("does not hold" in f for f in failures), f"T11: an unplaced cut the baseline does not name passes: {failures}")
ok, failures, _ = compare(unplaced, {"unfixed": 1, "unfixed_names": ["cut:Made.tsx::Made::chips"],
                                     "per_file": {"workspaces/Made.tsx": 1}, "na": []})
check(not any("does not hold" in f for f in failures), f"T11: a named unplaced cut is refused: {failures}")

declared = next(iter(DELIBERATE_CUTS))
head, declaration, source = declared.split("::", 2)
na_found = {"files": {f"x/{head[len('cut:'):]}": {"tables": 0, "cuts": [dict(made(source, "unplaced"), declaration=declaration)],
                                                    "others": []}}, "tables": 0}
check(declared_na(na_found) == [declared] and unfixed_names(na_found) == [],
      f"T12: a declared cut is not set apart from the unfixed: {declared_na(na_found)} {unfixed_names(na_found)}")
ok, failures, _ = compare(na_found, {"unfixed": 0, "unfixed_names": [], "per_file": {}, "na": []})
check(not ok and any("newly declared" in f for f in failures), f"T12: a newly declared cut passes: {failures}")

# --- rendering is a pure function of the scan -----------------------------------
text = render(found)
check(render(found) == text, "rendering twice gives the same bytes")
check(f"**{silent} unfixed**" in text, text[:300])
for name, entry in found["files"].items():
    for cut in entry["cuts"]:
        if cut_name(name, cut) in DELIBERATE_CUTS:
            check(f"`{cut_name(name, cut)}`" in text, f"{name}:{cut['line']} is declared and not listed as declared")
        else:
            check(f"| `{name}` | {cut['line']} |" in text, f"{name}:{cut['line']} is a truncation missing from the reference")
    for other in entry.get("others", []):
        check(f"| `{name}` | {other['line']} | `{other['declaration']}` |" in text,
              f"{name}:{other['line']} is a slice read as {other['reason']} missing from the reference")


# --- the ratchet refuses a rise, in total, per file, and by name ------------------------
def synthetic(count, name="workspaces/Made.tsx"):
    return {"files": {name: {"tables": 1, "cuts": [dict(made("rows", "mapped", table=True), line=10 + index)
                                                    for index in range(count)], "others": []}}, "tables": 1}


two = synthetic(2)
names = unfixed_names(two)
check(names == ["cut:Made.tsx::Made::rows", "cut:Made.tsx::Made::rows#2"], f"two cuts of one source are not named apart: {names}")
ok, failures, _ = compare(two, {"unfixed": 1, "unfixed_names": names, "per_file": {"workspaces/Made.tsx": 2}, "na": []})
check(not ok and any("up from" in f for f in failures), f"the total is not a ceiling: {failures}")

ok, failures, _ = compare(two, {"unfixed": 2, "unfixed_names": names, "per_file": {}, "na": []})
check(not ok and any("this file had none" in f for f in failures),
      f"a file gaining its first unfixed truncation is not refused: {failures}")

ok, failures, _ = compare(two, {"unfixed": 2, "unfixed_names": ["cut:Made.tsx::Made::rows", "cut:Gone.tsx::Gone::rows"],
                                "per_file": {"workspaces/Made.tsx": 2}, "na": []})
check(not ok and any("does not hold" in f for f in failures),
      f"a swap that keeps the total level is not refused by name: {failures}")

ok, failures, _ = compare(found, {"unfixed": silent, "unfixed_names": unfixed_names(found),
                                  "per_file": silent_per_file(found), "na": declared_na(found)})
check(ok, f"the current tree fails its own baseline: {failures}")

check(BASELINE.exists(), f"no baseline at {BASELINE}")
check(REFERENCE.exists(), f"no reference at {REFERENCE}")
check(REFERENCE.read_text(encoding="utf-8") == text,
      "the committed reference is stale; run --write")

# --- loaded windows: the request a screen sends ------------------------------------------------
import audit_table_truncation as gate  # noqa: E402


def one_call(source, label="api/x.ts"):
    calls = gate.requests_in(label, source)
    assert len(calls) == 1, f"expected one call, found {calls}"
    return calls[0]


literal = one_call('export const evaluate = (p: string) => postJson("/decision/evaluate", { project_id: p, limit: 250 });')
check(literal["method"] == "POST" and literal["path"] == "/decision/evaluate" and literal["body"] == {"limit": 250},
      f"T13: a literal body limit is not read: {literal}")
query = one_call("export const features = (id: string) => api<FeatureCollection>(`/gis/map-layers/${encodeURIComponent(id)}/features?limit=2000`);")
check(query["path"] == "/gis/map-layers/{}/features" and query["query"] == {"limit": 2000} and query["query_known"],
      f"T13: a query limit in a template is not read: {query}")
parameter = one_call("export function listObjects(t: string, limit = 50) { return api(`/objects/${t}?limit=${limit}`); }")
check(parameter["query"] == {"limit": 50}, f"T13: a limit from a parameter's default is not resolved: {parameter}")
shorthand = one_call("export function preview(id: string, limit = 25) { return postJson(`/x/${id}/live-preview`, { limit }); }")
check(shorthand["body"] == {"limit": 25}, f"T13: a shorthand limit is not resolved: {shorthand}")
constant = one_call("const SAMPLE = 20;\nexport function artifact(id: string) { return postJson(`/a/${id}/preview`, { sample_limit: SAMPLE }); }")
check(constant["body"] == {"sample_limit": 20}, f"T13: a limit from a module constant is not resolved: {constant}")
dynamic = one_call('export const risk = (ids: string[]) => postJson("/decision/evaluate", { object_ids: ids, limit: ids.length });')
check(dynamic["body"] == {"limit": None}, f"T13: a limit taken from the request's own ids reads as a window: {dynamic}")
glued = one_call("export function packages(query: string) { return api(`/ontology-packages${query}`); }")
check(glued["path"] == "/ontology-packages" and not glued["query_known"],
      f"T13: a query glued to a path is read as a path segment: {glued}")
nested = one_call('export const nested = () => api<Record<string, Array<number>>>("/x", { method: "DELETE" });')
check(nested["path"] == "/x" and nested["method"] == "DELETE", f"T13: nested type arguments or an init's method are misread: {nested}")

# --- loaded windows: what the route keeps back ---------------------------------------------------
MODULE = """
from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
router = APIRouter(prefix="/api/v1")


class Req(BaseModel):
    limit: int = Field(default=25, ge=1)


def _contract(rows):
    violations = [row for row in rows]
    return {"violations": violations[:100], "id": uuid.uuid4().hex[:12]}


@router.get("/plugins/{version_id}/executions")
def executions(version_id: str, limit: int = Query(default=50, ge=1, le=500)):
    return {}


@router.get("/a")
def summary(limit: int = Query(50, ge=1)):
    rows = q.limit(25).all()
    one = q.limit(1).first()
    return {"latest": [d(row) for row in rows[:8]], "contract": _contract(rows), "first": rows[:1]}


@router.post("/p")
def post(body: Req):
    return {}


@router.get("/layers/{layer_id}/features")
def features(layer_id: str, limit: int = 1000):
    raise HTTPException(status_code=400, detail=text[:200])
"""
routes = {route["function"]: route for route in gate.routes_in("m", MODULE)}
check(routes["executions"]["path"] == "/api/v1/plugins/{}/executions" and routes["executions"]["defaults"] == {"limit": (50, "query")},
      f"T14: `Query(default=N)` or the router's prefix is not read: {routes['executions']}")
check(routes["summary"]["defaults"] == {"limit": (50, "query")}, f"T14: `Query(N)` is not read: {routes['summary']}")
check(routes["features"]["defaults"] == {"limit": (1000, "query")} and routes["features"]["caps"] == [],
      f"T14: a plain default is not read, or a message cut in a raise reads as a cap: {routes['features']}")
check(routes["post"]["defaults"] == {"limit": (25, "body")}, f"T14: a body model's `Field(default=N)` is not read: {routes['post']}")
check(sorted(routes["summary"]["caps"]) == ["cap:m._contract::violations[:100]", "cap:m.summary::.limit(25)", "cap:m.summary::rows[:8]"],
      f"T14: the caps a route and its helper write are not exactly these: {routes['summary']['caps']}")

# --- loaded windows: linking, omission, and a limit with nowhere to go -----------------------------
module_routes = gate.routes_in("m", MODULE)
census_items = gate.windows_from({
    "api/runs.ts": "export const runs = (id: string) => api(`/api/v1/plugins/${encodeURIComponent(id)}/executions`);",
    "api/some.ts": "export const some = (id: string) => api(`/api/v1/plugins/${id}/executions?limit=10`);",
    "api/nowhere.ts": 'export const nowhere = () => postJson("/no/such", { limit: 5 });',
    "api/summary.ts": 'export const summary = () => api("/api/v1/a");',
    "api/query.ts": 'export const query = (body: { limit?: number }) => postJson("/api/v1/p", body);',
    "screens/Screen.tsx": "export function Screen() {\n  query({ limit: 500 });\n  query({ other: 1 });\n}",
}, module_routes)
items = census_items["items"]
check("default:GET /api/v1/plugins/{}/executions::limit" in items
      and items["default:GET /api/v1/plugins/{}/executions::limit"]["via"] == ["api/runs.ts:1"],
      f"T15: a call leaving the limit out does not reach the route's default, or one passing it does: {items}")
check(items.get("request:api/some.ts::some::GET /api/v1/plugins/{}/executions::limit", {}).get("value") == 10,
      f"T15: a request limit is not keyed by what it is: {sorted(items)}")
check(census_items["unlinked"] == ["request:api/nowhere.ts::nowhere::POST /no/such::limit"],
      f"T15: a request limit whose route does not exist is not reported: {census_items['unlinked']}")
check({"cap:m.summary::.limit(25)", "cap:m.summary::rows[:8]", "cap:m._contract::violations[:100]", "default:GET /api/v1/a::limit"} <= set(items),
      f"T15: the caps of a route a screen calls are not in the census: {sorted(items)}")
check(items.get("request:screens/Screen.tsx::Screen::POST /api/v1/p::limit", {}).get("value") == 500
      and items.get("default:POST /api/v1/p::limit", {}).get("via") == ["screens/Screen.tsx:3"],
      f"T15: a helper's caller is not read as the request, with and without the limit: {sorted(items)}")
check("cap:m.features::" not in " ".join(items), "T15: a route no screen calls enters the census")

# --- loaded windows: the registry -------------------------------------------------------------------
check("must be exactly one" in gate.window_problem({}), "T16: a window with no state passes")
check("must be exactly one" in gate.window_problem({"state": {"gap": "a", "na": "b"}}), "T16: a window with two states passes")
check("nothing said" in gate.window_problem({"state": {"gap": " "}}), "T16: a gap with no reason passes")
check("does not exist" in gate.window_problem({"state": {"stated": "no-such.spec.ts::x"}, "screen": "App.tsx", "note": "x"}),
      "T16: a window stated by a spec that does not exist passes")
check("no longer contains" in gate.window_problem({"state": {"stated": "truncation-sites.spec.ts::a title nobody wrote"},
                                                   "screen": "App.tsx", "note": "x"}),
      "T16: a window stated by a test nobody wrote passes")
stated_windows = {name: window for name, window in gate.WINDOWS.items() if gate._state_kind(window.get("state")) == "stated"}
check(len(stated_windows) >= 3, f"T16: only {len(stated_windows)} stated windows are registered")
for name, window in stated_windows.items():
    check(gate.window_problem(window) == "", f"T16: window:{name} is stated and fails: {gate.window_problem(window)}")
    other = next(title for title in (w["state"]["stated"] for w in stated_windows.values()) if title != window["state"]["stated"])
    check("names no note" in gate.window_problem(dict(window, note="")), f"T16: window:{name} passes naming no note")


def without_note(source, fragment):
    """The source with every note, caption or summary holding `fragment` taken out."""
    out, removed = source, 0
    for match in reversed(list(gate._STATEMENT_OPEN.finditer(source))):
        end = gate._element_end(source, match.start(), match.group(1) or match.group(2))
        if fragment in source[match.start():end]:
            out, removed = out[:match.start()] + out[end:], removed + 1
    return out, removed


for name, window in stated_windows.items():
    screen = f"frontend/src/{window['screen']}"
    stripped, removed = without_note((gate.FRONTEND_SRC / window["screen"]).read_text(encoding="utf-8"), window["note"])
    check(removed >= 1, f"T17: window:{name}'s note {window['note']!r} is not in a note, caption or summary of {window['screen']}")
    check("states nothing on screen" in gate.window_problem(window, {screen: stripped}),
          f"T17: window:{name} still reads as stated with its note taken out of {window['screen']}")

baseline_now = {"unfixed": len(unfixed_names(found)), "unfixed_names": unfixed_names(found),
                "per_file": silent_per_file(found), "na": declared_na(found)}
gaps = [name for name, window in gate.WINDOWS.items() if gate._state_kind(window.get("state")) == "gap"]
if gaps:
    as_na = dict(gate.WINDOWS, **{gaps[0]: dict(gate.WINDOWS[gaps[0]], state={"na": "declared away"})})
    ok, failures, _ = compare(found, baseline_now, as_na)
    check(not ok and any(f"window:{gaps[0]} is newly declared" in f for f in failures),
          f"T18: a gap window declared not applicable passes: {failures}")
    as_stated = dict(gate.WINDOWS, **{gaps[0]: dict(gate.WINDOWS[gaps[0]], state={"stated": next(iter(stated_windows.values()))["state"]["stated"]},
                                                    note="a note this screen never renders")})
    ok, failures, _ = compare(found, baseline_now, as_stated)
    check(not ok and any(f"window:{gaps[0]} is stated" in f for f in failures),
          f"T18: a gap window claiming another window's test passes: {failures}")
first = next(iter(gate.WINDOWS))
unclaimed = {name: window for name, window in gate.WINDOWS.items() if name != first}
ok, failures, _ = compare(found, baseline_now, unclaimed)
check(not ok and any("no entry in WINDOWS claims" in f for f in failures), f"T18: a window taken out of the registry passes: {failures}")
invented = dict(gate.WINDOWS, invented={"claims": ["request:workspaces/Nowhere.tsx::Nowhere::GET /none::limit"], "screen": "App.tsx",
                                        "state": {"gap": "a claim nothing makes"}})
ok, failures, _ = compare(found, dict(baseline_now, unfixed=baseline_now["unfixed"] + 1,
                                      unfixed_names=sorted(baseline_now["unfixed_names"] + ["window:invented"])), invented)
check(not ok and any("no longer finds there" in f for f in failures), f"T18: a window claiming what the census does not find passes: {failures}")
twice = dict(gate.WINDOWS, again=dict(gate.WINDOWS[first], state={"gap": "claimed twice"}))
ok, failures, _ = compare(found, baseline_now, twice)
check(not ok and any("is claimed by 2 windows" in f for f in failures), f"T18: a census item claimed twice passes: {failures}")

# --- loaded windows: the ratchet names them ---------------------------------------------------------
windowed = {"files": {}, "tables": 0, "sources": {},
            "windows": {"items": {"request:api/a.ts::a::GET /a::limit": {"kind": "request", "value": 5, "at": "api/a.ts:1"}}, "unlinked": []}}
registry = {"b": {"claims": ["request:api/a.ts::a::GET /a::limit"], "screen": "App.tsx", "state": {"gap": "draws the five as all"}}}
check(unfixed_names(windowed, registry) == ["window:b"], f"T19: a gap window is not named: {unfixed_names(windowed, registry)}")
ok, failures, _ = compare(windowed, {"unfixed": 1, "unfixed_names": ["window:c"], "per_file": {}, "na": []}, registry)
check(not ok and any("window:b is an unfixed truncation the baseline does not hold" in f for f in failures),
      f"T19: a gap window the baseline does not name passes at a level total: {failures}")
ok, failures, notes = compare(windowed, {"unfixed": 2, "unfixed_names": ["window:b", "window:c"], "per_file": {}, "na": []}, registry)
check(any("window:c is no longer found unfixed" in note for note in notes) and not any("window:c" in f for f in failures),
      f"T19: a gap that closed is refused rather than noted: {failures} {notes}")

check(BASELINE.exists() and not any(key.endswith("_ceiling") for key in json.loads(BASELINE.read_text(encoding="utf-8"))),
      "T21: the baseline carries a `_ceiling` key, which enrols this debt in the ratchet-motion gate")
check(json.loads(BASELINE.read_text(encoding="utf-8")).get("unfixed_names") == unfixed_names(found),
      "T21: the baseline's names are not exactly what is unfixed now")

# --- a view that leaves out what a person hid (X6 of GOAL_GRAPH_2026-09-23) ------------
HIDING = '''
export function Canvas({ nodes, hiddenNodes, onShowAll }) {
  const shown = nodes.filter((node) => !hiddenNodes.has(node.id));
  return (<div>%s{shown.map((node) => <b key={node.id}>{node.id}</b>)}</div>);
}
'''
silent_view = hidden_views_in(HIDING % "")
check(len(silent_view) == 1 and not silent_view[0]["noted"] and not silent_view[0]["reachable"],
      f"T22: a view that hides nodes and says nothing is not read as silent: {silent_view}")
said = hidden_views_in(HIDING % '<p role="note">{nodes.length - shown.length} hidden '
                                 '<button onClick={onShowAll}>Show all</button></p>')
check(said and said[0]["noted"] and said[0]["reachable"],
      f"T22: a view that counts what it hides and shows it all is not read as stated: {said}")
uncounted = hidden_views_in(HIDING % '<p role="note">Some are hidden <button onClick={onShowAll}>Show all</button></p>')
check(uncounted and not uncounted[0]["noted"], f"T22: a note with no count passes as stating one: {uncounted}")
check(not hidden_views_in("const kept = nodes.filter((node) => !removedNodes.has(node.id));"),
      "T22: an exclusion filter that is not a hidden set is read as a view")
fake = {"files": {"components/Canvas.tsx": {"tables": 0, "cuts": [], "others": [], "views": silent_view}}}
check("view:Canvas.tsx::Canvas::hiddenNodes" in unfixed_names(fake),
      f"T22: a silent hidden view is not counted unfixed: {unfixed_names(fake)}")
check(all(key in json.loads(BASELINE.read_text(encoding="utf-8")).get("na", []) for key in DELIBERATE_VIEWS),
      "T22: a filter declared not a view is not held in the baseline's na")
check("## What a person hid" in render(found), "T22: the reference has no section for hidden views")

print(f"Table truncation gate verified: {checks} assertions passed "
      f"({silent} unfixed, {reaching} reaching a table, across {tables} tables).")
