<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · APPLICATIONS</b><br>
<span style="font-size:22px"><b>Workshop</b></span><br>
<span style="color:#ABB3BF">A no-code/low-code application builder for creating interactive operational UIs directly on top of the Ontology.</span>
</td></tr></table>

## What it is

Workshop is Palantir Foundry's drag-and-drop application builder that lets analysts and engineers create fully interactive, production-grade web applications without writing frontend code. Applications are built on top of the **Object Data Layer** — objects, properties, object sets, Actions, and Functions — and the resulting modules run live against Foundry's ontology at runtime. Workshop targets operational users who need real-time situational awareness, task management, or workflow tooling.

## How it works

Workshop applications are called **modules**. Each module is a self-contained resource in Foundry composed of four interlocking building blocks: **Layouts**, **Widgets**, **Variables**, and **Events**. Together they form a reactive dataflow graph that is evaluated lazily at runtime.

**End-to-end mechanics:**

1. **Module creation.** A builder creates a new Workshop module via Projects & Files → New → Workshop module. The module opens in the visual builder editor.

2. **Layout scaffolding.** The builder constructs a page hierarchy using layout components:
   - **Header** — a persistent toolbar (horizontal or vertical) that spans all pages and holds global navigation tabs, button groups, and an optional logo.
   - **Pages** — discrete screens within the module. Only the header persists across pages; each page holds its own widget set.
   - **Sections** — subdivisions within a page or overlay. Sections support six layout modes: *Columns*, *Rows*, *Tabs*, *Flow* (vertical scroll), *Toolbar* (compact horizontal), and *Loop* (repeats an embedded sub-module over each object in an object set).
   - **Overlays** — contextual panels that appear above a page as either a *Drawer* (slides in from left or right) or a *Modal* (centered dialog).

3. **Widget placement.** The builder drags widgets into sections from the Add widget panel. Widgets are the leaf-level UI components (tables, charts, forms, buttons, maps, etc.). Each widget declares:
   - **Input variables** — data it will render (e.g., an object set to display in a table).
   - **Output variables** — state it publishes when a user interacts (e.g., the currently selected row in a table).

4. **Variable wiring.** Variables are the connective tissue between widgets and the Ontology. A variable is typed (Object set, String, Numeric, Boolean, Date, Timestamp, GeoPoint, GeoShape, Array, Struct, or Time series set) and has a **definition type** that controls how it is populated:
   - *Static* — a literal value set by the builder.
   - *Object set definition* — a live query against an object type with optional filters and linked-object traversals.
   - *Function* — output of a Foundry Function (TypeScript/Java) evaluated at runtime.
   - *Object set aggregation* — a computed aggregate (count, sum, average, etc.) derived from an object set variable.
   - *Object property* — a single property value from a selected object.
   - *Variable transformation* — a pipeline of operations referencing other variables.

   Variables recompute according to their **recompute behavior**: *Automatic* (default — recomputes whenever any dependency changes), *Event-triggered* (only on explicit user action), or *Load and event* (on module load plus events). In view mode, variables compute **lazily** — only when they are consumed by a visible widget on the active page or overlay, so hidden pages incur no compute cost until navigated to.

5. **Event configuration.** Events are attached to widgets and layout elements to describe what happens when a user acts. Event types include:
   - *Layout events* — navigate to a page, expand/collapse a section, switch tabs.
   - *Variable events* — reset, recompute, or set a variable's value from another variable.
   - *Layer events* — open or close a drawer or modal overlay.
   - *AIP Assist events* — send a prompt to an AI chatbot configured in the module.
   - *Application events* — open another Foundry resource in a new tab with variable mapping.
   - *Data staleness* — force a full module data refresh.
   
   Events execute **sequentially** in the order configured but do not block on downstream variable recomputation — the source variable value is copied immediately and downstream propagation happens asynchronously.

6. **Actions and Functions.** Widgets can invoke Ontology **Actions** (writeback operations) and call **Functions on Objects (FOO)** for business logic. A Button Group widget, for example, can trigger an Action with pre-populated parameters derived from the active object in a table, enabling in-app editing and task resolution without leaving the module.

7. **Publishing.** When development is complete the builder publishes a **versioned** snapshot. Operational users access only published versions; the builder sees a live draft. Modules can also be distributed via the Foundry Marketplace.

## User interface

The Workshop builder opens in a split-pane editor. The overall shell uses Foundry's dark chrome (<span style="background:#111418;color:#ABB3BF;padding:2px 6px;border-radius:3px">app bg #111418</span>).

<table style="border-collapse:collapse;width:100%">
<tr style="background:#1C2127;color:#fff">
  <th style="padding:8px 12px;border:1px solid #383E47;text-align:left">Area</th>
  <th style="padding:8px 12px;border:1px solid #383E47;text-align:left">What you see</th>
</tr>
<tr style="background:#252A31">
  <td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF"><b>Left sidebar</b></span></td>
  <td style="padding:8px 12px;border:1px solid #383E47">Tabbed panels: <b>Layout</b> (page/section tree), <b>Variables</b> (variable list + dependency graph), <b>Events</b> (global event log), <b>Permissions</b>. A search bar filters items within each panel.</td>
</tr>
<tr style="background:#1C2127">
  <td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF"><b>Canvas (center)</b></span></td>
  <td style="padding:8px 12px;border:1px solid #383E47">Live WYSIWYG preview of the active page with drag-and-drop widget placement. The canvas switches between <span style="color:#2D72D2"><b>Edit mode</b></span> and <span style="color:#238551"><b>Preview mode</b></span> via the top toolbar toggle.</td>
