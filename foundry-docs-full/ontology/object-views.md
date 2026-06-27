<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · ONTOLOGY</b><br>
<span style="font-size:22px"><b>Object Views</b></span><br>
<span style="color:#ABB3BF">Reusable, centralized presentations of a single Ontology object's data, links, and embedded workflows.</span>
</td></tr></table>

## What it is

Object Views are the canonical "detail page" for any object in Palantir Foundry's Ontology. When a user navigates to a specific object — a building, an aircraft, a customer order — the Object View surfaces that object's property values, its relationships to other objects, and any Workshop-powered applications the team has attached to it. Foundry automatically generates a **Standard Object View** for every object type the moment it is created; teams can layer on top a fully customizable **Configured Object View** built with Workshop without removing the baseline representation.

## How it works

Object Views sit at the intersection of the Ontology layer and the Workshop application layer. The end-to-end mechanics work as follows.

1. **Object type definition drives the baseline.** When an ontology builder creates an object type and assigns properties (scalar, media, time-series, geospatial) and link types to it, Foundry automatically constructs a Standard Object View that reflects that schema. Prominent properties appear in a card layout at the top; normal properties are rendered in a table; hidden properties are suppressed. Geospatial properties render on an interactive map, time-series properties render as charts, and media references open a dedicated media viewer — all without any additional configuration.

2. **Two form factors exist for every view type.** Both Standard and Configured views come in two form factors:
   - **Full Object View** — a comprehensive, multi-tab representation showing all data, links, and embedded apps.
   - **Panel Object View** — a compact representation designed to be embedded inside another application (e.g., a Workshop module sidebar) focusing only on the most critical fields for a given workflow.

