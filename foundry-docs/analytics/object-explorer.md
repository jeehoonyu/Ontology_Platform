# Object Explorer

> Object Explorer is Foundry's application for searching, filtering, and analyzing Ontology objects and their relationships — the fastest way to explore the semantic layer without building an app.

## What it is

Object Explorer is the built-in window into your Ontology. Point it at an object type and you can search, apply filters, view distributions with histograms, traverse links to related objects, and visualize networks — all interactively. It's where analysts and builders explore what objects exist and how they connect, before (or instead of) building a Workshop app.

## When to use it

- Quickly find and filter objects of a given type.
- Explore relationships by traversing links between objects.
- Understand property distributions and data quality in the Ontology.
- Build and save object sets for reuse in other tools.

**When NOT to use it / alternatives:** For tabular dataset analysis use **Contour**; for time series/ML use **Quiver**; for a tailored operational UI use **Workshop**.

## Key concepts & terminology

- **Object set** — A filtered collection of objects you're exploring.
- **Filter** — A condition narrowing the object set (by property, link, etc.).
- **Histogram / distribution** — Visual breakdown of a property's values.
- **Link traversal** — Navigating from objects to related objects.
- **Network / graph view** — Visualization of objects and their links.
- **Saved search / object set** — A reusable, named selection.

## Core capabilities / features

- **Search & filter** — Find objects by property values and link conditions.
- **Histograms & aggregations** — See distributions and summaries of properties.
- **Link traversal** — Hop across relationships to related object types.
- **Network visualization** — Explore connected objects as a graph.
- **Saved object sets** — Persist selections to reuse in Workshop, Functions, etc.
- **Drill-down to object views** — Open an individual object's detail page.
- **Governed** — Respects Ontology permissions and markings.

## How it works / typical workflow

1. **Open Object Explorer** and pick an **object type**.
2. **Apply filters** to narrow the object set.
3. **Inspect distributions** via histograms.
4. **Traverse links** to related objects (e.g., from `Order` to `Customer`).
5. **Visualize the network** if relationships matter.
6. **Save the object set** for use elsewhere, or open a single object's view.

## Example

Exploring open orders: select `Order`, filter `status = OPEN` and `total > 1000`, view the distribution by region, then traverse the link to `Customer` to see which customers they belong to. Save the resulting object set as "High-value open orders" for a Workshop module.

## How it connects to the rest of Foundry

- **Ontology** — Object Explorer is the native explorer for object types and links.
- **Workshop** — Saved object sets seed operational apps.
- **Functions / Actions** — Explored objects are acted on via Functions and Actions.
- **Quiver** — For deeper time-series/ML analysis of the same objects.
- **Map** — Geospatial objects can be explored on the map.

## Tips & gotchas for learners

- **Object-first, not row-first** — Object Explorer reasons about entities and links, unlike Contour.
- **Save object sets** to reuse selections across tools.
- **Link traversal** is the superpower — explore relationships, not just single types.
- **Permissions apply** — you only see objects/properties you're authorized for.

## Official documentation

- [Object Explorer: Overview](https://www.palantir.com/docs/foundry/object-explorer/overview)
- [Ontology: Overview](https://www.palantir.com/docs/foundry/ontology/overview)
- [Analytics: Overview](https://www.palantir.com/docs/foundry/analytics/overview)
