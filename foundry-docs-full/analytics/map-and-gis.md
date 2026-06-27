<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · ANALYTICS</b><br>
<span style="font-size:22px"><b>Map (Geospatial / GIS)</b></span><br>
<span style="color:#ABB3BF">A geospatial and temporal analysis application that integrates Ontology data into interactive, layered maps.</span>
</td></tr></table>

## What it is

The **Map** application is Foundry's native GIS and geospatial analysis platform. It allows analysts to pull objects directly from the Ontology onto a live map canvas, apply richly configurable layer styles, traverse physical networks via Search Around, and explore temporal movement data — all without leaving Foundry. Maps can be embedded in Workshop dashboards or built as standalone analytical applications using reusable overlay layers.

---

## How it works

### Coordinate system and data ingestion

Foundry Map renders using the **Web Mercator Projection (EPSG:3857)** and expects input geometry in **WGS 84 degrees (EPSG:4326)**. Source data lives in Ontology object types that carry one or more geospatial properties: `geopoint` (a latitude/longitude pair), `geoshape` (polygon or polyline geometry), or time-stamped position histories that form movement tracks.

### Layer stack — the building blocks

Every map is a stack of layers rendered in order from bottom to top:

1. **Base layer** — provides the geographic backdrop. Options include a light theme, dark theme, and satellite imagery. Switched at any time from the Layers panel.
2. **Object layer** — the primary analytical layer. Each object layer is bound to one Ontology object type. Objects are fetched live from the Ontology according to the viewport bounds and any active filters.
3. **Link layer** — rendered automatically when a Search Around operation is executed. Draws relationship edges between objects as lines, inheriting styling from the connected object types.
4. **Overlay layer** — a preconfigured, reusable visualization built in the **Map Layer Editor** and stored in Foundry as a shareable resource. Any map can import an overlay layer by name; updates to the overlay propagate automatically.
5. **Annotation layer** — user-drawn shapes (polygons, circles, rectangles, lines, points) that add context without modifying underlying data.

### Displays-based rendering model

Within each object layer, rendering is driven by one or more **displays**. A display is a single visual representation of the object (e.g., an icon, a circle, a line segment, a track). Multiple displays stack on the same layer so that, for example, a vehicle can simultaneously show an icon marker at its current position and a track line of its historical path. Each display has its own:

- **Geometry source** — which property (geopoint, geoshape, or computed value) drives position/shape.
- **Styler** — the visual encoder (icon renderer, circle renderer, line segment, track breadcrumbs/heatmap).
- **Zoom range** — visibility window defined by minimum and maximum zoom level, enabling semantic zoom where icons appear at street level and clusters appear at country level.

### Value-based styling pipeline

Style attributes (color, size, opacity, stroke) are resolved at render time through a **value-based styling** pipeline:

- **Fixed** — a single constant value applied to all objects.
- **Property-based** — reads an object property; for strings a manual color map or auto-differentiation is applied; for numerics a gradient editor maps the value range to a color ramp.
- **Function-based** — a computed expression drives the style.
- **Measure-based** — time series measurements control color or opacity, enabling data to "light up" relative to the temporal cursor.

Opacity can additionally be **time-dependent**: objects fade in/out relative to their timestamp and the map's active time window.

### Temporal model

Every map maintains a **selected time** and a **time window**. The time window bounds which time-series records are loaded; the selected time is the cursor position within that window. Tracks interpolate object positions between recorded points (linear interpolation or last-known-point) with a configurable maximum time-gap threshold beyond which no interpolation is drawn. The Series panel at the bottom-right renders sparklines and event timelines synchronized to the map cursor.

### Spatial query and Search Around

Users can draw a bounding box or polygon directly on the canvas; the map executes a **spatial intersection query** against the Ontology and returns only objects whose geometry overlaps the drawn shape. **Search Around** takes selected objects as seeds and traverses Ontology relationships to hydrate linked objects, automatically adding a link layer to visualize the connections.

### Object limit and performance

A default limit of **1,000 objects** per layer applies. Overlays created in the Map Layer Editor can be optimized for scale independently of per-session object layers.

---

## User interface

### Layout overview

The Map UI follows a three-column shell:

| Zone | Contents |
|------|----------|
| <span style="color:#8ABBFF">Left panel rail</span> | Layers, Find, Histogram, Info — tabbed icon rail |
| <span style="color:#8ABBFF">Center canvas</span> | Interactive map viewport with top toolbar |
| <span style="color:#8ABBFF">Right panel rail</span> | Selection, Time Selection, Series — context-sensitive |

### Left-side panels

- <span style="color:#2D72D2"><b>Layers panel</b></span> — the primary configuration surface. Lists all layers in stack order; each layer row has a visibility toggle and an expand arrow that opens the full styling editor. The <b>+ Add to map</b> button opens the object/overlay search dialog. Base layer switcher lives here.
- <span style="color:#2D72D2"><b>Find panel</b></span> — free-text search for named places and Ontology objects; navigates the viewport to the result.
- <span style="color:#2D72D2"><b>Histogram panel</b></span> — filters displayed objects by property value or time series; sliders drive the active filter range in real time.
- <span style="color:#2D72D2"><b>Info panel</b></span> — summary statistics for the current map state.

### Top toolbar — interaction modes

