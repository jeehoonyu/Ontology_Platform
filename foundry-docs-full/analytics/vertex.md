<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · ANALYTICS</b><br>
<span style="font-size:22px"><b>Vertex</b></span><br>
<span style="color:#ABB3BF">An interactive graph application for exploring the relationships between ontology objects — expanding, styling, and reasoning over a living node-link diagram of your data.</span>
</td></tr></table>

## What it is

Vertex is Foundry's **graph exploration** application. You start from one or more ontology objects, then **expand** outward along link types to reveal connected objects, building up a node-link graph you can **filter**, **style**, **lay out**, save as a reusable **template**, animate over a **timeline**, and probe with **what-if scenarios**. It turns the ontology's links into a visual investigative surface for analysts.

## How it works

1. **Seed.** A graph begins with seed objects (chosen from search, an object set, or another app). Each object becomes a node carrying its properties.
2. **Search Around (expand).** From selected nodes you traverse a chosen **link type** in a direction (outgoing / incoming / both) to a bounded depth. New objects and links are merged into the graph; revisited nodes are de-duplicated.
3. **Display options.** Nodes and edges are styled by data — fill color by object type or property, edge width by a numeric property, badges, and extended labels. A **layout** algorithm arranges them: *Auto* (force-directed), *Circular*, *Hierarchy*, *Grid*, *Radial*, *Cluster* (group by a property/type), or *Cartesian* (position by x/y properties).
4. **Filter.** Histogram/range/category filters fade or hide nodes outside the selected criteria, without removing them from the graph.
5. **Templates.** A graph can be saved as a **template** with parameter slots — object parameters (which objects to seed) and scalar parameters (depths, link types) — so the same multi-step exploration can be re-run on new inputs.
6. **Events & timeline.** Event object types are associated with nodes (start/end time fields, a visual intent such as *warning*/*danger*). The **timeline** plays the graph over time and a time-window filter fades nodes whose events fall outside the window.
7. **Scenarios.** A scenario clones the current graph, applies parameter overrides, and shows the resulting state next to the baseline for comparison.
8. **Link merging.** Many intermediate objects (e.g. transactions) between two endpoints can be **merged** into a single aggregated edge with a count/label.
9. **Control Panel settings.** Administrators set tenant defaults — default time selection, data-loading policy, model configuration.

## User interface

A central graph canvas with a left **object/search panel**, a right **display-options / styling panel**, and a bottom **timeline** strip.

<table>
<tr style="background:#1C2127;color:#fff"><th align="left" style="border:1px solid #383E47;padding:6px 10px">Surface</th><th align="left" style="border:1px solid #383E47;padding:6px 10px">Purpose</th></tr>
<tr><td style="border:1px solid #383E47;padding:6px 10px"><span style="color:#2D72D2">Canvas</span></td><td style="border:1px solid #383E47;padding:6px 10px">Node-link diagram; select, expand, drag, lasso</td></tr>
<tr><td style="border:1px solid #383E47;padding:6px 10px"><span style="color:#2D72D2">Search Around</span></td><td style="border:1px solid #383E47;padding:6px 10px">Pick link type + direction + depth to expand selection</td></tr>
<tr><td style="border:1px solid #383E47;padding:6px 10px"><span style="color:#2D72D2">Display options</span></td><td style="border:1px solid #383E47;padding:6px 10px">Color/size/badges/labels, layout algorithm</td></tr>
<tr><td style="border:1px solid #383E47;padding:6px 10px"><span style="color:#2D72D2">Timeline</span></td><td style="border:1px solid #383E47;padding:6px 10px">Scrub/playback events, time-window filter</td></tr>
</table>

Node states: <span style="color:#238551"><b>● in scope</b></span> · <span style="color:#8F99A8"><b>● faded (filtered out)</b></span> · <span style="color:#C87619"><b>● event: warning</b></span> · <span style="color:#CD4246"><b>● event: danger</b></span>.

## Worked example

Seed three **Flight** objects, Search Around the `operates_route` link (outgoing, depth 2) to reveal the **Airport** network, color nodes by object type, switch to a **Circular** layout, then filter to departures between 08:00–12:00 — non-matching flights fade. Save the steps as a template parameterized on a starting flight, then attach a `FlightDelay` event type and scrub the timeline to watch delays propagate.

## How it connects to the rest of Foundry

- **Ontology** — every node/edge is an ontology object/link; expansion is the ontology's Search Around.
- **Workshop** — a Vertex graph can be embedded as a widget in an application.
- **Time series / events** — event object types and time-series properties drive the timeline.

## In this platform (local equivalent)

`vertex_ops.py` — `/vertex/graphs` (seed), `/vertex/graphs/{id}/explore` (Search Around over `LinkInstance`), `/layout` (deterministic auto/grid/circular/radial/hierarchy/cluster positioning), `/filter`, `/style`, `/vertex/templates` + `/templates/{id}/execute`, `/graphs/{id}/events` + `/timeline` + `/timeline/filter`, `/graphs/{id}/scenarios` (deterministic what-if), `/vertex/control-panel/settings`. Verified by `oms/test_vertex_ops.py` (**75 assertions**). Scenario execution is a clearly-labeled deterministic simulation, not a model invoke.

## Official documentation
- [Vertex: Overview](https://www.palantir.com/docs/foundry/vertex/overview)
- [Explore graphs](https://www.palantir.com/docs/foundry/vertex/graphs-explore)
- [Explore object relationships](https://www.palantir.com/docs/foundry/vertex/explore-object-relationships)
- [Graph templates](https://www.palantir.com/docs/foundry/vertex/graphs-template)
- [Display options](https://www.palantir.com/docs/foundry/vertex/graphs-display-options)
- [Configure events](https://www.palantir.com/docs/foundry/vertex/configure-events) · [Timeline](https://www.palantir.com/docs/foundry/vertex/timeline)
- [Scenarios](https://www.palantir.com/docs/foundry/vertex/scenarios-getting-started) · [Link merging](https://www.palantir.com/docs/foundry/vertex/link-merging)
- [Control Panel settings](https://www.palantir.com/docs/foundry/vertex/vertex-settings-control-panel)
