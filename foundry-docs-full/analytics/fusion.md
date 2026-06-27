<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · ANALYTICS</b><br>
<span style="font-size:22px"><b>Fusion</b></span><br>
<span style="color:#ABB3BF">A live spreadsheet application that reads from and writes back to Foundry datasets and the Ontology.</span>
</td></tr></table>

## What it is

Fusion is Foundry's spreadsheet tool — it looks and behaves like a conventional spreadsheet (cell references, functions, fill-handle dragging) but is wired directly into the Foundry data platform. Cells can pull live data from indexed Foundry datasets using `lookup` formulas, respond to user input via dropdowns and linked cells, and push results back to Foundry datasets or trigger Ontology Actions through clickable buttons. It sits inside the Analytics category of Foundry tools alongside Contour, targeting analysts who think in rows-and-columns rather than pipelines or code.

---

## How it works

Fusion's runtime spans four layers: the **Lime index**, the **spreadsheet engine**, the **formula DSL**, and **Action write-backs**.

### 1. Dataset indexing via Lime

Before a Foundry dataset can be queried from a Fusion sheet, it must be indexed into **Lime** — Foundry's internal search and lookup engine. A user or admin opens the <span style="color:#8ABBFF">Data</span> tab inside Fusion and selects **Index new dataset**, choosing the dataset path and branch. Indexing can run for multiple datasets in parallel. Once indexed, a dataset appears in the <span style="color:#8ABBFF">Indexed datasets</span> settings menu with one of three statuses:

<span style="color:#238551"><b>● Up-to-date</b></span> · <span style="color:#C87619"><b>● Syncing</b></span> · <span style="color:#CD4246"><b>● Stale</b></span>

Lime keeps a queryable snapshot of the dataset; formulas do not hit the raw dataset files directly — they query Lime. When the underlying Foundry dataset is rebuilt, the Lime index becomes **Stale** until re-synced.

### 2. Pulling data — lookup formulas

Indexed datasets are queried from cells using a family of `lookup` formulas derived from the Contour expression language DSL combined with Fusion-specific functions:

| Formula | What it returns |
|---|---|
| `lookup(dataset, col, filter_col, filter_val, …)` | Column values matching optional filters |
| `lookup_array(…)` | Same, but single results wrapped in a length-1 array |
| `lookup_distinct(…)` | Unique values from a column |
| `lookup_dropdown(…)` | An interactive dropdown whose options are lookup results |
| `lookup_sorted(dataset, col, sort_col, asc/desc)` | Values sorted by another column |
| `lookup_schema(dataset)` | Array of column names / schema |

Any argument — dataset name, column, filter value — can be a **cell reference**, making lookups dynamically reactive to user selections elsewhere on the sheet. Results are capped at **2,000 rows** per lookup. Multi-value results land in arrays; users Shift-drag downward to expand them into individual cells.

### 3. Interactive elements — dropdowns and linked cells

The <span style="color:#8ABBFF">Find and use data</span> search panel (upper-right of any sheet) lets analysts locate objects or datasets and import them as:

- **Dataset arrays** — a `lookup_array` formula placed at a cell, expandable by Shift-drag.
- **Dataset dropdowns / multi-dropdowns** — single- or multi-select dropdowns placed in each column of the imported slice (up to 200 options by default, 2,000 rows maximum import).
- **Object dropdowns / object tables** — Ontology objects displayed with their object icons; can drive other cell lookups via cell references.

This means a dropdown cell whose value changes will automatically re-evaluate any `lookup` formulas that reference it, creating a reactive, filter-driven spreadsheet without any explicit recalculation step.

### 4. Collaboration model

Fusion sheets are multi-user: multiple editors see each other's cursors and usernames in real time. However, **cell edits are only broadcast to other users after the editing user submits** (presses Enter). This prevents flickering of half-typed values on collaborators' screens.

### 5. Writing data back — Actions

Fusion supports Ontology-level write-backs through **action formulas** that render as clickable buttons:

- `action.submit_to_region()` — submits a data range to a named table region. Rows with matching keys **update** existing records; rows with new keys **insert** new records. The user must have edit access to both the sheet and the target synced dataset.
- `action.toast()` — shows a floating notification at the top of the page (used for feedback after a submit).
- `action.copy()` — copies a formula range's computed values to another range.
- `action.label()` — wraps any action with a custom label, icon, and color intent.
- `action.parallel()` / `action.serial()` — compose multiple actions to run simultaneously or in sequence, with conditional success/failure handlers for validation workflows.

