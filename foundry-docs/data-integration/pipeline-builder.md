# Pipeline Builder

> Pipeline Builder is Foundry's visual, no-code/low-code application for building production batch and streaming data pipelines without writing transform code by hand.

## What it is

Pipeline Builder lets you construct data pipelines by dragging and connecting **transform nodes** on a canvas instead of authoring code in a repository. Under the hood it compiles your visual graph into the same Spark-based transforms that Code Repositories produce, so the pipelines are fully production-grade — they have schemas, are versioned, run on schedules, and appear in Data Lineage. It is the recommended starting point for most data integration work because it removes the need to manage build infrastructure, language environments, or dependency code.

## When to use it

- You want to clean, join, reshape, or enrich datasets without writing Python/Java/SQL.
- You are building a pipeline that feeds the **Ontology** (it can write directly to object types).
- You need both **batch** and **streaming** pipelines from one tool.
- Citizen engineers / analysts need to own pipelines without learning Spark.

**When NOT to use it / alternatives:** Highly custom logic, reusable libraries, unit-tested code, or unusual dependencies are better in **Code Repositories** using the Transforms API. You can mix both — Pipeline Builder for the bulk, repositories for specialized steps.

## Key concepts & terminology

- **Pipeline** — The end-to-end graph from input datasets to output datasets/objects.
- **Node / transform** — A single operation (filter, join, aggregate, cast, formula, etc.).
- **Board / canvas** — The visual surface where nodes are connected.
- **Batch pipeline** — Processes bounded datasets on a schedule.
- **Streaming pipeline** — Continuously processes records from a **stream** with low latency.
- **Output** — A target dataset, stream, or Ontology object type the pipeline writes to.
- **Preview** — Sampled, live results shown at each node as you build.
- **Deploy / publish** — Promoting the pipeline so it builds on a schedule in production.

## Core capabilities / features

- **Visual transform library** — Dozens of built-in transforms: filter, join, union, group/aggregate, pivot/unpivot, window functions, string/date/math formulas, deduplicate, and more.
- **Live preview** — See sampled output at every node, making iterative building fast and safe.
- **Batch and streaming in one tool** — Switch the pipeline mode; streaming pipelines handle real-time topics.
- **Write to the Ontology** — Output object types directly, including create/modify semantics, without a separate sync step.
- **Expression/formula language** — A spreadsheet-like expression editor for derived columns.
- **Schema propagation & validation** — Types flow through the graph and errors surface inline before you deploy.
- **Use of Functions and ML models** — Apply Functions or model inference as nodes within the pipeline.
- **Change-only / incremental processing** — Process only new data where supported, reducing compute.
- **Version control & branching** — Pipelines have proposals, branches, and history like other Foundry resources.

## How it works / typical workflow

1. Create a new Pipeline Builder pipeline in a project.
2. **Add inputs** — select source datasets (or a stream for streaming mode).
3. **Add transform nodes** and connect them; configure each via the side panel.
4. **Preview** sampled output at each node to confirm logic.
5. **Add outputs** — a new dataset, a stream, or an Ontology object type.
6. **Validate** the pipeline; fix any schema/type errors highlighted on the canvas.
7. **Deploy/publish**, then attach a **schedule** so it builds automatically.
8. Monitor builds via **Data Lineage** and **Data Health**.

## Example

**Scenario:** Combine `raw_orders` and `customers`, keep only completed orders, and publish an `Order` object type.

1. Inputs: `raw_orders`, `customers`.
2. **Filter** node: `status == "COMPLETED"`.
3. **Join** node: `raw_orders.customer_id = customers.id` (left join).
4. **Formula** node: add `order_total = quantity * unit_price`.
5. Output node: write to the `Order` object type (primary key `order_id`).
6. Deploy and schedule hourly.

## How it connects to the rest of Foundry

- **Datasets / Transforms** — Compiles to the same transform jobs as Code Repositories and produces standard datasets.
- **Ontology** — Can write object types directly, making it the fastest path from raw data to objects.
- **Streams** — Powers streaming syncs and real-time pipelines.
- **Schedules** — Pipelines run on schedules and triggers.
- **Data Lineage / Data Health** — Pipelines appear in the lineage graph and can carry health checks.
- **Functions & Models** — Reusable logic and ML inference can be embedded as nodes.

## Tips & gotchas for learners

- **Start in Pipeline Builder, drop to code only when needed.** Most pipelines never need a repository.
- **Preview uses a sample**, not the full dataset — validate edge cases against full builds.
- **Writing to the Ontology** from Pipeline Builder is often simpler than a separate object-storage sync.
- **Streaming and batch behave differently** (windowing, state) — design with the mode in mind.
- **Deploy is required** — an un-deployed pipeline does not build on a schedule.

## Official documentation

- [Pipeline Builder: Overview](https://www.palantir.com/docs/foundry/pipeline-builder/overview)
- [Data integration: Overview](https://www.palantir.com/docs/foundry/data-integration/overview)
- [Building pipelines: Schedules](https://www.palantir.com/docs/foundry/building-pipelines/schedules)
