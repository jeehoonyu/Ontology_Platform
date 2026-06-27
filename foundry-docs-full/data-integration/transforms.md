<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · DATA INTEGRATION</b><br>
<span style="font-size:22px"><b>Transforms (Python / Java / SQL)</b></span><br>
<span style="color:#ABB3BF">Code-based data pipeline units that read input datasets, apply logic in Python, Java, or SQL, and write versioned output datasets — all executed on Apache Spark.</span>
</td></tr></table>

## What it is

Transforms are the core computational building blocks of Foundry data pipelines. Each transform is a versioned code artifact that declares one or more input datasets, applies user-authored logic (in Python, Java, or SQL), and emits one or more output datasets. Transforms are authored inside **Code Repositories**, version-controlled via Git, and executed by Foundry's compute infrastructure on Apache Spark, making them capable of processing datasets from gigabytes to petabytes. SQL is recommended for straightforward filtering, aggregating, and joining; Python is preferred for complex logic, ML preparation, or single-node workflows; Java provides low-level API access and is well-suited for stateful or streaming patterns.

---

## How it works

### 1. Authoring in Code Repositories

Transforms live in a **Code Repository** — a Git-backed project in Foundry. Each repository targets a single language (Python, Java, or SQL). For Python and Java, the project follows a standard layout: source files under `src/`, a build configuration (`gradle.build` for Java, `conda_recipe/` or `requirements.txt` for Python), and optional test files.

### 2. Declaring inputs and outputs

- **Python**: Transforms are decorated functions. The `@transform` decorator (or `@transform_df` for DataFrame-centric work) declares `Input(dataset_rid_or_alias)` and `Output(dataset_rid_or_alias)` parameters. At runtime Foundry injects `TransformInput` / `TransformOutput` objects that expose a Spark DataFrame, a Polars DataFrame, a pandas DataFrame, or raw file handles depending on the API chosen.
- **Java**: Transforms are classes annotated with `@Transform`. Fields annotated `@Input` and `@Output` wire datasets into the transform. A high-level API exposes `Dataset<Row>` (Spark DataFrames); a low-level API gives direct access to dataset transactions and files.
- **SQL**: Each `.sql` file is a transform. Input datasets are referenced by a user-defined alias declared at the top of the file; the SELECT statement body produces the output. Spark SQL (a superset of ANSI SQL) is the execution dialect.

### 3. Compute engine selection

Python transforms support two execution modes selected at the repository or per-transform level:

| Mode | Runtime | Typical use |
|------|---------|-------------|
| **Single-node** (default) | One worker; data loaded into Polars, pandas, or DuckDB | Small–medium datasets, ML feature prep, local preview |
| **Multi-node (Spark)** | Distributed Spark cluster; data as Spark DataFrame / PySpark | Large datasets, joins across billions of rows |

Java transforms always run on Spark. SQL transforms always run on Spark SQL.

### 4. Incremental processing

By default a transform performs a **full rebuild**: the output dataset is replaced each run. Transforms can opt into **incremental mode**, where only new or changed input rows are processed. In Python this is enabled via the `@incremental` decorator; in Java it requires explicit transaction management. Incremental transforms track a **transaction cursor** against input snapshots, read only the delta since the last successful run, and append or merge results into the output.

### 5. Scheduling and execution

1. A user triggers a build manually, or a **schedule** fires (cron-like, or event-driven on upstream dataset updates).
2. Foundry's job orchestrator resolves the **lineage graph**: it walks upstream dependencies to identify which datasets are stale and which transforms need to re-run.
3. For each transform to run, the platform allocates a Spark cluster (or single-node container), mounts the input dataset snapshots as read-only, and executes the transform code.
4. On success the platform **commits a new transaction** on the output dataset, atomically making the new data visible to downstream consumers. If the job fails, the output dataset is left at its last-successful-transaction state.
5. Lineage, build logs, and profiling metrics are written to the dataset's metadata so they are visible in **Dataset Health** and **Lineage Explorer**.

