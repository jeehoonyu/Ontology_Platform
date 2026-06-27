<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · APPLICATIONS</b><br>
<span style="font-size:22px"><b>Slate</b></span><br>
<span style="color:#ABB3BF">A drag-and-drop, low-code application builder for creating dynamic, Ontology-connected web apps inside Foundry.</span>
</td></tr></table>

## What it is

Slate is Palantir Foundry's low-code/no-code application development environment. It lets builders construct fully custom, interactive web applications — dashboards, operational tools, data-entry forms, public-facing portals — using a drag-and-drop canvas, without requiring traditional full-stack engineering. Applications can read from and write to the Foundry Ontology, call Foundry Functions, run SQL queries against synced datasets, and call external REST APIs, all wired together through a reactive dependency graph. Every visual element is customizable via Less/CSS, enabling precise brand alignment or experimental layouts.

---

## How it works

Slate's runtime is built around a **reactive dependency graph**: every widget, function, variable, and query is a **node** in a directed graph, and Slate automatically re-evaluates downstream nodes whenever an upstream dependency changes. This eliminates manual wiring of "refresh" logic — builders declare connections, and the runtime handles ordering and re-execution.

### Execution and data-flow mechanics

1. **Application load.** When a user opens a Slate app, Foundry initialises all nodes in the dependency graph. Queries marked to run on load fire immediately; others wait for their dependency conditions to be satisfied.

2. **Widget state as source.** Every widget (dropdown, text input, date picker, etc.) exposes its current value as a node in the graph. Other nodes reference widget values using **Handlebars** double-brace syntax: `{{widgetId.value}}`. Changing a widget's value marks its dependents as stale and triggers re-computation.

3. **Variables.** Mutable state containers that store arbitrary values (strings, numbers, JSON objects). They can be set by Events/Actions, pre-populated from URL parameters, or hold intermediate computation results. Variables are also graph nodes — changing a variable re-evaluates everything that depends on it.

4. **Queries.** Queries are the primary data ingress/egress mechanism. Slate supports four types:
   - **Ontology / Object Set queries** — the recommended path; reads structured object data from the Foundry Ontology SDK.
   - **Foundry Functions queries** — calls serverless TypeScript/Java functions for computed or aggregated results.
   - **SQL (Postgres) queries** — executes parameterised SQL against Foundry-synced Postgres datasets; uses mandatory security helpers (`schema`, `table`, `column`, `param`) to prevent injection.
   - **HTTP JSON queries** — calls external REST endpoints; response fields are extracted with JSONPath; Handlebars values must be wrapped in `jsonStringify`.
   All query results are normalised to JSON before entering the graph, unifying data from heterogeneous sources into a single structure for downstream processing.

5. **Functions.** Inline JavaScript snippets that act as pure transform nodes. A function reads upstream values via Handlebars (widget states, variable values, query results), processes them, and outputs a new value. Functions re-run whenever any referenced upstream node changes. They are commonly used to reshape query results, build conditional CSS class strings, or prepare parameters for subsequent queries.

6. **Events and Actions.** Events are triggers (button click, row select, page load, timer) that fire an ordered list of **Actions** in response. Actions can: set a variable, run a query on-demand, open/close a modal, navigate to another page, trigger a Foundry **Action** (write-back to the Ontology), or show a toast notification. Events close the loop from user interaction back into the graph, enabling full read-write application workflows.

7. **Ontology write-back.** The dedicated **Actions widget** (a Platform widget) binds to a configured Foundry Action definition, presents users with a form, validates inputs, and submits the write directly to the Ontology. This is the canonical path for creating, editing, or deleting Ontology objects from a Slate app.

8. **Rendering.** On each re-evaluation, widgets re-render using their newly resolved input values. Because styling is compiled from **Less** at load time (not at runtime), dynamic visual changes are achieved by using Handlebars to swap predefined CSS class names — not by mutating raw style strings.

9. **Versioning and deployment.** Finished applications are versioned inside Foundry. Builders can publish a stable version while continuing to develop on a draft. Applications can optionally be exposed on the public internet (without a Foundry login) for use cases like external data submission.

---

## User interface

The Slate editor is a single-page builder divided into four persistent regions plus a set of pop-out overlay panels.

### Editor layout

<table style="border-collapse:collapse;width:100%;background:#1C2127;color:#fff;font-size:13px">
<tr style="background:#252A31">
  <th style="padding:8px 12px;border:1px solid #383E47;text-align:left">Region</th>
  <th style="padding:8px 12px;border:1px solid #383E47;text-align:left">Location</th>
  <th style="padding:8px 12px;border:1px solid #383E47;text-align:left">What it contains</th>
