<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · ANALYTICS</b><br>
<span style="font-size:22px"><b>Quiver</b></span><br>
<span style="color:#ABB3BF">No-code analytics canvas for exploring and visualizing Ontology object and time series data through chainable cards.</span>
</td></tr></table>

## What it is

Quiver is a no-code analytics platform embedded in Palantir Foundry that provides a point-and-click interface for performing data analysis directly on object sets and time series data sourced from the Ontology. Users build analyses by connecting typed **cards** — visual building blocks that each accept defined inputs and emit defined outputs — into dependency chains that produce charts, tables, pivot results, and dashboards without writing code. Finished analyses can be published as interactive dashboards, embedded into operational applications (Workshop), or surfaced as widgets in Notepad reports.

---

## How it works

### 1. Data enters from the Ontology
Every analysis begins with one or more **data cards** — either an **object type** card (pulling a live object set from the Ontology) or a **time series** card (pointing at a time series property or sync). Quiver reads these directly from the Ontology at query time; no intermediate exports are needed. Object relationships defined in the Ontology are natively traversable, so joining across linked types requires no manual SQL.

### 2. Cards form a typed dependency graph
The foundational mechanic is Quiver's **data model**: every card accepts zero or more inputs of specific types and produces a single output of a specific type. The enforced type system means a card can only be wired to a downstream card if its output type matches that card's required input type. The full type vocabulary includes:

- **Collections**: Object set, Time series, Transform table, Materialization, Event set
- **Scalars**: String, Number, Time, Boolean, Duration
- **Structured outputs**: Categorical chart, Pivot table, Time series chart
- **Arrays & ranges**: String/Number/Time/Boolean arrays, Numeric range, Time range, X/Y range

Cards chain left-to-right (visible in Graph mode): source → filter/transform → aggregate/visualize → result. Over 100 card types exist across categories including filtering, joining, calculating, transforming, converting, and visualizing.

### 3. Canvas vs. Graph — two views of the same graph
Quiver maintains a **single underlying dependency graph** that is simultaneously visible in two modes. Switching modes never changes the computation, only the presentation:

- **Canvas mode** (default): a free-form page where cards are displayed as resizable tiles. Multiple named canvases (tabs) can exist per analysis. Only cards on the active canvas are computed, improving performance. Rearranging cards on a canvas does not affect the execution order.
- **Graph mode**: cards become nodes connected by typed edges drawn left-to-right, showing the full data lineage. Useful for inspecting dependencies and debugging complex chains. Cards added in graph mode are not automatically placed on a canvas.

### 4. Parameterization for dynamic analysis
**Parameter cards** expose user-adjustable inputs (dropdowns, sliders, text inputs) that feed into downstream cards. When a dashboard consumer changes a parameter value, only the downstream cards that depend on it recompute. This enables a single analysis to serve multiple perspectives without duplication.

### 5. Advanced transformations: Transform tables and Materializations
When built-in filter/aggregate cards are insufficient, users can drop in a **Transform table** card — a flexible local table that supports formula-based column derivations and multi-step data reshaping. **Materialization** cards back aggregated results by a Foundry dataset, enabling large-scale pre-aggregation that survives session close. Both are typed outputs that feed into downstream visualization cards like any other card.

### 6. Formulas
Quiver ships a proprietary **formula language** used inside calculation cards, derived-column cards, and transform tables. For time series specifically, a dedicated **time series library** provides sensor and signal-processing functions (resampling, rolling windows, interpolation, event detection) optimized for high-frequency signals and backed by a purpose-built time series database.

### 7. Publishing and embedding
When the analysis is ready, the **Dashboards side panel** converts one or more canvases into published **dashboards** — standalone interactive views shareable with other Foundry users. Dashboard tiles respect parameter widgets so consumers interact with live data. Dashboards can also be embedded as widgets in **Workshop** (operational apps) or as template canvases in **Notepad** (reports). **Writeback** is possible via **Actions** wired to result cards, persisting analytical conclusions back to the Ontology.

### 8. State and concurrency
Quiver auto-saves working state between explicit saves and encodes analysis state in URL variables (enabling shareable deep links). Multiple users can open the same analysis concurrently and work independently; explicit saves overwrite the previous version.

---

## User interface

### Overall layout

The workspace is divided into a **top bar**, **left-side panel rail**, and the **main canvas/graph area**.

| Zone | Description |
|------|-------------|
| <span style="color:#8ABBFF">**Workspace Header**</span> | Far top-left: Undo / Redo, Analysis history, Save, Share, and the Details panel toggle (access / metadata). |
| <span style="color:#8ABBFF">**Analysis Top Bar**</span> | "Add data cards" button and "Search cards" to browse all 100+ card types by name or category. |
| <span style="color:#8ABBFF">**View Mode Toggle**</span> | Top-right corner: switch between Canvas and Graph modes. |
| <span style="color:#8ABBFF">**Canvas Tabs**</span> | Bottom of workspace: named canvas pages. Create via the **+** icon (lower-left). |
| <span style="color:#8ABBFF">**Left Panel Rail**</span> | Five collapsible icon-triggered panels (see below). |
| <span style="color:#8ABBFF">**Main Area**</span> | Canvas: free-form tile grid. Graph: left-to-right node/edge diagram. |

### Left-side panels (rail icons)

<table style="background:#1C2127;border:1px solid #383E47;border-radius:4px;padding:8px;width:100%">
<tr style="border-bottom:1px solid #383E47">
  <td style="color:#8ABBFF;padding:6px 10px"><b>Analysis Contents</b></td>
  <td style="color:#ABB3BF;padding:6px 10px">Hierarchical list of all cards; eye icons toggle visibility; drag to move cards between canvases.</td>
