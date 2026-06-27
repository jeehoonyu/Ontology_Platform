<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · DATA INTEGRATION</b><br>
<span style="font-size:22px"><b>Datasets, Schemas &amp; Transactions</b></span><br>
<span style="color:#ABB3BF">The versioned, file-backed storage primitive that carries all tabular data through Foundry pipelines.</span>
</td></tr></table>

## What it is

A **dataset** is the fundamental unit of data storage in Palantir Foundry. At its core it is a wrapper around a collection of files stored in a backing distributed file system (typically Hadoop-compatible object storage). Every piece of data — from raw ingestion to final analytical output — lives in a dataset before it is promoted into the Ontology. Datasets are versioned through an append-only transaction log, queryable through typed schemas, and can be branched for collaborative or experimental development.

## How it works

### 1. Physical storage: files + a transaction log

A dataset does not store rows directly. It stores **files** (Parquet, ORC, CSV, JSON, Avro, or unstructured binary) in a backing file system. A separate, immutable **transaction log** records every modification ever made to those files. The current logical contents of a dataset — called a **view** — are derived by replaying the transaction log up to the latest committed transaction on a given branch.

### 2. Transactions — the write protocol

Every mutation to a dataset follows a strict three-state lifecycle:

1. **OPEN** — A transaction is created (via API or internally by a build engine). While `OPEN`, files can be uploaded into the dataset's storage prefix. Only one transaction per branch can be `OPEN` at a time; a second attempt returns HTTP `409 CONFLICT`.
2. **COMMITTED** — The writer closes the transaction. The new files become visible to all readers on that branch immediately.
3. **ABORTED** — The transaction is discarded. Any files uploaded during the open window are ignored and will be garbage-collected.

There are four **transaction types**, which govern how the committed files interact with the existing view:

| Type | Effect on the view |
|---|---|
| `SNAPSHOT` | Replaces the entire current view with the new set of files. Used by full-refresh batch pipelines. |
| `APPEND` | Adds new files to the existing view without touching prior files. Used for incremental pipelines when inputs have only been appended or additively updated. |
| `UPDATE` | Like `APPEND` but may also overwrite individual existing files (e.g., compaction or partial re-computation). |
| `DELETE` | Removes specific files from the view. |

### 3. Views — point-in-time snapshots

A **dataset view** is the effective file contents of a dataset for a specific branch at a specific transaction. Historical views are addressable by `endTransactionRid`, allowing pipelines and the API to read a dataset as it looked at any past commit that has not been removed by a retention policy. This is the mechanism that enables reproducible builds.

### 4. Schemas — column metadata

A **schema** is metadata stored alongside a dataset view. It records:

- The **parsing class** (e.g., `ParquetDataFrameReader`, `TextDataFrameReader` for CSV)
- A list of **column definitions**: name, nullable flag, and field type
- Complex field types such as `DECIMAL` (needs precision + scale), `MAP` (key type + value type), `ARRAY` (element type), and `STRUCT` (nested sub-schemas)

Schemas are not enforced at write time by the storage layer — they are **interpretive metadata** consumed by the compute engines (Spark, the Dataset Preview renderer, and the SQL engine). Foundry can infer a schema automatically from a sample of CSV or JSON data; structured Parquet files carry their own embedded schema which Foundry reads and promotes.

Schema versions are linked to `endTransactionRid`, so every view has a corresponding schema version; schema history is queryable through the API (`GET /api/v2/datasets/{rid}/schema`).

### 5. Branches — parallel lines of development

Datasets support Git-style **branches**. The default branch is `master`. Every branch maintains its own transaction log pointer. Branches allow:

- **Experimental transforms** to run without polluting the production view
- **Change proposals** in Pipeline Builder to stage output before promoting to master
- **Historical branch creation** from the History tab — pinning a branch to a past `endTransactionRid` for auditing or replay

Merging a branch writes a new transaction on the target branch containing all the delta files from the source branch.

### 6. Builds — the automated write path

