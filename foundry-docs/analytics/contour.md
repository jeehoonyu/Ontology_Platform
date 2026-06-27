# Contour

> Contour is Foundry's point-and-click analytics application for exploring large tabular datasets, building analyses step by step, deriving new datasets, and creating charts — no code required.

## What it is

Contour lets analysts interrogate data at scale without writing Spark. You build an **analysis** as a sequence of **boards** (steps) — filter, aggregate, join, pivot, add columns — and each step shows results on a sample, while the full analysis runs distributed under the hood. Because every step is reproducible, a Contour analysis can be saved, shared, and even published back out as a derived dataset for downstream use.

## When to use it

- Ad-hoc, exploratory analysis of large tabular datasets.
- Analysts who want SQL-like power through a visual, step-based UI.
- Producing a cleaned/aggregated dataset without writing transform code.

**When NOT to use it / alternatives:** For object/time-series analysis and dashboards use **Quiver**; for code-driven data science use **Code Workbook**; for operational apps use **Workshop**.

## Key concepts & terminology

- **Analysis** — A saved Contour document: a pipeline of analytical steps.
- **Path** — A branch of analysis steps (analyses can fork into multiple paths).
- **Board** — A single step/operation (filter, aggregate, pivot, join, chart, etc.).
- **Expression** — A formula for derived columns or filters.
- **Pivot table** — Cross-tabulated aggregation board.
- **Chart board** — Visualization built from the current data state.
- **Derived dataset** — A dataset published from a Contour analysis for reuse.

## Core capabilities / features

- **Step-based analysis** — Stack boards to filter, aggregate, join, pivot, and compute.
- **Scales to large data** — Runs distributed while you interact with samples.
- **Rich boards** — Pivot tables, summaries, histograms, and many chart types.
- **Expressions** — Spreadsheet-like formulas for derived columns and filters.
- **Multiple paths** — Branch an analysis to compare alternatives.
- **Publish to dataset** — Turn an analysis into a governed derived dataset.
- **Sharing & reproducibility** — Save and share analyses; every step is recorded.

## How it works / typical workflow

1. **Create an analysis** and select a starting dataset.
2. Add a **filter board** to narrow rows.
3. Add **aggregate/pivot boards** to summarize.
4. Add **expression boards** for derived metrics.
5. Add **chart boards** to visualize.
6. **Publish** the result as a derived dataset or share the analysis.

## Example

Analyzing `clean/sales`: filter to the current year, aggregate revenue by region and month, add a pivot table region×month, and chart the trend. Publish the aggregated result as `analytics/sales_by_region` for a Workshop dashboard.

## How it connects to the rest of Foundry

- **Datasets** — Reads datasets and can publish derived datasets.
- **Ontology / Object Explorer** — Complementary; Contour is tabular-first, Object Explorer is object-first.
- **Quiver / Workshop** — Consume Contour-derived datasets for dashboards and apps.
- **AIP Assist** — Can help build Contour analyses.

## Tips & gotchas for learners

- **Think in steps** — each board transforms the prior board's output.
- **Use paths to compare** scenarios without duplicating work.
- **Publish derived datasets** to make analyses reusable downstream.
- **Samples vs full runs** — interactive previews are sampled; published outputs are full.
- **Contour is tabular** — for objects/relationships, use Object Explorer or Quiver.

## Official documentation

- [Contour: Overview](https://www.palantir.com/docs/foundry/contour/overview)
- [Analytics: Overview](https://www.palantir.com/docs/foundry/analytics/overview)