</tr>
<tr>
  <td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF"><b>Action Bar</b></span></td>
  <td style="padding:8px 12px;border:1px solid #383E47">Top</td>
  <td style="padding:8px 12px;border:1px solid #383E47">App name, Actions dropdown (import/export/version), preview-mode toggle, pop-out launchers for Queries, Functions, Config, Events, Styles, Variables, Dependencies</td>
</tr>
<tr style="background:#252A31">
  <td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF"><b>Widget List</b></span></td>
  <td style="padding:8px 12px;border:1px solid #383E47">Left panel</td>
  <td style="padding:8px 12px;border:1px solid #383E47">Hierarchical tree of all widgets on the page (toolbar widgets separated from canvas widgets); drag to reorder; click to select</td>
</tr>
<tr>
  <td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF"><b>Canvas</b></span></td>
  <td style="padding:8px 12px;border:1px solid #383E47">Center</td>
  <td style="padding:8px 12px;border:1px solid #383E47">Live WYSIWYG workspace; drag widgets from the palette onto the canvas; resize, reposition, and drop into containers; screen-size preview dropdown (desktop/tablet/mobile)</td>
</tr>
<tr style="background:#252A31">
  <td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF"><b>Widget Editor</b></span></td>
  <td style="padding:8px 12px;border:1px solid #383E47">Right panel</td>
  <td style="padding:8px 12px;border:1px solid #383E47">Three tabs: <b>Property</b> (widget-specific settings), <b>Layout</b> (size, padding, alignment), <b>JSON</b> (raw config); some widgets add an <b>Events</b> tab</td>
</tr>
</table>

### Widget palette

Widgets are grouped into categories accessible from the Action Bar's widget-add control:

<span style="color:#2D72D2"><b>Chart</b></span> · <span style="color:#2D72D2"><b>Container</b></span> · <span style="color:#2D72D2"><b>Control</b></span> · <span style="color:#2D72D2"><b>Platform</b></span> · <span style="color:#2D72D2"><b>Text</b></span> · <span style="color:#2D72D2"><b>Time</b></span> · <span style="color:#2D72D2"><b>Visualization</b></span> · <span style="color:#2D72D2"><b>Advanced</b></span>

Platform widgets include the **Object Set panel**, **Object Context panel**, and the **Actions widget** for Ontology integration.

### Pop-out overlay panels

Launched from the Action Bar, these panels float over the canvas:

- <span style="color:#8ABBFF">**Queries editor**</span> — create/edit queries, set run conditions (e.g. "run when dependencies are not null"), view raw results as JSON.
- <span style="color:#8ABBFF">**Functions editor**</span> — write and test JavaScript transform snippets with a live output preview.
- <span style="color:#8ABBFF">**Variables editor**</span> — declare variables, set default values, and link to URL parameters.
- <span style="color:#8ABBFF">**Events editor**</span> — define event sources (widget interactions, page load, timers) and chain Action sequences.
- <span style="color:#8ABBFF">**Styles panel**</span> — write Less/CSS classes that can be applied to any widget via the `Additional Classes` property field.
- <span style="color:#8ABBFF">**Dependency graph**</span> — visual directed graph showing all nodes and their connections; useful for debugging stale or circular dependencies.

### Multi-select and alignment

Hold <kbd>Ctrl</kbd> / <kbd>Cmd</kbd> and click multiple widgets on the canvas or in the Widget List to select them simultaneously. The right panel then shows alignment and distribution controls (align left, center, right, top, middle, bottom; distribute horizontally or vertically).

### Global search

<kbd>Ctrl+K</kbd> / <kbd>Cmd+K</kbd> opens a command palette that searches queries, functions, variables, widgets, and Ontology objects, with search history.

### Node state indicators

<span style="color:#238551"><b>● resolved</b></span> — node has a valid, current value · <span style="color:#C87619"><b>● stale / loading</b></span> — upstream dependency changed, re-evaluation in progress · <span style="color:#CD4246"><b>● error</b></span> — query failed or function threw · <span style="color:#2D72D2"><b>● running</b></span> — query or function actively executing

---

## Worked example

**Scenario:** An operations team needs a live dashboard showing all open maintenance tickets (Ontology objects), with a button to mark a ticket as "Resolved."