A **build** is the Foundry scheduler's execution of a transform (Pipeline Builder node or Code Repository transform). When a build runs:

1. The build engine opens a transaction on the output dataset.
2. The transform computes and writes output files into the open transaction's storage prefix.
3. If computation succeeds the transaction is committed (`COMMITTED`); if it fails the transaction is aborted (`ABORTED`), leaving the dataset unchanged.
4. Downstream datasets are marked **stale** and eligible for their own builds. The scheduler will skip a build if all target datasets are already up-to-date relative to their inputs.

The default write mode is `APPEND` when all incremental inputs have only had `APPEND` or additive `UPDATE` transactions since the last build; otherwise it falls back to `SNAPSHOT`.

---

## User interface

Dataset Preview is the primary in-platform UI for inspecting datasets. It is launched from any dataset node in Data Lineage, Pipeline Builder, or the file browser.

### Overall layout

<table style="background:#1C2127;border:1px solid #383E47;border-radius:6px;width:100%;border-collapse:collapse">
<tr style="border-bottom:1px solid #383E47">
<td style="padding:8px 12px;color:#8ABBFF;font-weight:bold;width:22%">Area</td>
<td style="padding:8px 12px;color:#8ABBFF;font-weight:bold">What you see / can do</td>
</tr>
<tr style="border-bottom:1px solid #383E47">
<td style="padding:8px 12px;color:#FFFFFF"><b>Top bar</b></td>
<td style="padding:8px 12px;color:#ABB3BF">Dataset name, branch selector (defaults to <code>master</code>), build status chip, and action buttons (Build, Edit schema, Download).</td>
</tr>
<tr style="border-bottom:1px solid #383E47">
<td style="padding:8px 12px;color:#FFFFFF"><b>Preview tab</b></td>
<td style="padding:8px 12px;color:#ABB3BF">Tabular grid of up to 300 rows sampled from the latest committed view. Column headers show the inferred type. A <i>Search columns…</i> field filters the column list on the right-hand panel.</td>
</tr>
<tr style="border-bottom:1px solid #383E47">
<td style="padding:8px 12px;color:#FFFFFF"><b>Columns panel</b></td>
<td style="padding:8px 12px;color:#ABB3BF">Per-column stats: field type, description, % null values, value distribution histogram, and sample values.</td>
</tr>
<tr style="border-bottom:1px solid #383E47">
<td style="padding:8px 12px;color:#FFFFFF"><b>Schema tab</b></td>
<td style="padding:8px 12px;color:#ABB3BF">Full schema definition (all columns, types, nullable flags). <span style="color:#2D72D2"><b>Edit schema</b></span> button opens an inline editor; <i>Infer schema</i> auto-populates from a CSV/JSON sample.</td>
</tr>
<tr style="border-bottom:1px solid #383E47">
<td style="padding:8px 12px;color:#FFFFFF"><b>History tab</b></td>
<td style="padding:8px 12px;color:#ABB3BF">Chronological list of committed transactions (build jobs) with timestamps, transaction type, and row counts. From any row you can <span style="color:#2D72D2"><b>Create branch</b></span> to pin that historical view.</td>
</tr>
<tr style="border-bottom:1px solid #383E47">
<td style="padding:8px 12px;color:#FFFFFF"><b>Files tab</b></td>
<td style="padding:8px 12px;color:#ABB3BF">Raw file listing for the current view's storage prefix. Allows individual file download.</td>
</tr>
<tr>
<td style="padding:8px 12px;color:#FFFFFF"><b>SQL (Code) tab</b></td>
<td style="padding:8px 12px;color:#ABB3BF">Read-only Spark SQL editor. Supports joins across datasets (reference another dataset by name in backticks). Results streamed back inline.</td>
</tr>
</table>

### Status chips

<span style="color:#238551"><b>● up to date</b></span> — dataset view is current with all inputs &nbsp;·&nbsp;
<span style="color:#C87619"><b>● stale</b></span> — one or more inputs have newer transactions &nbsp;·&nbsp;
<span style="color:#CD4246"><b>● build failed</b></span> — last transaction was aborted &nbsp;·&nbsp;
<span style="color:#2D72D2"><b>● building</b></span> — open transaction in progress

