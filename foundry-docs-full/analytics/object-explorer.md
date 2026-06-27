<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · ANALYTICS</b><br>
<span style="font-size:22px"><b>Object Explorer</b></span><br>
<span style="color:#ABB3BF">A point-and-click search and analysis tool for discovering, filtering, and acting on objects stored in the Ontology — no code required.</span>
</td></tr></table>

## What it is

Object Explorer is Foundry's primary self-service interface for querying the Ontology. It lets any user — from a data analyst to a field operator — search across all object types, slice results with interactive charts, and take bulk Actions (such as writebacks) on the resulting object sets. It requires minimal configuration and is deliberately geared toward less technical users, acting as a front door to Ontology-backed data without requiring SQL or code.

## How it works

Object Explorer sits on top of the **Ontology layer**: every object type, property, link type, and Action that has been registered in the Ontology Manager is immediately queryable here. The tool never reads raw datasets directly — it reads objects (which are backed by datasets but abstracted behind the Ontology).

**End-to-end data flow and mechanics:**

1. **Home page orientation.** When a user opens Object Explorer they land on a home page that lists all non-hidden object type groups (configured in Ontology Manager) in the left nav. A **global search bar** spans the top. Any saved explorations, comparison views, lists, or modules the user has created appear at the top of the page for quick re-entry.

2. **Global search.** Typing in the search bar queries the entire Ontology — it matches object titles, property values, object type names, and artifact names (saved explorations, lists, comparisons, modules). Results are returned across four tabs — **All**, **Objects**, **Object types**, and **Artifacts** — ranked by prominence and result frequency. If more than 250 object types exist, keyword type-ahead is scoped to the first 250. Hidden object types and properties are never surfaced.

3. **Object type selection and preview.** Clicking an object type card opens a **preview panel** that surfaces its description, property list, and linked types. From there the user clicks **Start Exploration** to enter the full exploration context for that type.

