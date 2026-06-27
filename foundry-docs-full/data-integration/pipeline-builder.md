<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · DATA INTEGRATION</b><br>
<span style="font-size:22px"><b>Pipeline Builder</b></span><br>
<span style="color:#ABB3BF">A visual, no-code/low-code application for designing, executing, and managing data transformation pipelines in Palantir Foundry.</span>
</td></tr></table>

## What it is

Pipeline Builder is Foundry's primary data integration application. It provides a canvas-based, directed acyclic graph (DAG) editor where users connect input datasets, transformation nodes, and outputs into end-to-end data pipelines — without writing code unless they choose to. It supports both batch and streaming pipelines and is designed to replace manual ETL scripting for the majority of data engineering use cases on Foundry.

## How it works

Pipeline Builder models a pipeline as a **DAG of nodes**. Each node has a type (input, transform, or output), a configuration, and zero or more directed edges to downstream nodes. Foundry's compute engine evaluates the DAG when a build is triggered, reading from upstream nodes and writing to downstream ones.

**End-to-end mechanics:**

1. **Add input nodes.** You point the pipeline at existing Foundry datasets, streaming datasets, or media sets. Optionally you configure a *dataset sync* (pulling data from an external source) or add generated/sample data for development purposes. Each input node registers a read-dependency so the scheduler can watch for upstream changes.

2. **Insert transform nodes.** Each transform node sits between inputs and outputs on the canvas. A transform takes one or more full tables as input and returns a full table as output. Transforms are categorized as:
   - **Single-table operations** — Filter rows, Select/Rename/Drop columns, Sort, Apply expression (evaluates a function across one column and writes the result to a new column), Apply multiple expressions (project across many columns at once), Aggregate, Aggregate over window.
   - **Multi-table operations** — Join data (inner/left/right/full outer/cross), Union data.
   - **Specialized transforms** — Create geospatial transforms, Transform media (images/video/audio), Trained model node (invoke a Foundry-hosted ML model), Use LLM node (invoke a large language model via AIP), Pattern mining, K-means clustering, Create unique ID, Streaming pipeline join.
   - **Expression system** — Inside any transform that accepts expressions, a library of 300+ typed functions covers strings, numerics, dates, geospatial coordinates, arrays, and conditional logic. Expressions operate at the cell/column level; transforms operate at the table level.

3. **Configure each node.** Clicking a node opens its configuration panel on the right. You define column mappings, join keys, filter predicates, expression formulas, or model references through a form-based UI. Expressions are typed into an inline formula editor with autocomplete and live type-checking.

4. **Preview the pipeline.** Before building, you can trigger a *pipeline preview* which runs the DAG on a configurable sample of rows (input sampling strategy). The preview materializes the output schema and a row sample so you can validate logic interactively without committing a full build.

