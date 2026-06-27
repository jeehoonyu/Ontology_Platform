# Map (Geospatial / GIS) & Vertex

> Map is Foundry's geospatial and temporal analysis application for visualizing, searching, and acting on location-based Ontology data; Vertex is the companion graph application for exploring object relationships as a network.

## What it is

Map brings GIS capabilities to the Ontology. It renders objects with geospatial properties — points, paths, polygons — on an interactive map, supports searching by geometry, plays back movement over time, and lets you run **Actions** directly on the map. It uses Web Mercator projection (EPSG:3857) and expects WGS 84 coordinates (EPSG:4326). **Vertex** is the related application for exploring objects and their links as a node-edge graph, useful for network/relationship analysis.

## When to use it

- Your objects have locations and you need to see/analyze them spatially.
- You need geometry-based search (bounding box, polygon intersection).
- You're analyzing movement/tracks over time or building geospatial apps.
- (Vertex) You need to explore entity relationships as an interactive network graph.

**When NOT to use it / alternatives:** For non-spatial object exploration use **Object Explorer**; for tabular analysis use **Contour**; for full operational apps use **Workshop** (which can embed maps).

## Key concepts & terminology

- **Layer** — A set of objects/data rendered on the map (points, paths, polygons, imagery).
- **Geopoint / Geoshape** — Ontology property base types for coordinates and geometries.
- **Geometry search** — Querying by bounding box or polygon intersection.
- **Temporal playback** — Animating events/tracks over time.
- **Map template** — A reusable configuration for building geospatial apps.
- **Geo action** — An Ontology Action triggered from a drawn shape/selection on the map.
- **Vertex** — Graph app for exploring object-link networks.

## Core capabilities / features

- **Geospatial visualization** — Render points, paths, polygons, vector data, and satellite imagery.
- **Geometry-based search** — Bounding-box and polygon-intersection queries over objects.
- **Temporal analysis** — Visualize movement paths and time-stamped events over time.
- **Interactive geo actions** — Draw shapes and execute Ontology Actions on the map.
- **Layered analysis** — Combine multiple object/data layers.
- **App building** — Create geospatial solutions from map templates.
- **Vertex graph analysis** — Explore object relationships, with media layers and annotations.

## How it works / typical workflow

1. **Open Map** and add a **layer** of geospatial objects.
2. **Search by geometry** — draw a box/polygon to select objects within it.
3. **Style layers** by property; add imagery or vector backgrounds.
4. **Play back over time** for moving objects/events.
5. **Run geo actions** on selections (e.g., assign a region, dispatch a unit).
6. Save as a **map template** or embed in **Workshop**.

## Example

A logistics team plots `Vehicle` objects (geopoint) on Map, draws a polygon around a depot region to select vehicles inside it, plays back the last hour of movement tracks, and triggers a "Reroute" **Action** on the selected vehicles — all from the map.

## How it connects to the rest of Foundry

- **Ontology** — Map renders objects with Geopoint/Geoshape properties; Actions provide writeback.
- **Object Explorer** — Non-spatial exploration of the same objects.
- **Workshop** — Maps embed into operational applications.
- **Pipeline Builder / Transforms** — Prepare geospatial data (coordinates, geometries).
- **Vertex** — Network/graph view of object relationships.

## Tips & gotchas for learners

- **Coordinates must be WGS 84 (EPSG:4326)** — Map projects to Web Mercator (EPSG:3857).
- **Model geometry as Geopoint/Geoshape** properties so objects are mappable.
- **Geometry search** (box/polygon) is the spatial equivalent of filtering.
- **Geo actions** make the map operational, not just visual.
- **Vertex is for relationships**, Map is for locations — different lenses on the Ontology.

## Official documentation

- [Map: Overview](https://www.palantir.com/docs/foundry/map/overview)
- [Vertex: Overview](https://www.palantir.com/docs/foundry/vertex/overview)
- [Ontology: Overview](https://www.palantir.com/docs/foundry/ontology/overview)