4. **Exploration view — chart-driven filtering.** The core of Object Explorer is the **exploration view**, which is a canvas of configurable aggregation charts. Each chart represents an aggregation of one property field on the main object type or a linked type. Available chart types are:
   - **Listogram** — count bars for string/boolean/array properties; click values to include or exclude them.
   - **Histogram** — bucketed bars for numeric or date properties; drag to select a range.
   - **Pie chart** — alternative to listogram for categorical properties.
   - **Grid plot** — 2-D color matrix comparing two property dimensions.
   - **Single statistic** — aggregate scalar (sum, avg, min, max, count, unique count); display only, not filterable.
   - **Statistics table** — aggregates grouped by a property, sortable by any metric.
   - **Cluster map / Choropleth map** — geopoint or geographic-region properties rendered spatially.

   Clicking a chart value applies a **filter to the active object set** — all other charts immediately re-aggregate against the narrowed set, creating a cascading drill-down effect. Charts can also filter across link relationships (a chart on a linked object type's property filters the main type transitively). Up to **five undo/redo states** are tracked per session.

5. **Results table.** The filtered object set is simultaneously rendered in a paginated results table. Columns correspond to object properties marked as `Sortable` or configured for display. Users can reorder columns by drag, resize them, freeze leftmost columns, and toggle text wrapping. **Time series properties** show the latest value plus a sparkline inline. Clicking a row's checkbox opens a **selection preview panel** on the right for up to 20 selected objects.

6. **Object View drill-down.** Clicking a single object opens its **Object View** — a dedicated page (configured separately in Ontology Manager) showing all properties, linked objects, and available Actions for that instance.

7. **Bulk Actions.** Once a filter produces a desired object set, users can execute **Actions** (registered in the Ontology) against the entire set — e.g., a writeback that updates a status field across all matched records. Actions appear automatically in three places in the UI; they can be hidden via the `hubble-oe:hide-action` type class. A successful Action displays a confirmation toast, optionally with a hyperlink to the created/modified object view.

8. **Comparison and export.** Two object sets or two individual objects can be placed in a **side-by-side comparison**. Object sets can be opened in compatible applications (e.g., Quiver) or exported externally.

9. **Saving explorations.** A **saved exploration** persists the full state: object type, applied filters, chart layout, column configuration, and perspective. Reopening it re-executes the same query against current data, so results always reflect live Ontology state. Admins (members of `hubble-exploration-admins` or holding "Object Exploration Admin" permission) can promote a layout to the **global default** for all users.

10. **Dynamic object sets (experimental).** An experimental feature lets Actions consume the exploration's current result set as a **dynamic object set** rather than a static snapshot — the set updates automatically as the underlying data changes within the applied filters. Requires a `hubble-oe-object-set-rid` type class on the Action parameter.

## User interface

<table style="background:#1C2127;border:1px solid #383E47;border-radius:6px;width:100%;border-collapse:collapse">
<thead>
<tr style="background:#252A31">
<th style="color:#8ABBFF;padding:8px 12px;text-align:left;border-bottom:1px solid #383E47">Area</th>
<th style="color:#8ABBFF;padding:8px 12px;text-align:left;border-bottom:1px solid #383E47">What you see</th>
</tr>
</thead>
<tbody>
<tr>
<td style="padding:8px 12px;color:#ABB3BF;border-bottom:1px solid #383E47"><span style="color:#2D72D2"><b>Home page</b></span></td>
<td style="padding:8px 12px;color:#ABB3BF;border-bottom:1px solid #383E47">Global search bar at top; object type group cards in left nav; recent/saved artifacts pinned above the card grid; star icons for favoriting types</td>
</tr>
<tr>
<td style="padding:8px 12px;color:#ABB3BF;border-bottom:1px solid #383E47"><span style="color:#2D72D2"><b>Search results page</b></span></td>
<td style="padding:8px 12px;color:#ABB3BF;border-bottom:1px solid #383E47">Four tabs: All · Objects · Object types · Artifacts; left sidebar with type-group filters; "search around" hover action on individual object results</td>
</tr>
<tr>
<td style="padding:8px 12px;color:#ABB3BF;border-bottom:1px solid #383E47"><span style="color:#2D72D2"><b>Exploration view</b></span></td>
<td style="padding:8px 12px;color:#ABB3BF;border-bottom:1px solid #383E47">2-column chart canvas; "Add chart" card; drag-to-reorder chart headers; resize handles on chart cards; active filter chips across the top; undo/redo controls</td>
</tr>
<tr>
<td style="padding:8px 12px;color:#ABB3BF;border-bottom:1px solid #383E47"><span style="color:#2D72D2"><b>Results table</b></span></td>
<td style="padding:8px 12px;color:#ABB3BF;border-bottom:1px solid #383E47">Paginated rows; sortable column headers; freeze-column toggle; inline edit pencil icon on hover; sparklines for time-series columns; checkbox selection opens right-side preview panel</td>
</tr>
<tr>
<td style="padding:8px 12px;color:#ABB3BF;border-bottom:1px solid #383E47"><span style="color:#2D72D2"><b>Object View</b></span></td>
<td style="padding:8px 12px;color:#ABB3BF;border-bottom:1px solid #383E47">Full-page detail for one object: property list, linked-object panels, Action buttons; layout configured in Ontology Manager</td>
</tr>
<tr>
<td style="padding:8px 12px;color:#ABB3BF"><span style="color:#2D72D2"><b>Action execution</b></span></td>
<td style="padding:8px 12px;color:#ABB3BF">Modal form for Action parameters; on success a toast appears — <span style="color:#238551"><b>● confirmed</b></span>; optional hyperlink to the created/modified object; on failure <span style="color:#CD4246"><b>● error</b></span> message in toast</td>
</tr>
</tbody>
</table>

**Layout conventions.** The app shell uses a <span style="color:#ABB3BF">dark `#111418` background</span> with panels at `#1C2127` and card surfaces at `#252A31`. Borders separate panels at `#383E47`. Primary interactive elements (buttons, active filter chips, links) use <span style="color:#2D72D2">**blue #2D72D2**</span>. Muted labels and secondary text render in <span style="color:#ABB3BF">`#ABB3BF`</span>.

## Worked example

**Scenario:** A logistics analyst wants to find all shipments in the "Delayed" status that originated in the West region, then trigger a bulk notification Action.

1. From the Object Explorer home page the analyst clicks the **Shipments** card (under the "Logistics" object type group) and selects **Start Exploration**.
2. The exploration view loads with a default chart canvas. The analyst clicks **Add chart**, selects the `status` property, and a **Listogram** appears showing counts per status value.
3. The analyst clicks **Delayed** in the listogram and chooses **Keep**. The active object set narrows; all other charts re-aggregate against delayed shipments only.
4. The analyst adds a second chart on `origin_region` (another Listogram), then clicks **West** → **Keep**. The count in the header drops to the matched set.
5. Switching to the **Results table** tab, the analyst freezes the `shipment_id` and `eta` columns, sorts by `eta` ascending, and quickly scans overdue items.
6. The analyst selects all objects (checkbox in the header row), clicks the **Send Delay Alert** Action button, fills in the notification template parameter in the modal, and submits. A <span style="color:#238551"><b>● success</b></span> toast confirms the writeback completed.
7. The analyst clicks **Save exploration**, names it "West Delayed Shipments – Daily Check", and the exploration is pinned to the home page for tomorrow's review against fresh data.

## Documentation map

- **Overview** — tool introduction, design philosophy, key capabilities
- **Getting started** — home page walkthrough, object type cards, favorites, graph view of type relationships
- **Search and explore objects**
  - Search for objects — search scope, results tabs, sidebar filters, "search around"
  - Search syntax — advanced query operators
  - Analyze using SQL — running SQL against object sets
- **Analyze and compare**
  - Explore with charts — chart types, filter mechanics, linked-type charts, layout management
  - View results — table sorting/columns, freeze, sparklines, inline edits, preview panel, object comparison
  - Apply Actions — bulk Actions, dynamic object sets, Action configuration
  - Save explorations — saving, sharing, default layouts, admin layout management
- **Configure Object Explorer** — object type groupings, action success toasts, hiding actions, dynamic object sets, default layout administration

## Official documentation

- [Object Explorer · Overview](https://www.palantir.com/docs/foundry/object-explorer/overview)
- [Object Explorer · Getting started](https://www.palantir.com/docs/foundry/object-explorer/getting-started)
- [Object Explorer · Search for objects](https://www.palantir.com/docs/foundry/object-explorer/search-objects)
- [Object Explorer · Search syntax](https://www.palantir.com/docs/foundry/object-explorer/search-syntax)
- [Object Explorer · Explore with charts](https://www.palantir.com/docs/foundry/object-explorer/explore-charts)
- [Object Explorer · View results](https://www.palantir.com/docs/foundry/object-explorer/view-results)
- [Object Explorer · Apply Actions](https://www.palantir.com/docs/foundry/object-explorer/apply-actions)
- [Object Explorer · Save explorations](https://www.palantir.com/docs/foundry/object-explorer/save-explorations)
- [Object Explorer · Analyze using SQL](https://www.palantir.com/docs/foundry/object-explorer/analyze-sql)
- [Object Explorer · Configure Object Explorer](https://www.palantir.com/docs/foundry/object-explorer/configure)