Data written via `action.submit_to_region()` flows into a **synced dataset** in Foundry, making it available to downstream pipelines, transforms, and the Ontology.

### End-to-end data flow summary

```
Foundry Dataset (branch)
        │  index / sync
        ▼
     Lime Index
        │  lookup() / lookup_dropdown() / Find-and-use-data
        ▼
  Fusion Sheet Cells  ←──── user input / dropdown selection
        │  action.submit_to_region()
        ▼
  Synced Dataset (Foundry)  ──► downstream pipelines / Ontology
```

---

## User interface

### Overall layout

<table style="background:#1C2127;border:1px solid #383E47;border-collapse:collapse;width:100%">
<tr style="background:#252A31">
  <td style="padding:8px 12px;color:#8ABBFF;font-weight:bold;border:1px solid #383E47">Area</td>
  <td style="padding:8px 12px;color:#8ABBFF;font-weight:bold;border:1px solid #383E47">What you see</td>
</tr>
<tr>
  <td style="padding:8px 12px;color:#FFFFFF;border:1px solid #383E47"><b>Toolbar</b></td>
  <td style="padding:8px 12px;color:#ABB3BF;border:1px solid #383E47">Top bar with sheet tabs, undo/redo, format controls, a <span style="color:#8ABBFF">View</span> dropdown (normal vs. presentation), and a <span style="color:#8ABBFF">Settings</span> button.</td>
</tr>
<tr>
  <td style="padding:8px 12px;color:#FFFFFF;border:1px solid #383E47"><b>Formula bar</b></td>
  <td style="padding:8px 12px;color:#ABB3BF;border:1px solid #383E47">Shows the active cell's raw formula; expandable for long expressions. Autocomplete suggestions appear when you type <code>=a</code>.</td>
</tr>
<tr>
  <td style="padding:8px 12px;color:#FFFFFF;border:1px solid #383E47"><b>Grid canvas</b></td>
  <td style="padding:8px 12px;color:#ABB3BF;border:1px solid #383E47">Standard lettered columns / numbered rows. Strings left-align; numbers right-align. Action buttons render inline as <span style="color:#2D72D2"><b>[Button]</b></span> cells.</td>
</tr>
<tr>
  <td style="padding:8px 12px;color:#FFFFFF;border:1px solid #383E47"><b>Find and use data panel</b></td>
  <td style="padding:8px 12px;color:#ABB3BF;border:1px solid #383E47">Right-hand slide-out panel. Search box + Target icon (pick a cell value). Filter by object type or dataset. <span style="color:#2D72D2"><b>Use data</b></span> button opens the Import Data modal.</td>
</tr>
<tr>
  <td style="padding:8px 12px;color:#FFFFFF;border:1px solid #383E47"><b>Data tab / Indexed datasets</b></td>
  <td style="padding:8px 12px;color:#ABB3BF;border:1px solid #383E47">Left-hand or top-menu tab. Lists indexed datasets with <span style="color:#238551"><b>● Up-to-date</b></span> / <span style="color:#C87619"><b>● Syncing</b></span> / <span style="color:#CD4246"><b>● Stale</b></span> status chips. "Index new dataset" entry point here.</td>
</tr>
<tr>
  <td style="padding:8px 12px;color:#FFFFFF;border:1px solid #383E47"><b>Sheet tabs</b></td>
  <td style="padding:8px 12px;color:#ABB3BF;border:1px solid #383E47">Bottom strip (similar to Excel). Double-click to rename. Multiple sheets per workbook.</td>
</tr>
<tr>
  <td style="padding:8px 12px;color:#FFFFFF;border:1px solid #383E47"><b>Presentation view</b></td>
  <td style="padding:8px 12px;color:#ABB3BF;border:1px solid #383E47">Toggled from the toolbar <span style="color:#2D72D2"><b>View</b></span> dropdown. Hides editing chrome and optionally the grid; optimized for sharing with large audiences. Can be set as the default view in settings.</td>
</tr>
</table>

### Key interactions