3. **Configured Object Views are Workshop modules.** A builder opens the Configured Object View editor (reachable from the Ontology Manager's Object Views tab, from Object Explorer's "More > Advanced > Edit object view" menu, or from the Panel view's ellipsis menu). Each **tab** inside the full Object View is a complete Workshop module. Adding a "managed module" tab auto-creates a new Workshop module whose permissions are kept in sync with the Object View and cannot be reused elsewhere; alternatively, builders can embed an existing Workshop module as a tab.

4. **The current object is passed as a variable.** When the Object View opens for a specific object instance, Foundry passes that object as an object-set parameter through the Workshop module interface (external ID `object`). Inside the Workshop module, builders reference this via module interface variables. This enables dynamic loading: every widget in the tab reacts to whichever object the user is currently viewing.

5. **Default full Object View layout.** Unless manually overridden, the default configured full Object View contains a **Property List widget** (showing prominent properties, or all non-hidden properties if none are prominent) and a **Links widget** (showing the object's link types with grouped linked objects). Once a builder manually edits any tab content, that tab becomes static and no longer auto-updates when the object type schema changes.

6. **Tabs are managed via a "Manage tabs" dialog.** Accessible through the gear icon in the Object Title Bar, this dialog lets builders add, rename, reorder, and delete tabs, as well as control tab visibility. Deleting a tab also permanently deletes the Workshop module it contains. Builders can preview the view in light/dark mode and across both form factors before publishing.

7. **Save and publish.** Clicking **Save and publish** commits changes to all tabs and the underlying Workshop module simultaneously. Published changes apply to every object of that type across the platform. The prior Standard Object View remains accessible at all times — a "View standard Object View" button is always available in the UI so users can fall back to the schema-driven baseline.

8. **The Object View widget in Workshop.** Within any Workshop application, builders can embed an Object View using the dedicated **Object View widget**. This widget accepts an input variable (the object set to display), allows selection of full or panel form factor, supports header visibility toggling, and exposes interface configuration so the parent module can pass its own variables down into the embedded Object View's tabs. In Adaptive mode (Panel), the widget automatically switches between single-object and object-set views depending on what the input resolves to.

## User interface

The Object View editor inherits Foundry's Blueprint-based dark theme. Below is a summary of the key areas.

<table style="border-collapse:collapse;width:100%">
<tr style="background:#1C2127">
  <th style="padding:8px 12px;color:#8ABBFF;border:1px solid #383E47;text-align:left">Area</th>
  <th style="padding:8px 12px;color:#8ABBFF;border:1px solid #383E47;text-align:left">What you see</th>
</tr>
<tr style="background:#111418">
  <td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#2D72D2"><b>Header breadcrumb</b></span></td>
  <td style="padding:8px 12px;border:1px solid #383E47;color:#ABB3BF">Ontology name → object type → form factor (Full / Panel). A dropdown lets you switch form factors. Version numbers for both the Object View and current Workshop module are shown.</td>
</tr>
<tr style="background:#1C2127">
  <td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#2D72D2"><b>Tab bar</b></span></td>
  <td style="padding:8px 12px;border:1px solid #383E47;color:#ABB3BF">Horizontal tabs across the Object Title Bar. A <b>gear icon</b> opens the Manage Tabs dialog for add / rename / reorder / delete / visibility operations.</td>
</tr>
<tr style="background:#111418">
  <td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#2D72D2"><b>Workshop canvas</b></span></td>
  <td style="padding:8px 12px;border:1px solid #383E47;color:#ABB3BF">The main panel of each tab. Full Workshop widget palette available: Property List, Links, charts, maps, tables, buttons, and more.</td>
</tr>
<tr style="background:#1C2127">
  <td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#2D72D2"><b>Property List widget</b></span></td>
  <td style="padding:8px 12px;border:1px solid #383E47;color:#ABB3BF">Default widget in every new tab. Renders prominent properties as cards at top; all other non-hidden properties in a table below.</td>
</tr>
<tr style="background:#111418">
  <td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#2D72D2"><b>Links widget</b></span></td>
  <td style="padding:8px 12px;border:1px solid #383E47;color:#ABB3BF">Displays linked objects grouped by link type. Inline property preview without navigation; side-panel preview on selection; "open in new tab" option.</td>
</tr>
<tr style="background:#1C2127">
  <td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#2D72D2"><b>Preview toolbar</b></span></td>
  <td style="padding:8px 12px;border:1px solid #383E47;color:#ABB3BF">Toggle between <span style="color:#238551"><b>● light</b></span> and <span style="color:#C87619"><b>● dark</b></span> modes; switch between Full and Panel form factor previews before publishing.</td>
</tr>
<tr style="background:#111418">
  <td style="padding:8px 12px;border:1px solid #383E47"><span style="color:#2D72D2"><b>Save and publish</b></span></td>
  <td style="padding:8px 12px;border:1px solid #383E47;color:#ABB3BF"><span style="color:#2D72D2"><b>● primary action button</b></span> — commits all tab changes and Workshop module edits simultaneously, making the view live for all objects of this type.</td>
</tr>
</table>

**Status indicators used in Object Views at runtime:**
<span style="color:#238551"><b>● active/live</b></span> · <span style="color:#C87619"><b>● stale/pending sync</b></span> · <span style="color:#CD4246"><b>● error in underlying dataset</b></span> · <span style="color:#2D72D2"><b>● primary navigation action</b></span>

## Worked example

**Scenario: Fleet maintenance portal for heavy equipment.**

1. An ontology builder creates an `Equipment` object type with properties `serial_number`, `last_service_date` (prominent), `location` (geoshape), `hours_operated` (time-series), and a link type `assigned_to → Operator`.
2. Foundry auto-generates the Standard Object View. Navigating to any `Equipment` object instantly shows: a map of its current location, a line chart of hours operated over time, and a table of all remaining properties — zero configuration required.
3. The builder opens the Configured Object View editor from Ontology Manager. They add three tabs: **Summary** (default Property List + Links widgets), **Maintenance History** (an embedded Workshop module that queries maintenance records filtered to this object via the `object` interface variable), and **Work Orders** (an existing Workshop module, re-embedded here).
4. The builder sets the Panel Object View to show only `last_service_date` and `status` so that when a dispatcher opens a side panel in the Dispatch Workshop app, they see a clean, minimal card.
5. After clicking **Save and publish**, all `Equipment` objects across the platform now display the configured view by default. Dispatchers can still click "View standard Object View" to see the full auto-generated representation at any time.

## Documentation map

- **Object Views / Overview** — top-level introduction and form-factor summary
- **Object Views / Standard Object Views** — automatic schema-driven views, property rendering rules, linked objects component
- **Object Views / Configured Object View overview** — Workshop integration, editor entry points, default layout, publishing model
- **Object Views / Full Object Views / Configure full Object Views** — header/breadcrumb UI, tab management dialog, available widgets, Save and publish flow
- **Object Views / Panel Object Views / Configure panel Object Views** — panel-specific settings, Adaptive mode, embedding in Workshop apps
- **Object Views / Configuration / Configure Workshop tabs** — adding managed vs. embedded module tabs, passing the object variable, module interface wiring
- **Object Views / Legacy Object Views / Layout** — older layout/widget system (pre-Workshop tabs)
- **Object Views / Legacy Object Views / Visualization** — legacy visualization widgets
- **Workshop / Core display widgets / Object View** — Object View widget reference: form factor options, header control, empty-state config, Adaptive panel mode, interface variable mapping

## Official documentation

- [Object Views — Overview](https://www.palantir.com/docs/foundry/object-views/overview)
- [Object Views — Configured Object View overview](https://www.palantir.com/docs/foundry/object-views/config-overview)
- [Object Views — Standard Object Views](https://www.palantir.com/docs/foundry/object-views/standard-object-views)
- [Object Views — Configure full Object Views](https://www.palantir.com/docs/foundry/object-views/config-object-views)
- [Object Views — Configure panel Object Views](https://www.palantir.com/docs/foundry/object-views/config-panel-views)
- [Object Views — Configure Workshop tabs](https://www.palantir.com/docs/foundry/object-views/config-workshop-tabs/index.html)
- [Workshop — Object View widget](https://www.palantir.com/docs/foundry/workshop/widgets-object-view)
- [Ontology — Overview](https://www.palantir.com/docs/foundry/ontology/overview)
- [Ontology — Core concepts](https://www.palantir.com/docs/foundry/ontology/core-concepts)