</tr>
<tr style="background:#252A31">
  <td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF"><b>Right config panel</b></span></td>
  <td style="padding:8px 12px;border:1px solid #383E47">Context-sensitive configuration for the selected widget or section: data bindings, display options, sizing (Auto / Absolute / Flex), conditional visibility, and event handlers. The <b>Add widget</b> button at the top opens the widget picker.</td>
</tr>
<tr style="background:#1C2127">
  <td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF"><b>Top toolbar</b></span></td>
  <td style="padding:8px 12px;border:1px solid #383E47">Module name, Edit/Preview toggle, page selector breadcrumb, <span style="color:#2D72D2"><b>Publish</b></span> button, and the Performance Profiler icon.</td>
</tr>
<tr style="background:#252A31">
  <td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#8ABBFF"><b>Variable panel</b></span></td>
  <td style="padding:8px 12px;border:1px solid #383E47">List of all variables with type badges. A graph button opens the <b>Variable Dependency Graph</b> — a directed acyclic graph visualizing how variables feed into each other and which widgets consume them.</td>
</tr>
</table>

**State indicators used in events and variables:**

<span style="color:#238551"><b>● computed / fresh</b></span> · <span style="color:#C87619"><b>● stale / recomputing</b></span> · <span style="color:#CD4246"><b>● error</b></span> · <span style="color:#2D72D2"><b>● primary action / publish</b></span> · <span style="color:#ABB3BF"><b>● muted / hidden</b></span>

Widgets are sized using three modes: **Auto** (shrinks/grows to content), **Absolute** (fixed pixel dimensions), and **Flex** (proportional fill within the parent section). Sections can be set as collapsible, with an optional section header title and icon drawn from the Blueprint icon library.

## Worked example

**Scenario: Flight Alert Inbox for an airline operations supervisor.**

1. Builder opens a new Workshop module and names it "Flight Alert Inbox."
2. On the default page, a three-column section is created: left (Filter List), center (Object Table), right (Object View + Button Group).
3. A variable `flightAlerts` is defined as an *Object set definition* pointing to the `[Example Data] Flight Alert` object type.
4. A second variable `filteredAlerts` is left as a passthrough; the **Filter List** widget is dropped into the left column with `flightAlerts` as its base object set. Its output variable `filterList1FilterOutput` is produced automatically.
5. The **Object Table** widget is placed in the center column, its input bound to `filterList1FilterOutput`. Columns are added via "Add all properties" and sorted by `Flight Date` descending. The table publishes an output variable `objectTable1ActiveObject` (the selected row).
6. A collapsible right column (500 px absolute width) holds an **Object View** widget bound to `objectTable1ActiveObject`, and a **Button Group** widget with a "Resolve Alert" button (Success intent, tick icon) that fires the `[Example Data] De-escalate Flight Alert` Action with `objectTable1ActiveObject` pre-mapped to the action's object parameter.
7. The module header is given an airplane icon (Red 3 Blueprint color) and the title "Flight Alert Inbox."
8. Builder clicks **Publish** → operational users receive a versioned URL. Selecting any row immediately loads the object detail panel; clicking "Resolve Alert" triggers the writeback Action and the table refreshes automatically.

## Documentation map

The Workshop documentation tree covers the following major sections:

- **Core concepts** — Layouts, Widgets, Variables, Events, Permissions
- **Variable types and usage** — Struct variables, Variable transformations, Derived properties
- **Actions** — Actions overview, inline actions
- **Functions on Objects (FOO)** — Functions overview, using functions in Workshop
- **Widgets reference** — Each widget category (display, visualization, filtering, event-trigger, AIP, embedding)
- **Layout & navigation** — Routing, Tabs, Loop layouts
- **Interactivity** — Cross-application interactivity, State saving, Auto-refresh, Scenarios
- **AIP integration** — AIP Analyst widget, AIP Chatbot widget, AIP Generated Content widget, AIP Assist events
- **Mobile** — Mobile overview, mobile getting started
- **Performance & debugging** — Performance Profiler, Variable dependency graph
- **Publishing & distribution** — Versions and publishing, Changelog panel, Marketplace integration, Kiosk mode
- **Best practices** — Application design best practices, component best practices, FAQs
- **Getting started** — Tutorial (Flight Alert Inbox), Example applications
- **Embedding** — Embed Workshop modules overview, Embedded Modules widget, Iframe widget

## Official documentation

- [Workshop — Overview](https://www.palantir.com/docs/foundry/workshop/overview)
- [Workshop — Core concepts: Layouts](https://www.palantir.com/docs/foundry/workshop/concepts-layouts)
- [Workshop — Core concepts: Widgets](https://www.palantir.com/docs/foundry/workshop/concepts-widgets)
- [Workshop — Core concepts: Events](https://www.palantir.com/docs/foundry/workshop/concepts-events)
- [Workshop — Core concepts: Variables](https://www.palantir.com/docs/foundry/workshop/concepts-variables)
- [Workshop — Getting started (Flight Alert Inbox tutorial)](https://www.palantir.com/docs/foundry/workshop/getting-started)
- [Workshop — Example applications](https://www.palantir.com/docs/foundry/workshop/example-applications)
- [Workshop — Actions overview](https://www.palantir.com/docs/foundry/workshop/actions-overview)
- [Workshop — Functions on Objects overview](https://www.palantir.com/docs/foundry/workshop/functions-overview)
- [Workshop — Versions and publishing](https://www.palantir.com/docs/foundry/workshop/versions)
- [Workshop — Performance Profiler](https://www.palantir.com/docs/foundry/workshop/performance-profiler)
- [Workshop — Mobile overview](https://www.palantir.com/docs/foundry/workshop/mobile-overview)
- [Workshop — Scenarios overview](https://www.palantir.com/docs/foundry/workshop/scenarios-overview)