- **Autocomplete**: typing `=` in a cell surfaces Contour DSL + Fusion functions; type `=a` to browse the full list.
- **Fill-handle drag**: drag the corner handle to replicate formulas; **double-click** the handle to auto-fill matching columns until an empty column is encountered.
- **Shift-drag on array results**: expands a `lookup_array` or similar multi-value result downward into individual cells.
- **Keyboard shortcuts**: standard spreadsheet shortcuts work; a <span style="color:#2D72D2">Keyboard Shortcuts</span> menu is available in the toolbar.
- **Collaborative cursors**: co-editors appear with colored cursors and usernames; changes are broadcast on Enter/submit.

---

## Worked example

**Scenario**: A logistics analyst wants to let a dispatcher look up shipment status for any order ID and record a manual status override.

1. **Index the dataset** — In the <span style="color:#2D72D2">Data</span> tab, click "Index new dataset" and select the `shipments` dataset on the `master` branch. Status shows <span style="color:#C87619"><b>● Syncing</b></span>, then transitions to <span style="color:#238551"><b>● Up-to-date</b></span>.

2. **Create an input cell** — In cell `B2`, type a label `Order ID:` and leave `C2` blank for user input.

3. **Add a reactive lookup** — In `B4`, enter:
   ```
   =lookup("shipments", "status", "order_id", C2)
   ```
   As the dispatcher types an order ID into `C2`, `B4` immediately shows the live status from Lime.

4. **Add a dropdown for the override** — In `B6`, enter:
   ```
   =lookup_dropdown("shipments", "status")
   ```
   This renders a dropdown of all distinct status values from the dataset.

5. **Add a submit button** — In `B8`, enter:
   ```
   =action.trigger(
     action.serial(
       action.submit_to_region("override_table", C2, B6),
       action.toast("Override saved!")
     ),
     action.label("Save Override", "floppy-disk", "primary")
   )
   ```
   Clicking the button writes the `(order_id, override_status)` pair into the `override_table` region of the synced dataset. Downstream Foundry pipelines can then pick up these manual overrides.

6. **Share in presentation view** — Switch to <span style="color:#2D72D2">Presentation view</span> + hide the grid; share the link with dispatchers who see a clean form-like interface without the formula bar or grid lines.

---

## Documentation map

The Fusion documentation tree under `palantir.com/docs/foundry/fusion/` covers:

- **Overview** — what Fusion is, top-level capabilities, note on Actions as an alternative for Ontology writes
- **Sheets**
  - Sheets overview — cell types, collaboration, formula bar, fill-handle behavior
  - Find and use data — search panel, Import Data modal, dataset arrays, dropdowns, object tables
  - Presentation view — toolbar toggle, hide-grid option, default view setting
- **Formulas**
  - Function library — full Contour DSL + Fusion-specific function reference
  - Perform Actions — `action.submit_to_region`, `action.toast`, `action.copy`, `action.label`, `action.parallel`, `action.serial`
  - *(additional formula/validation/time-series sub-pages)*
- **Datasets**
  - Index datasets — Lime indexing, status states, multi-dataset indexing
  - Lookup datasets — `lookup`, `lookup_array`, `lookup_distinct`, `lookup_dropdown`, `lookup_sorted`, `lookup_schema` reference
  - Sync tables — exporting/writing back to Foundry datasets
  - Import documents — bringing external document data into sheets

---

## Official documentation

- [Fusion · Overview](https://www.palantir.com/docs/foundry/fusion/overview)
- [Fusion · Sheets Overview](https://www.palantir.com/docs/foundry/fusion/sheets-overview)
- [Fusion · Find and Use Data](https://www.palantir.com/docs/foundry/fusion/find-and-use-data)
- [Fusion · Lookup Datasets](https://www.palantir.com/docs/foundry/fusion/lookup-datasets)
- [Fusion · Index Datasets](https://www.palantir.com/docs/foundry/fusion/index-datasets/index.html)
- [Fusion · Perform Actions](https://www.palantir.com/docs/foundry/fusion/perform-actions)
- [Fusion · Presentation View](https://www.palantir.com/docs/foundry/fusion/presentation-view)
- [Fusion · Function Library](https://www.palantir.com/docs/foundry/fusion/function-library/index.html)