</tr>
<tr style="border-bottom:1px solid #383E47">
  <td style="color:#8ABBFF;padding:6px 10px"><b>Parameters</b></td>
  <td style="color:#ABB3BF;padding:6px 10px">Define and manage parameter cards exposed to dashboard consumers.</td>
</tr>
<tr style="border-bottom:1px solid #383E47">
  <td style="color:#8ABBFF;padding:6px 10px"><b>Visual Functions</b></td>
  <td style="color:#ABB3BF;padding:6px 10px">Reusable formula-based logic shared across cards in the analysis.</td>
</tr>
<tr style="border-bottom:1px solid #383E47">
  <td style="color:#8ABBFF;padding:6px 10px"><b>Dashboards</b></td>
  <td style="color:#ABB3BF;padding:6px 10px">Publish canvases as dashboards; configure what consumers can interact with.</td>
</tr>
<tr>
  <td style="color:#8ABBFF;padding:6px 10px"><b>Settings</b></td>
  <td style="color:#ABB3BF;padding:6px 10px">Analysis-level configuration (time zone, default time range, etc.).</td>
</tr>
</table>

### Card interactions

Each card tile on the canvas shows its **output type** in the header. Hovering reveals a <span style="color:#2D72D2">**Next Actions menu**</span> below the card — a contextual list of compatible downstream cards (grouped: filter, visualize, calculate, join, transform, convert) with a search field. Clicking an action inserts a new connected card directly below.

Tile manipulation: drag the <span style="color:#ABB3BF">upper-left handle</span> to move; drag the <span style="color:#ABB3BF">lower-right corner</span> to resize. The Card Editor panel (opens on selection) shows a collapsible **Dependencies** section listing all upstream/downstream cards, with click-to-navigate links.

In <span style="color:#2D72D2">**Graph mode**</span>, nodes render compactly (title + type). Right-clicking a node opens: View dependencies, Add to canvas, Color group, Hide, Delete. The **Preview Panel** at the bottom displays the selected node's output; multiple previews can be pinned for side-by-side comparison. Eligible input nodes highlight when you are selecting a card's input.

### Status indicators

<span style="color:#238551"><b>● computed</b></span> — card output is current and valid  
<span style="color:#C87619"><b>● stale / computing</b></span> — upstream input has changed; result pending  
<span style="color:#CD4246"><b>● error</b></span> — type mismatch or data issue  
<span style="color:#2D72D2"><b>● selected / active canvas</b></span> — currently focused card or tab

---

## Worked example

**Scenario**: An operations analyst wants to see the average response time per region for all open service tickets, filterable by ticket priority.

1. **Add data card** — select the `ServiceTicket` object type from the Ontology. This produces an **object set** card containing all tickets.
2. **Filter** — from the Next Actions menu choose "Filter by property"; filter to `status = Open`. Output: filtered object set.
3. **Add parameter** — insert a String parameter card `priority_filter` with values `["P1","P2","P3","All"]`. Wire it as the value input to a second filter card (`priority = priority_filter`).
4. **Group & aggregate** — add a "Group by" card, grouping by `region`; add an aggregation card computing `mean(response_time_hours)`. Output: categorical chart.
5. **Visualize** — add a Bar Chart card consuming the categorical chart output. The chart renders on the canvas.
6. **Organize** — rename the canvas "Response Time by Region". Drag the parameter tile to the top-left so dashboard consumers see the control first.
7. **Publish** — open the Dashboards panel, create a dashboard from this canvas. Share with the operations team; they change the priority dropdown and the bar chart recomputes live.

---

## Documentation map

Sub-pages and sections documented under Quiver in the Palantir Foundry docs:

- **Overview** — what Quiver is and when to use it
- **Core concepts** — cards, data model, canvas vs. graph, parameters, dashboards, state
- **Getting started** — first analysis walkthrough
- **Analysis overview** — anatomy of an analysis resource
- **Analysis data model** — full type vocabulary and connection rules
- **Analysis types** — object, time series, and mixed analyses
- **Analysis canvas** — canvas mode UI, multi-canvas management, card organization
- **Analysis graph** — graph mode UI, dependency view, color groups
- **Analysis toolbars** — workspace header, top bar, next actions menu, search bar, side panels
- **AIP features** — AI/LLM-powered interactions within Quiver
- **Cards — Overview** — card categories, how cards chain, 100+ card reference
- **Best practices** — performance, canvas organization, parameterization guidance
- **Notepad integration** — Quiver template canvas widget in Notepad reports

---

## Official documentation

- [Quiver — Overview](https://www.palantir.com/docs/foundry/quiver/overview)
- [Quiver — Core concepts](https://www.palantir.com/docs/foundry/quiver/core-concepts)
- [Quiver — Analysis data model](https://www.palantir.com/docs/foundry/quiver/analysis-data-model)
- [Quiver — Analysis canvas](https://www.palantir.com/docs/foundry/quiver/analysis-canvas)
- [Quiver — Analysis graph](https://www.palantir.com/docs/foundry/quiver/analysis-graph)
- [Quiver — Analysis toolbars](https://www.palantir.com/docs/foundry/quiver/analysis-toolbars)
- [Quiver — Cards overview](https://www.palantir.com/docs/foundry/quiver/cards-overview)
- [Quiver — Best practices](https://www.palantir.com/docs/foundry/quiver/quiver-best-practices)
- [Quiver — AIP features](https://www.palantir.com/docs/foundry/quiver/quiver-aip/index.html)
- [Quiver — Getting started](https://www.palantir.com/docs/foundry/quiver/getting-started)