---

## Worked example

**Scenario:** A CSV file lands daily from an external system via Data Connection. A Python transform enriches it and writes results to an output dataset consumed by an Ontology object type.

1. **Ingestion.** Data Connection opens a `SNAPSHOT` transaction on `raw_orders` and uploads the daily CSV as a single Parquet file, then commits. The dataset now has one committed transaction; its schema (inferred on first sync) maps 12 columns with their types.

2. **Transform build triggered.** The `orders_enriched` dataset is downstream of `raw_orders`. Because `raw_orders` just received a new `SNAPSHOT` transaction, `orders_enriched` is now **stale**. The daily schedule fires and the Spark build opens a new transaction on `orders_enriched`.

3. **Compute.** The Python transform reads `raw_orders` at its latest `endTransactionRid`, joins with a reference dataset (`product_catalog`), and writes enriched Parquet files into the open transaction's storage prefix. Because the upstream transaction was a `SNAPSHOT`, the output defaults to `SNAPSHOT` as well, replacing the prior view entirely.

4. **Commit.** The build engine commits the transaction. Dataset Preview now shows the refreshed 300-row sample, updated column stats, and a new entry in the History tab.

5. **Ontology sync.** The Ontology object type backed by `orders_enriched` re-indexes, making updated order objects available to application users within minutes.

6. **Audit.** A data steward notices an anomaly in the new build. They open the History tab, find the prior transaction, and click **Create branch** → `audit/2026-06-05`. They can now inspect the old view alongside the new one without affecting production.

---

## Documentation map

The following sub-pages live beneath Datasets in the Foundry docs:

- **Core concepts / Datasets** — primary reference (files, transactions, views, schemas, branches)
- **Core concepts / Branching** — branch creation, merging, change proposals, protected branches
- **Core concepts / Builds** — build lifecycle, stale detection, schedule triggers
- **Core concepts / Schedules** — cron-based and trigger-based schedule configuration
- **Core concepts / Views** — how views are computed from the transaction log
- **Core concepts / Change data capture (CDC)** — incremental update patterns
- **Core concepts / Virtual tables** — computed views without materialising files
- **Dataset Preview / Overview** — the Preview, Schema, History, Files, and SQL tabs
- **Dataset Preview / CSV parsing** — `TextDataFrameReader` configuration and dialect options
- **Dataset Preview / FAQ** — common questions about row limits, schema inference, and permissions
- **Building pipelines / Infer a schema for CSV or JSON files** — `Apply a schema` workflow
- **API Reference / Datasets / Transactions** — `Create`, `Commit`, `Abort`, `Get` transaction endpoints
- **API Reference / Datasets / Get Dataset Schema** — `GET /api/v2/datasets/{rid}/schema`
- **API Reference / Datasets / Put Dataset Schema** — `PUT /api/v2/datasets/{rid}/schema`

---

## Official documentation

- [Core concepts · Datasets](https://www.palantir.com/docs/foundry/data-integration/datasets)
- [Core concepts · Branching](https://www.palantir.com/docs/foundry/data-integration/branching)
- [Dataset Preview · Overview](https://www.palantir.com/docs/foundry/dataset-preview/overview)
- [Dataset Preview · SQL preview](https://www.palantir.com/docs/foundry/dataset-preview/sql-preview)
- [API Reference · Create Transaction](https://www.palantir.com/docs/foundry/api/datasets-resources/transactions/create-transaction)
- [API Reference · Get Dataset Schema](https://www.palantir.com/docs/foundry/api/datasets-v2-resources/datasets/get-dataset-schema)
- [Pipeline Builder · Add a dataset output](https://www.palantir.com/docs/foundry/pipeline-builder/outputs-add-dataset-output)
- [Building pipelines · Infer a schema](https://www.palantir.com/docs/foundry/building-pipelines/infer-schema)