### 6. Data expectations and validation

Python transforms support **data expectations** — assertions (e.g., non-null checks, range checks) that run as part of the transform execution. Failures can be configured to block the build or emit warnings, providing inline data-quality gating without a separate validation step.

---

## User interface

Transforms are authored and managed across two primary surfaces: **Code Repositories** (the IDE/editor) and **Pipeline Builder** (the visual canvas).

### Code Repositories (editor)

<table style="background:#1C2127;border:1px solid #383E47;border-radius:6px;width:100%;border-collapse:collapse">
<tr style="border-bottom:1px solid #383E47">
<td style="padding:10px 14px;color:#8ABBFF;font-weight:bold;width:30%">Panel / Area</td>
<td style="padding:10px 14px;color:#ABB3BF">What you see</td>
</tr>
<tr style="border-bottom:1px solid #383E47">
<td style="padding:8px 14px;color:#fff"><span style="color:#2D72D2"><b>File tree (left sidebar)</b></span></td>
<td style="padding:8px 14px;color:#ABB3BF">Hierarchical view of the repository: <code>src/</code>, <code>test/</code>, build files. Transforms appear as individual <code>.py</code>, <code>.java</code>, or <code>.sql</code> files.</td>
</tr>
<tr style="border-bottom:1px solid #383E47">
<td style="padding:8px 14px;color:#fff"><span style="color:#2D72D2"><b>Code editor (center)</b></span></td>
<td style="padding:8px 14px;color:#ABB3BF">Monaco-based editor with syntax highlighting, autocomplete for Foundry SDK APIs, inline lint errors, and in-line documentation popups.</td>
</tr>
<tr style="border-bottom:1px solid #383E47">
<td style="padding:8px 14px;color:#fff"><span style="color:#2D72D2"><b>Dataset I/O panel (right)</b></span></td>
<td style="padding:8px 14px;color:#ABB3BF">Lists the transform's declared inputs and outputs; clicking an input navigates to the source dataset. Output aliases show the target dataset RID.</td>
</tr>
<tr>
<td style="padding:8px 14px;color:#fff"><span style="color:#2D72D2"><b>Build / Preview toolbar</b></span></td>
<td style="padding:8px 14px;color:#ABB3BF"><b>Preview</b> runs a lightweight local preview on a sample; <b>Build</b> triggers a full Spark job. Build status chips appear inline.</td>
</tr>
</table>

**Build status chips:**

<span style="color:#238551"><b>● succeeded</b></span> &nbsp;·&nbsp; <span style="color:#C87619"><b>● stale / pending</b></span> &nbsp;·&nbsp; <span style="color:#CD4246"><b>● failed</b></span> &nbsp;·&nbsp; <span style="color:#2D72D2"><b>● running</b></span> &nbsp;·&nbsp; <span style="color:#ABB3BF"><b>● never built</b></span>

### Pipeline Builder (visual canvas)

Pipeline Builder renders the full transform graph as a node-link diagram. Each dataset is a rectangular node; each transform is a node connected by directed edges (data flows left-to-right by convention). You can:

- **Create a new transform** by right-clicking the canvas and choosing a language (Python / Java / SQL / Pipeline Builder no-code transforms such as Join, Union, Filter).
- **Color-group** related nodes with color labels to visually segment pipeline stages.
- **Add text annotations** as floating sticky notes on the canvas.
- **Checkpoint** intermediate datasets to force materialization and break long dependency chains.
- **Search / find-and-replace** across all transform logic in the repository.
- Double-click any transform node to open it directly in Code Repositories.

---

## Worked example

**Scenario**: A logistics team receives daily GPS pings in a raw dataset `gps_pings_raw`. They want a clean, enriched output `gps_pings_clean` that removes nulls, casts timestamps, and adds a derived `distance_km` column.

1. In **Code Repositories**, the team creates a new Python repository and adds `gps_transform.py`:

```python
from transforms.api import transform_df, Input, Output
from pyspark.sql import functions as F

@transform_df(
    Output("/Logistics/gps_pings_clean"),
    raw=Input("/Logistics/gps_pings_raw"),
)
def compute(raw):
    return (
        raw
        .dropna(subset=["lat", "lon", "ts"])
        .withColumn("ts", F.to_timestamp("ts"))
        .withColumn(
            "distance_km",
            F.sqrt(F.pow(F.col("lat") - F.lag("lat").over(...), 2) + ...) * 111.0
        )
    )
```

2. The team clicks **Preview** — Foundry runs the logic on a 1 000-row sample locally and displays a tabular preview of `gps_pings_clean` in seconds.
3. After reviewing the preview schema and row counts, they click **Build** (or commit to trigger a schedule). Foundry allocates a Spark cluster, runs the full transform, and commits a new snapshot of `gps_pings_clean`.
4. In **Pipeline Builder** the team sees the node `gps_pings_raw → gps_transform → gps_pings_clean` with a <span style="color:#238551"><b>● succeeded</b></span> chip on the output node.
5. Downstream consumers (reports, ML models) automatically see the new snapshot without any manual refresh.

---

## Documentation map

The following sub-sections live beneath the Transforms tool in the Palantir docs:

**Python transforms (`transforms-python`)**
- Overview / Getting started
- Basic transforms · Transforms and pipelines · Project structure
- Compute engine selection (single-node vs Spark)
- Incremental transforms — overview, usage guide, abort transactions, historical snapshots
- Polars lazy API · DuckDB API · PySpark (via `transforms-python-spark`)
- Media sets and unstructured data
- Virtual tables and compute pushdown (BigQuery, Databricks, Snowflake)
- Data expectations
- Unit tests · Debugging · Local preview · Local development setup
- Share Python libraries across repositories
- API Reference

**Java transforms (`transforms-java`)**
- Overview · Transforms and pipelines · Project structure
- High-level and low-level Dataset APIs
- Incremental transforms
- User-defined functions
- Read and write unstructured files
- Advanced configuration · Spark syntax cheat sheet
- Share code across repositories
- Unit tests · Local development

**SQL transforms (`transforms-sql`)**
- Overview
- Spark SQL Reference (full syntax guide)
- Unit tests

**Pipeline Builder (`pipeline-builder`)**
- Navigation · Tips and tricks
- Transform types: Join, Union, Filter, and more
- Management: folders, color groups, text nodes, checkpoints, job groups, show/hide nodes, find-and-replace, charts

---

## Official documentation

- [Python Transforms — Overview](https://www.palantir.com/docs/foundry/transforms-python/overview)
- [Python Transforms — Basic Transforms](https://www.palantir.com/docs/foundry/transforms-python/transforms)
- [Python Transforms — Transforms and Pipelines](https://www.palantir.com/docs/foundry/transforms-python/transforms-pipelines)
- [Python Transforms — Getting Started](https://www.palantir.com/docs/foundry/transforms-python/getting-started)
- [Python (Spark) — PySpark Overview](https://www.palantir.com/docs/foundry/transforms-python-spark/pyspark-overview)
- [SQL Transforms — Overview](https://www.palantir.com/docs/foundry/transforms-sql/overview)
- [SQL Transforms — Spark SQL Reference](https://www.palantir.com/docs/foundry/transforms-sql/spark-reference)
- [Java Transforms — Overview](https://www.palantir.com/docs/foundry/transforms-java/overview)
- [Java Transforms — Transforms and Pipelines](https://www.palantir.com/docs/foundry/transforms-java/transforms-pipelines)
- [Java Transforms — Incremental Transforms](https://www.palantir.com/docs/foundry/transforms-java/incremental-transforms)
- [Pipeline Builder — Transforms Overview](https://www.palantir.com/docs/foundry/pipeline-builder/transforms-overview)
- [Virtual Tables — Core Concepts](https://www.palantir.com/docs/foundry/data-integration/virtual-tables)
