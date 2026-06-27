# Object Views

> Configurable detail pages that display all relevant information about a single Ontology object—its properties, linked objects, and embedded applications—in one place.

## What it is

Object Views are reusable, object-level display pages that serve as a central hub for everything known about a specific object instance (for example, one patient, one aircraft, one purchase order). They live inside the Foundry Ontology layer and are launched whenever a user clicks on an object from Object Explorer, Workshop, or any other Foundry application.

The feature solves a real problem: without Object Views, every team would have to build their own "detail page" from scratch inside Workshop. Object Views provide a shared, governed starting point that is tied directly to an object type's schema and automatically stays in sync with it.

## When to use it

- You want a **consistent detail page** for an object type used across multiple applications or teams.
- Your object type has **many properties and links** and users need a scannable, organized layout rather than a raw property list.
- You need **role-specific views** — for example, a quick-glance Panel View for an operations dashboard alongside a comprehensive Full View for analysts.
- You want to embed **Workshop widgets** (charts, maps, timelines, action buttons) directly on an object's page without building a standalone Workshop app.
- You want an **auto-generated view** that requires zero configuration while your object type is still maturing.

**When NOT to use it / alternatives:** If you need a highly interactive multi-object workflow (e.g., bulk editing, cross-object comparisons), build a dedicated Workshop application instead. Object Views are intended for single-object or small-set contexts.

## Key concepts & terminology

- **Object type** — the schema definition for a class of real-world entities (e.g., "Aircraft"); each object type has its own Object View.
- **Object instance** — a single row/entity of an object type; each instance is what the Object View actually displays.
- **Standard Object View** — the automatically generated view that Foundry creates for every object type; requires zero configuration and always reflects the current schema.
- **Configured Object View** — a fully customizable view built on top of a Workshop module; becomes the default once created.
- **Full Object View** — a form factor that provides an in-depth, comprehensive display of all related information about one object; opens as a dedicated page.
- **Panel Object View** — a form factor designed for embedding inside other applications; compact and focused on the most critical data.
- **Object Instance Panel** — a panel view showing one object instance.
- **Object Set Panel** — a panel view showing multiple objects of the same type in aggregated/list form.
- **Workshop module** — the underlying layout editor that powers each tab of a configured Object View.
- **Prominent property** — a property flagged in the Ontology as especially important; gets enhanced rendering (charts, maps, media viewers) in both standard and configured views.
- **Tab** — a top-level navigation section within an Object View; each tab is backed by its own Workshop module.

## Core capabilities / features

**Standard Object Views (no configuration required)**
- Auto-generated the moment an object type is defined; always reflects current schema without manual maintenance.
- Displays prominent properties with type-aware formatting: time-series as interactive charts, geospatial properties on maps, media references in dedicated viewers, other types in card format above a property table.
- Hidden properties remain hidden automatically.
- Includes a **Linked Objects component**: browse linked objects grouped by link type, preview their properties inline, open subsets in new tabs, or view selections in a side panel.

**Configured Object Views (Workshop-powered)**
- Built in the same Workshop module editor used for full applications, giving full layout flexibility.
- Created via Ontology Manager (Object Views tab), Object Explorer ("More > Advanced > Edit object view"), or in-application panel edit options.
- Once created, **automatically becomes the default** for that object type; users can still toggle back to the standard view via a button.
- Auto-generated defaults include prominent properties and links, and update dynamically until a builder manually edits them—after which the builder must maintain them manually.
- **Tab management**: add, reorder, rename, and delete tabs via the gear icon in the object title bar; each tab is an independent Workshop module.
- **Layout containers**: horizontal distribution, vertical stack, tabbed containers (nested tabs), and conditional containers (show/hide content based on user-selected filters).
- **Panel-specific settings**: adjust display size via presets or manual pixel entry; toggle canvas fitting when the panel exceeds available space.
- **Object Set Panels** ship with a Charts tab (up to 5 XY charts) and a List tab (Object List widget with up to 3 properties per object).
- Supports Workshop variables, model-backed simulations (Scenarios), and Action buttons on any tab.
- Published via a **Save and publish** button; can be gated by version settings.

**Permissions**
- Without Ontology roles: requires `Object View Admin` in Control Panel + `Editor` on input datasources.
- With Ontology roles: only `Ontology Editor` role on the object type is needed.

## How it works / typical workflow