5. **Add output nodes.** You attach one or more output nodes to any transform or input node. Supported output types include: Dataset (tabular), Media set, Virtual table (query-time view), Ontology output (writes properties back to Foundry's ontology layer), and Geotemporal series sync. Each output node is itself a named Foundry resource with a versioned history.

6. **Deliver (build) the pipeline.** Clicking **Deliver** triggers a full compute build of all output nodes. Foundry's scheduler resolves the dependency order of nodes in the DAG, reads from the registered inputs, runs each transform in sequence, and writes to the registered outputs. Incremental/snapshot strategies are handled per output configuration.

7. **Schedule and monitor.** Schedules are attached to a pipeline (or individual output datasets) and can fire on two triggers: *when a parent resource updates* (event-driven) or *at a specific time* (cron-style). AIP-assisted scheduling can recommend a schedule based on observed data update patterns. Build status, data health checks, and data expectations (unit-test-like assertions on output data) are visible in the monitoring panels.

8. **Branch and collaborate.** Pipeline Builder supports Foundry *branches* — each branch is an isolated version of the pipeline definition. Teams use the *change proposal* workflow (analogous to a pull request) with code review and approval gates before merging changes to the protected main branch.

## User interface

<table style="background:#1C2127;border:1px solid #383E47;border-radius:6px;padding:12px;width:100%;border-collapse:collapse">
<tr style="border-bottom:1px solid #383E47">
<td style="padding:8px 12px;color:#8ABBFF;font-weight:bold">Zone</td>
<td style="padding:8px 12px;color:#8ABBFF;font-weight:bold">What you see</td>
</tr>
<tr style="border-bottom:1px solid #383E47">
<td style="padding:8px 12px;color:#fff"><span style="color:#2D72D2"><b>Top toolbar</b></span></td>
<td style="padding:8px 12px;color:#ABB3BF">Branch selector, Deliver button, Preview button, Build settings, Find &amp; Replace, Code export</td>
</tr>
<tr style="border-bottom:1px solid #383E47">
<td style="padding:8px 12px;color:#fff"><span style="color:#2D72D2"><b>Left sidebar</b></span></td>
<td style="padding:8px 12px;color:#ABB3BF">Node library (Inputs / Transforms / Outputs), Folders &amp; color groups, Parameters panel, Custom functions</td>
</tr>
<tr style="border-bottom:1px solid #383E47">
<td style="padding:8px 12px;color:#fff"><span style="color:#2D72D2"><b>Canvas (graph)</b></span></td>
<td style="padding:8px 12px;color:#ABB3BF">DAG of nodes connected by directed edges; <b>Pan mode</b> (click-drag to navigate) and <b>Drag-select mode</b> (marquee-select multiple nodes); right-click context menu; node color groups; checkpoint markers</td>
</tr>
<tr style="border-bottom:1px solid #383E47">
<td style="padding:8px 12px;color:#fff"><span style="color:#2D72D2"><b>Right config panel</b></span></td>
<td style="padding:8px 12px;color:#ABB3BF">Context-sensitive: shows transform configuration form, expression editor with autocomplete, join/filter builder, schema preview, Schedules tab, Data expectations</td>
</tr>
<tr>
<td style="padding:8px 12px;color:#fff"><span style="color:#2D72D2"><b>Bottom preview pane</b></span></td>
<td style="padding:8px 12px;color:#ABB3BF">Sampled row output table, column types, row count; schema diff vs. previous build</td>
</tr>
</table>

**Node states on the canvas:**

<span style="color:#238551"><b>● built/up-to-date</b></span> · <span style="color:#C87619"><b>● stale/pending</b></span> · <span style="color:#CD4246"><b>● failed</b></span> · <span style="color:#2D72D2"><b>● selected / active</b></span> · <span style="color:#ABB3BF"><b>● never built</b></span>

**Key interactions:**

- **Adding a node:** drag from the left sidebar onto the canvas, or right-click the canvas and choose a node type.
- **Connecting nodes:** hover the edge of a source node until a connection handle appears, then drag to the target node.
- **Organizing complex pipelines:** group nodes into named **folders** (shown as collapsible containers on the canvas) and assign **color groups** for visual segmentation. Use **Show/Hide nodes** to narrow focus.
- **Checkpoints:** mark a node as a checkpoint to force Foundry to materialize and cache that intermediate dataset, breaking long dependency chains and enabling downstream pipelines to branch off mid-flow.
- **Job groups:** bundle related nodes so they share a single build schedule entry and appear as a logical unit in monitoring.
- **Parameterization:** define pipeline-level parameters (typed values or column references) that can be passed at build time, enabling reusable pipeline templates.

## Worked example

**Scenario:** Cleaning and enriching a raw customer events table for downstream analytics.

1. **Input** — Add the `raw_customer_events` dataset (batch mode). Set input sampling to 10,000 rows for preview.
2. **Filter** — Insert a *Filter* transform. Expression: `event_type IS NOT NULL AND timestamp > '2024-01-01'`. Preview confirms ~80 % of rows pass.
3. **Apply expression** — Add an *Apply expression* node. Formula: `UPPER(TRIM(customer_id))` → writes to a new column `customer_id_clean`.
4. **Join** — Add a *Join data* node joining `customer_id_clean` (left) against the `dim_customers` reference dataset (right) on `customer_id`. Join type: left outer, to preserve events with no match.
5. **Aggregate** — Add an *Aggregate* node: group by `customer_id_clean`, compute `COUNT(*) AS event_count` and `MAX(timestamp) AS last_seen`.
6. **Output** — Attach a *Dataset output* node, name it `customer_event_summary`. Click **Deliver**. Foundry builds the DAG in dependency order and writes the output dataset to the catalog.
7. **Schedule** — In the Schedules tab, configure *trigger when parent updates* on `raw_customer_events` so the pipeline re-runs automatically on each new data drop.

## Documentation map

The following sub-sections exist under Pipeline Builder in the Palantir Foundry docs:

- **Overview** — introduction and workflow summary
- **Core concepts** — building blocks: inputs, transforms, outputs, management
- **Navigation** — canvas modes, toolbar, sidebar, keyboard shortcuts
- **Tips and tricks** — productivity patterns
- **Input datasets** — add sources, configure syncs, generated data, batch vs. streaming mode
- **Transforms**
  - Transforms overview (expressions vs. transforms distinction)
  - Transform data (filter, select, rename, drop, sort, aggregate, apply expression)
  - Join data
  - Union data
  - Aggregate over window
  - Create geospatial transforms
  - Transform media
  - Trained model node
  - Use LLM node
  - Pattern mining / K-means / Split transforms
  - Create unique ID
  - Streaming pipeline join
- **Pipeline outputs**
  - Deliver pipeline
  - Dataset outputs
  - Media set outputs
  - Virtual table outputs
  - Ontology outputs
  - Geotemporal series sync outputs
- **Pipeline management**
  - Overview
  - Input sampling strategies
  - Parameters
  - Build settings
  - Custom functions
  - Show and hide nodes / Folders / Color groups
  - Checkpoints / Job groups
  - Find and replace
  - Code export
  - Charts and text nodes
- **Branching** — create branch, change proposals, approval workflows, branch protection, fallback branch
- **Schedules** — overview, create a schedule, AIP-assisted scheduling
- **Data quality** — data health checks, data expectations, unit tests
- **AIP features** — LLM-powered pipeline authoring assistance
- **Functions index** — 300+ expression functions reference
- **Building pipelines (cross-tool)** — Create a streaming pipeline with Pipeline Builder

## Official documentation

- [Pipeline Builder — Overview](https://www.palantir.com/docs/foundry/pipeline-builder/overview)
- [Pipeline Builder — Core concepts](https://www.palantir.com/docs/foundry/pipeline-builder/core-concepts)
- [Pipeline Builder — Transforms overview](https://www.palantir.com/docs/foundry/pipeline-builder/transforms-overview)
- [Pipeline Builder — Transform data](https://www.palantir.com/docs/foundry/pipeline-builder/transforms-transform-data)
- [Pipeline Builder — Navigation](https://www.palantir.com/docs/foundry/pipeline-builder/navigation)
- [Pipeline Builder — Use LLM node](https://www.palantir.com/docs/foundry/pipeline-builder/pipeline-builder-llm)
- [Pipeline Builder — Trained model node](https://www.palantir.com/docs/foundry/pipeline-builder/transforms-trained-model)
- [Pipeline Builder — Schedules overview](https://www.palantir.com/docs/foundry/pipeline-builder/schedules-overview)
- [Pipeline Builder — Deliver pipeline](https://www.palantir.com/docs/foundry/pipeline-builder/outputs-deliver-pipeline)
- [Building pipelines — Create a streaming pipeline with Pipeline Builder](https://www.palantir.com/docs/foundry/building-pipelines/create-stream-pipeline-pb)