1. **Add an Object Set widget** (Platform category) → point it at the `MaintenanceTicket` Ontology object type → filter to `status = "Open"`. This widget populates a node in the graph.

2. **Add a Table widget** → bind its `data` property to `{{objectSetWidget.objects}}`. The table renders live rows from the Ontology.

3. **Add a Button widget** labeled "Mark Resolved" → in its Events tab, add an **On Click** event → Action: **Trigger Foundry Action** → select the `resolveTicket` Action, passing `{{tableWidget.selectedRow.ticketId}}` as the input parameter.

4. In the **Styles panel**, write `.resolved-btn { background-color: #238551; color: #fff; border-radius: 4px; }` and apply the class to the button via its `Additional Classes` field.

5. Publish a new version. Users open the app, see only open tickets, click the button on any row, and the write-back fires the Foundry Action — updating the Ontology object in place. The Object Set widget auto-refreshes, and the resolved ticket disappears from the table.

---

## Documentation map

The following sub-pages exist beneath the Slate tool in the Foundry docs:

- **Overview** — introduction, capabilities summary, public-access apps
- **Logic > Overview** — dependency graph model, primitives summary
- **Logic > Access values with Handlebars** — `{{ }}` syntax, helpers, scoping
- **Logic > Events and actions index** — all available event types and action types
- **Logic > Define and run Slate functions** — JavaScript snippets, inputs/outputs
- **Logic > Understand dependencies** — dependency graph, best practices
- **Read and write data > Overview** — data import/export mechanisms, trade-offs
- **Read and write data > Read and write to data systems** — query configuration, SQL security helpers, JSONPath
- **Widgets > Container** — layout containers, nesting rules
- **Widgets > Control** — inputs, buttons, dropdowns, sliders
- **Widgets > Platform** — Object Set panel, Object Context panel, Actions widget
- **Widgets > Chart** — chart widget types and configuration
- **Widgets > Visualization** — advanced visualisation widgets
- **Widgets > Advanced** — HTML widget, custom code widget
- **Styles > Style overview** — Less/CSS styling system, Blueprint integration
- **Styles > Configure and apply styles** — per-widget vs. stylesheet approach
- **Styles > Build complex layouts** — responsive layout patterns
- **Styles > Global stylesheets [Experimental]** — org-wide reusable CSS
- **Navigation** — editor navigation, canvas controls, keyboard shortcuts
- **FAQ** — common questions and answers

---

## Official documentation

- [Slate · Overview](https://www.palantir.com/docs/foundry/slate/overview)
- [Slate · Style Overview](https://www.palantir.com/docs/foundry/slate/style-overview)
- [Slate · Logic · Overview](https://www.palantir.com/docs/foundry/slate/logic-overview)
- [Slate · Logic · Access values with Handlebars](https://www.palantir.com/docs/foundry/slate/concepts-handlebars)
- [Slate · Logic · Events and actions index](https://www.palantir.com/docs/foundry/slate/concepts-events-and-actions-index)
- [Slate · Logic · Define and run Slate functions](https://www.palantir.com/docs/foundry/slate/concepts-functions)
- [Slate · Logic · Understand dependencies](https://www.palantir.com/docs/foundry/slate/best-practices-app-functionality)
- [Slate · Read and write data · Overview](https://www.palantir.com/docs/foundry/slate/read-write-overview)
- [Slate · Read and write data · Read and write to data systems](https://www.palantir.com/docs/foundry/slate/concepts-queries)
- [Slate · Styles · Configure and apply styles](https://www.palantir.com/docs/foundry/slate/concepts-styles)
- [Slate · Styles · Build complex layouts](https://www.palantir.com/docs/foundry/slate/best-practices-complex-layouts)
- [Slate · Widgets · Container](https://www.palantir.com/docs/foundry/slate/widgets-container)
- [Slate · Widgets · Control](https://www.palantir.com/docs/foundry/slate/widgets-control)
- [Slate · Widgets · Platform](https://www.palantir.com/docs/foundry/slate/widgets-platform)
- [Slate · Widgets · Visualization](https://www.palantir.com/docs/foundry/slate/widgets-visualization)
- [Slate · Widgets · Advanced](https://www.palantir.com/docs/foundry/slate/widgets-advanced)
- [Slate · Navigation](https://www.palantir.com/docs/foundry/slate/navigation)
- [Slate · FAQ](https://www.palantir.com/docs/foundry/slate/faq)
- [Slate · Core concepts · Overview](https://www.palantir.com/docs/foundry/slate/concepts-overview/)