<table style="background:#1C2127;border:1px solid #383E47;border-radius:6px;padding:8px;width:100%">
<tr style="color:#ABB3BF;font-size:12px">
<th style="padding:6px 10px;text-align:left">Mode</th>
<th style="padding:6px 10px;text-align:left">What it does</th>
</tr>
<tr><td style="padding:5px 10px"><span style="color:#8ABBFF"><b>Select</b></span></td><td style="padding:5px 10px;color:#ABB3BF">Bulk-select objects; invert selection; lasso within drawn shapes</td></tr>
<tr><td style="padding:5px 10px"><span style="color:#8ABBFF"><b>Search Around</b></span></td><td style="padding:5px 10px;color:#ABB3BF">Traverse Ontology relationships from selected objects; renders link layers</td></tr>
<tr><td style="padding:5px 10px"><span style="color:#8ABBFF"><b>Draw</b></span></td><td style="padding:5px 10px;color:#ABB3BF">Create polygons, circles, rectangles, lines, and points for spatial queries or annotations</td></tr>
<tr><td style="padding:5px 10px"><span style="color:#8ABBFF"><b>Capture</b></span></td><td style="padding:5px 10px;color:#ABB3BF">Screenshot the current viewport as an image</td></tr>
<tr><td style="padding:5px 10px"><span style="color:#8ABBFF"><b>Measure</b></span></td><td style="padding:5px 10px;color:#ABB3BF">Calculate physical distances between drawn points</td></tr>
<tr><td style="padding:5px 10px"><span style="color:#8ABBFF"><b>Annotate / Delete</b></span></td><td style="padding:5px 10px;color:#ABB3BF">Add freeform annotations or remove map items</td></tr>
</table>

### Right-side panels

- <span style="color:#2D72D2"><b>Selection panel</b></span> — object card(s) for whatever is clicked or lasso-selected; shows properties, links, and available actions.
- <span style="color:#2D72D2"><b>Time Selection panel</b></span> — date/time range picker and cursor scrubber; sets the map's active time window.
- <span style="color:#2D72D2"><b>Series panel</b></span> (bottom-right) — sparklines and event timelines for selected objects; synchronized to the temporal cursor.

### Styling editor (inside Layers panel)

Opening a layer's expand arrow reveals the styling editor:

- **Saved styles** — named style snapshots that can be switched without losing configuration.
- **Display list** — add/remove/reorder displays for the layer.
- Per-display controls for color (fixed / property / gradient), opacity (fixed / time-based), zoom range, stroke pattern (solid / dashed / dotted), arrow overlays, icon selection, marker shape (circle / pin / none), and label/tooltip configuration.
- **Include in legend** toggle per color mapping.

### Status indicators

<span style="color:#238551"><b>● Loaded</b></span> · <span style="color:#C87619"><b>● Loading / stale</b></span> · <span style="color:#CD4246"><b>● Error / limit exceeded</b></span> · <span style="color:#2D72D2"><b>● Active filter applied</b></span>

---

## Worked example

**Scenario:** An operations team wants to find all warehouses within 50 km of a hurricane track and see which logistics routes intersect the affected zone.

1. Open a new Map application in Foundry.
2. In the <span style="color:#2D72D2">Layers panel</span>, click **+ Add to map** and search for the `Warehouse` object type on the **Objects** tab. Click **Add all** (assuming < 1,000 warehouses).
3. A second object layer is added for `Logistics Route` (geoshape properties, rendered as lines with a fixed cyan stroke).
4. Switch to the **Draw** toolbar mode and draw a polygon approximating the hurricane corridor.
5. Click **Search for objects that intersect this shape** — the Layers panel filters the Warehouse and Route layers to show only intersecting features. A count badge shows <span style="color:#C87619"><b>● 47 warehouses</b></span> and <span style="color:#CD4246"><b>● 12 routes</b></span> inside the zone.
6. Select all warehouses; click **Search Around** to traverse the `supplies` relationship — a link layer appears connecting warehouses to their supplier objects.
7. Open the **Time Selection panel**, set the window to the 72-hour storm forecast, and scrub the cursor — warehouses whose `last_resupply` timestamp falls outside the window fade via time-based opacity, instantly revealing at-risk facilities.
8. Open the **Histogram panel** and filter by `inventory_days_remaining < 3` to highlight critical shortages with a red gradient style on the circle renderer.
9. Click **Capture** to screenshot the final map and share with stakeholders.

---

## Documentation map

Sub-pages that exist beneath the Map tool in the Palantir Foundry docs:

- **Overview** — top-level capabilities summary
- **Core concepts** — layer types, time selection model, styling overview
- **Interact with maps**
  - Map interface overview — UI panels and toolbar reference
  - Add data to a map — adding object types and overlays
  - Spatial queries and Search Around
- **Visualize Ontology data**
  - Overview — displays-based architecture, rendering modes
  - Styling — value-based styling pipeline, color/opacity/stroke configuration
  - Saved styles
- **Geospatial and geotemporal** (related section)
  - Types of geospatial and geotemporal data
  - Use geospatial data in the Ontology
- **Workshop widget: Map** — embedding maps in Workshop dashboards
- **Contour: Map board** — map-style board in the Contour analytics tool
- **Map Layer Editor** — building reusable overlay layers

---

## Official documentation

- [Map · Overview](https://www.palantir.com/docs/foundry/map/overview)
- [Map · Core concepts](https://www.palantir.com/docs/foundry/map/core-concepts)
- [Map · Map interface overview](https://www.palantir.com/docs/foundry/map/map-overview)
- [Map · Add data to a map](https://www.palantir.com/docs/foundry/map/add-to-map)
- [Map · Visualize Ontology data · Overview](https://www.palantir.com/docs/foundry/map/visualize-objects)
- [Map · Styling](https://www.palantir.com/docs/foundry/map/styling)
- [Geospatial and geotemporal · Types of geospatial data](https://www.palantir.com/docs/foundry/geospatial/types-of-geospatial-and-geotemporal-data)
- [Geospatial and geotemporal · Use geospatial data in the Ontology](https://www.palantir.com/docs/foundry/geospatial/ontology)
