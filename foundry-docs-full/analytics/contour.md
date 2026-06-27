<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · ANALYTICS</b><br>
<span style="font-size:22px"><b>Contour</b></span><br>
<span style="color:#ABB3BF">Point-and-click analytical platform for visualizing, filtering, and transforming large datasets without code.</span>
</td></tr></table>

## What it is

Contour is Palantir Foundry's no-code, browser-based analytics tool that enables users to explore and transform tabular data at scale using a sequential board-based model. Analyses are organized into parameterized paths that produce interactive dashboards or saveable output datasets. It is best suited for large-scale joins and aggregations, one-off exploratory work on unmapped datasets, and sharing governed analysis results as reproducible Foundry jobs.

---

## How it works

Contour's execution model is a **top-down, board-chained pipeline**. Data enters at the top of a path and is progressively transformed by each board before passing to the next.

1. **Create an Analysis.** An analysis is a named Contour resource stored in Foundry. It holds one or more analytical **paths** (investigation threads) and a shared parameter space. Open any dataset in Foundry and click **Analyze** to launch a new analysis seeded with that dataset.

2. **Define a Path.** Each path starts with a **source dataset** selected from Foundry's catalog (including restricted views and saved query results). Paths are independent of each other within the same analysis; you can branch an investigation by adding a second path from a different starting dataset.

