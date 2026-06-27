# Quiver

> Quiver is Foundry's multimodal analysis application for object-driven and time-series analysis, point-and-click machine learning, and building interactive dashboards.

## What it is

Where Contour is tabular-first, Quiver is **object- and time-series-first**. It's built to analyze Ontology objects and their associated time series, run point-and-click ML, and assemble the results into dashboards. Analysts use it to investigate entities (objects), study sensor/metric time series over time, and present findings — all without code.

## When to use it

- Analyzing Ontology **objects** and their relationships interactively.
- **Time-series analysis** — sensor data, metrics, signals over time.
- Quick, point-and-click **machine learning** on object/time-series data.
- Building **dashboards** that combine these analyses.

**When NOT to use it / alternatives:** For purely tabular exploration use **Contour**; for full operational apps with writeback use **Workshop**; for code-driven ML use **Modeling**/**Code Workbook**.

## Key concepts & terminology

- **Canvas** — The Quiver working surface where analyses and visualizations live.
- **Object-driven analysis** — Starting from an object set and exploring its properties/links.
- **Time series** — Sequences of timestamped values attached to objects.
- **Point-and-click ML** — Built-in modeling without code (e.g., forecasting/classification).
- **Dashboard** — A shareable arrangement of charts and analyses.
- **Layers / panels** — Components combined on the canvas.

## Core capabilities / features

- **Object-driven analysis** — Explore object sets, properties, and relationships visually.
- **Time-series analytics** — Plot, transform, and compare time series; windowing and smoothing.
- **Point-and-click ML** — Build predictive models interactively on your data.
- **Multimodal charting** — Combine tabular, object, and time-series visuals.
- **Dashboards** — Compose and share interactive dashboards.
- **Ontology integration** — Works natively with object types and their data.

## How it works / typical workflow

1. **Open Quiver** and bring in an object set or time-series data.
2. **Explore** — chart properties, traverse links, or plot time series.
3. **Transform** time series (resample, smooth, compute derived signals).
4. Optionally run **point-and-click ML** (e.g., forecast a metric).
5. **Assemble a dashboard** of the key charts/analyses.
6. **Share** the dashboard with stakeholders.

## Example

Investigating equipment health: load the `Machine` object set, plot each machine's vibration **time series**, smooth and detect anomalies, run a point-and-click forecast of failure risk, and build a dashboard ranking machines by risk for the maintenance team.

## How it connects to the rest of Foundry

- **Ontology** — Quiver analyzes object types and their time series natively.
- **Time series** — Consumes time-series properties on objects.
- **Workshop** — Dashboards/insights can inform or embed into operational apps.
- **Modeling** — For production ML, formalize models via Modeling Objectives.
- **Contour** — Complementary tabular analysis.

## Tips & gotchas for learners

- **Quiver is object/time-series-first** — reach for it when entities and signals matter, not just rows.
- **Point-and-click ML is for exploration** — productionize serious models in Modeling.
- **Mind time-series resolution** — resampling choices change conclusions.
- **Dashboards are shareable** but governed by Ontology permissions.

## Official documentation

- [Quiver: Overview](https://www.palantir.com/docs/foundry/quiver/overview)
- [Analytics: Overview](https://www.palantir.com/docs/foundry/analytics/overview)