1. **Define the object type** in Ontology Manager—set properties, mark prominent ones, define links to other object types.
2. **Use the automatic Standard View** to verify the schema looks correct without any extra work.
3. **Open the configured view editor** from Ontology Manager > Object Views tab > Edit (or from Object Explorer).
4. **Add and organize tabs** using the gear icon: one tab per logical grouping (e.g., "Overview", "History", "Linked Assets").
5. **Design each tab** in the Workshop module editor—drag in widgets (property lists, charts, maps, action buttons, embedded apps), arrange them with layout containers, and bind them to object properties or functions.
6. **Configure panel views** separately (Full vs. Panel is switchable via the top ribbon): set the display size and choose between instance vs. set panel types.
7. **Save and publish** to make the configured view the live default for all users of that object type.
8. **Iterate**: when the object type schema changes, update the configured view manually (the auto-sync stops once you've manually edited the view).

## Example

Imagine a `Patient` object type in a healthcare Foundry deployment.

- **Standard View** (zero config): automatically shows a property table with Name, DOB, MRN; renders a time-series chart for vitals; shows a map if a location property exists; lists linked Procedures, Prescriptions, and Diagnoses.
- **Configured Full View** built by the data team:
  - Tab 1 "Summary" — Property List widget with prominent fields + a conditional container that reveals an alert banner when a "High Risk" flag property is `true`.
  - Tab 2 "Clinical History" — an embedded Workshop module with an XY Chart of lab values over time and an Object List of linked Diagnoses.
  - Tab 3 "Actions" — Action buttons to "Admit Patient", "Update Vitals", triggering write-back Actions defined in the Ontology.
- **Panel View** embedded in a triage dashboard — compact instance panel showing only Name, DOB, and current vitals score.

No code is required for standard or configured views; the Workshop module editor is entirely visual.

## How it connects to the rest of Foundry

- **Ontology** — Object Views are a first-class feature of the Ontology layer. They reference object types, properties, links, and Actions defined there. Changes to the object type propagate to standard views automatically.
- **Workshop** — Every configured Object View tab is a Workshop module. Any widget, variable, or function available in Workshop is also available inside an Object View tab.
- **Object Explorer** — Clicking any object in Object Explorer opens its Object View. Users can switch between standard and configured views from here.
- **Gaia / Vertex / other Foundry apps** — Panel Object Views are embedded inside these applications to surface object details in context without navigating away.
- **Functions** — Workshop modules backing Object View tabs can call Foundry Functions for computed properties or derived analytics.
- **Actions** — Action widgets placed on Object View tabs let users trigger write-back operations (create, edit, delete) directly from the object detail page.
- **Marketplace** — Configured Object Views can be packaged into Marketplace products so they can be distributed and installed across multiple Foundry environments.

## Tips & gotchas for learners

- **Auto-sync stops on first manual edit.** The auto-generated configured view keeps updating when you change the object type—but only until you make your first manual edit. After that, schema changes will NOT be reflected automatically; you must update the view yourself.
- **Standard view is always available.** Even after creating a configured view, users can toggle back to the standard view. Don't assume everyone sees your configured layout.
- **Panel vs. Full is a separate configuration.** You must configure the Full View and Panel View separately—they do not share a layout.
- **Object Set Panels are different from Instance Panels.** If you switch the panel type you may lose your existing layout configuration, so decide early.
- **Permissions differ by Ontology role setup.** If your enrollment does not use Ontology roles, you need the `Object View Admin` Control Panel permission—not just Ontology Manager access.
- **Publishing is required.** Saving without publishing means users won't see your changes. Look for the "Save and publish" button, and check whether auto-publish is turned off in version settings.
- **Each tab is an independent Workshop module.** This is powerful (full Workshop feature set per tab) but means changes to one tab do not affect others—manage them separately.
- **Prominent properties drive both views.** Marking properties as prominent in the Ontology affects the standard view rendering and the default generated configured view. Keep prominent flags tidy.

## Official documentation

- [Object Views — Overview](https://www.palantir.com/docs/foundry/object-views/overview)
- [Configured Object View overview](https://www.palantir.com/docs/foundry/object-views/config-overview)
- [Configure full Object Views](https://www.palantir.com/docs/foundry/object-views/config-object-views)
- [Configure panel Object Views](https://www.palantir.com/docs/foundry/object-views/config-panel-views)
- [Standard Object Views](https://www.palantir.com/docs/foundry/object-views/standard-object-views)
- [Configure Workshop tabs](https://www.palantir.com/docs/foundry/object-views/config-workshop-tabs/)
- [Ontology overview](https://www.palantir.com/docs/foundry/ontology/overview)