3. **Add Boards.** Boards are the core unit of work. They stack vertically and execute top-to-bottom: the output table of board *N* becomes the input of board *N+1*. Board types fall into four families:
   - **Visualization** — Chart, Histogram, Distribution, Time Series, Grid, Heatmap, Pivot Table, Calculation
   - **Filtering** — Filter (text / numeric / date / wildcard), Expression (custom formula), Set Math (keep / add / remove rows vs. a reference dataset)
   - **Transformation** — Edit Columns, Column Editor, Multi-Column Editor, Reorder Columns, Transform Data (obfuscate / hash / k-anonymize), Sort, Unpivot, Deduplication
   - **Integration** — Enrich (left join, returns both tables' columns), Link (inner/right join, returns right columns), Join (admin-curated templates)
   
   Selecting a row or bar in a visualization board automatically filters data for all boards **below** it in the path, enabling interactive drill-down without writing a filter.

4. **Parameterize.** Parameters (type: String, Number, or Date) are declared in the left sidebar and injected into downstream boards in two ways: via the **Filter board** dropdown (no code), or via `$parameter_name` syntax inside an **Expression board**. String and Number parameters support multiple simultaneous values (treated as arrays). Suggested values for string/number parameters can be sourced from a dataset column (up to 1 000 unique values) or a manually entered list. Cross-filter groups let multiple parameters from the same dataset narrow each other's suggestion lists.

5. **Aggregate and Visualize.** Numeric aggregation functions available across boards include Count, Min, Max, Sum, Mean, Standard Deviation, Variance, and approximate Median (Spark `percentile_approx`). The **Chart** board supports layered overlays (e.g., a bar chart plus a line overlay with a second Y-axis) and chart types: bar, line, scatter, heat grid, and pie.

6. **Publish a Dashboard.** A Contour **Dashboard** aggregates charts and text tiles from one or more paths into a shareable presentation. Dashboards support chart-to-chart filtering (clicking a bar filters other tiles), inline parameter widgets, fullscreen presentation mode, and PDF export. Parameter values are preserved when a viewer navigates between the analysis and the dashboard.

7. **Save as a Dataset.** The entire transformation sequence for a path can be materialized as a new Foundry dataset. Contour serializes the board chain as a **Foundry job**, which integrates with the platform build system. When any upstream dataset changes, the saved dataset can be recomputed automatically, preserving full data lineage.

---

## User interface

Contour's UI is a single-page editor organized into three main regions.

<table>
<tr>
<td style="background:#1C2127;color:#ABB3BF;padding:10px 14px;border:1px solid #383E47;vertical-align:top;min-width:140px"><b style="color:#8ABBFF">Left Sidebar</b></td>
<td style="background:#1C2127;color:#ABB3BF;padding:10px 14px;border:1px solid #383E47">Parameter panel and path list. Create/rename/delete parameters here; each parameter shows its type, default value, and suggestion source. Path tabs appear at the top of the sidebar — click to switch between investigation threads within the same analysis.</td>
</tr>
<tr>
<td style="background:#1C2127;color:#ABB3BF;padding:10px 14px;border:1px solid #383E47;vertical-align:top"><b style="color:#8ABBFF">Canvas (Center)</b></td>
<td style="background:#1C2127;color:#ABB3BF;padding:10px 14px;border:1px solid #383E47">The main working area. Shows the stacked board chain for the active path. Each board renders inline — a histogram renders its bars immediately; a filter board shows its configuration form. Drag boards to reorder. A <span style="color:#2D72D2"><b>+ Add board</b></span> toolbar at the bottom (or between boards) opens the board picker with all available board types organized by category.</td>
</tr>
<tr>
<td style="background:#1C2127;color:#ABB3BF;padding:10px 14px;border:1px solid #383E47;vertical-align:top"><b style="color:#8ABBFF">Right Panel</b></td>
<td style="background:#1C2127;color:#ABB3BF;padding:10px 14px;border:1px solid #383E47">Context-sensitive configuration for the selected board. Contains tabs such as <span style="color:#2D72D2"><b>Options</b></span> (axis selection, grouping, aggregation), <span style="color:#2D72D2"><b>Format</b></span> (axis titles, legend, number units, color), and <span style="color:#2D72D2"><b>Filters</b></span> (board-level filters separate from the Filter board). The Table board shows a 1 000-row snapshot here with conditional formatting controls.</td>
</tr>
<tr>
<td style="background:#1C2127;color:#ABB3BF;padding:10px 14px;border:1px solid #383E47;vertical-align:top"><b style="color:#8ABBFF">Top Bar</b></td>
<td style="background:#1C2127;color:#ABB3BF;padding:10px 14px;border:1px solid #383E47">Analysis name (editable), <span style="color:#238551"><b>Save as Dataset</b></span> action, <span style="color:#2D72D2"><b>Open Dashboard</b></span> navigation, and a <span style="color:#C87619"><b>stale indicator</b></span> when an upstream dataset has changed and the saved output needs rebuilding.</td>
</tr>
</table>

**Board state chips you will encounter:**

<span style="color:#238551"><b>● computed</b></span> — board output is current and rendered  
<span style="color:#C87619"><b>● stale</b></span> — upstream data changed, board needs recompute  
<span style="color:#CD4246"><b>● error</b></span> — expression or join failed; error detail shown inline  
<span style="color:#2D72D2"><b>● selected</b></span> — a chart element is actively filtering downstream boards  

**Key interactions:**
- Click a bar / map cell / histogram bucket → creates a live selection filter that propagates to all boards below in the path.
- `Ctrl/Cmd + Click` on chart elements → multi-select for compound filters.
- Expression board: type column names directly; reference parameters with `$param_name`; autocomplete suggests column names and functions.
- Board picker toolbar: boards grouped as Visualize, Filter, Transform, Integrate — hover any card for a tooltip description before adding.

---

## Worked example

**Scenario:** A supply-chain analyst has a Foundry dataset `shipments` with columns `region`, `carrier`, `delay_days`, and `ship_date`. They want to build an interactive dashboard showing average delay by carrier, filterable by region and date range.

1. Open `shipments` in Foundry and click **Analyze** — Contour opens with the dataset pre-loaded.
2. In the left sidebar, add a **String** parameter `selected_region` with suggestions from the `region` column, and a **Date** parameter `start_date`.
3. Add a **Filter** board → set `region = $selected_region` and `ship_date >= $start_date`.
4. Add a **Chart** board → X-axis: `carrier`, Y-axis: Mean of `delay_days`, chart type: Bar. In the Format tab set Y-axis title to "Avg Delay (days)" and enable descending sort.
5. Add a **Calculation** board below the chart → aggregate: Count of rows (to show total shipments in scope as a KPI card).
6. Click **Open Dashboard** → drag both boards (chart tile + calculation tile) onto the dashboard canvas. Add the two parameters as interactive widgets.
7. Click **Save as Dataset** — Contour serializes the Filter + Chart derivation as a Foundry job. When the upstream `shipments` dataset refreshes nightly, the saved output auto-recomputes.
8. Share the dashboard URL with stakeholders — they use the region dropdown and date picker to explore without touching the analysis.

---

## Documentation map

The following sub-pages exist beneath the Contour tool in the Palantir Foundry docs:

- **Overview** — what Contour is and when to use it
- **Getting started** — tutorial using NYC Census sample data
- **Core concepts** — paths, boards, datasets, parameterization
- **Boards: Overview** — board architecture and data-flow model
- **Boards: Descriptions** — full reference for every board type
- **Analysis: Parameterize your analysis** — parameter types, multi-value, suggestions, cross-filter groups
- **Performance and correctness: Optimizing your analysis** — compute tips for large datasets
- **Administration: Compute Usage** — monitoring and managing Contour compute resources

---

## Official documentation

- [Contour · Overview](https://www.palantir.com/docs/foundry/contour/overview)
- [Contour · Getting started](https://www.palantir.com/docs/foundry/contour/getting-started)
- [Contour · Core concepts](https://www.palantir.com/docs/foundry/contour/core-concepts)
- [Contour · Boards: Overview](https://www.palantir.com/docs/foundry/contour/boards-overview)
- [Contour · Boards: Descriptions](https://www.palantir.com/docs/foundry/contour/boards-descriptions)
- [Contour · Parameterize your analysis](https://www.palantir.com/docs/foundry/contour/analysis-parameterize)
- [Contour · Performance and correctness: Optimizing your analysis](https://www.palantir.com/docs/foundry/contour/performance-optimize)
- [Contour · Administration: Compute Usage](https://www.palantir.com/docs/foundry/contour/compute-usage)
