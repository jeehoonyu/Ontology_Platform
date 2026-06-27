# Datasets, Schemas & Transactions

> A dataset is Foundry's core unit of stored, versioned tabular (or file) data — the input and output of every pipeline and the foundation the Ontology is built on.

## What it is

Almost everything in Foundry flows through datasets. A dataset is a versioned collection of files (often Parquet) with an associated **schema** that describes its columns and types. Every change to a dataset is recorded as a **transaction**, giving you a full, auditable history and the ability to branch, time-travel, and roll back. Datasets are produced by syncs (raw data landing from sources) and by transforms/Pipeline Builder (derived data), and they are consumed by analytics tools, the Ontology, and applications.

## When to use it

- You are ingesting raw data from an external source (lands as a dataset).
- You are producing derived/cleaned data from a transform or pipeline.
- You need versioned, governed, branchable storage for tabular or file data.

**When NOT to use it / alternatives:** For unstructured binary content (images, PDFs, audio) use **media sets**. For real-time low-latency data use **streams**. For referencing external tables without copying, use **virtual tables**.

## Key concepts & terminology

- **Dataset** — A versioned set of files plus a schema.
- **Schema** — Column names and types applied on top of the underlying files.
- **Transaction** — An atomic commit of changes; types: **SNAPSHOT** (replace all), **APPEND** (add rows), **UPDATE**, **DELETE**.
- **Branch** — A parallel line of a dataset's history (default branch is `master`).
- **View** — A logical dataset that points at files/transactions from other datasets.
- **File** — The physical storage unit; a dataset can hold many files/partitions.
- **Build** — The job that produces a new transaction on a dataset.
- **Open/closed transaction** — A transaction is open while being written, closed when committed.

## Core capabilities / features

- **Versioning & history** — Every build is a transaction you can inspect, compare, and roll back to.
- **Branching** — Develop and test changes on a branch before merging to `master`.
- **Schema management** — Schemas can be inferred or explicitly applied; type mismatches surface as errors.
- **Transaction types** — SNAPSHOT for full refresh, APPEND for incremental adds, plus UPDATE/DELETE.
- **File-level access** — Datasets can hold arbitrary files, not just tables, accessible to transforms.
- **Permissions & markings** — Access is governed by project roles and data markings.
- **Details/Preview UI** — Inspect schema, transactions, files, and a sample preview in the dataset application.

## How it works / typical workflow

1. Data **lands as a dataset** via a sync, or is **created by a transform/pipeline**.
2. A **schema** is applied (inferred or explicit).
3. Each build commits a **transaction**; the dataset's history grows.
4. Downstream transforms read the dataset by path or RID and produce new datasets.
5. Object types in the **Ontology** are backed by datasets via object-storage syncs.
6. Analysts explore the dataset in **Contour**, **Code Workbook**, or **Quiver**.

## Example

You ingest a daily CSV from cloud storage:

- A **file-based sync** lands the raw files into `/Project/raw/sales` as **APPEND** transactions (one per day).
- A **transform** reads `/Project/raw/sales`, dedups and types it, and writes `/Project/clean/sales` as a **SNAPSHOT** each run.
- The `Sale` **object type** is backed by `/Project/clean/sales`.
- If a bad build occurs, you **roll back** `clean/sales` to the prior transaction.

## How it connects to the rest of Foundry

- **Data Connection / syncs** — Produce raw datasets from external sources.
- **Transforms / Pipeline Builder** — Read and write datasets.
- **Ontology** — Object types are backed by datasets.
- **Schedules / Data Lineage** — Builds run on schedules; datasets are nodes in the lineage graph.
- **Analytics tools** — Contour, Quiver, and Code Workbook query datasets directly.
- **Security** — Markings and project permissions govern dataset access.

## Tips & gotchas for learners

- **SNAPSHOT replaces everything; APPEND adds.** Mixing them up causes duplicate or missing data.
- **Branches are your safety net** — test schema changes off `master`.
- **Schema drift** from upstream sources is a common failure; add health checks.
- **Datasets vs streams vs media sets** — pick the right storage primitive for the data shape.
- **Roll back is your friend** when a build goes wrong; transactions make it safe.

## Official documentation

- [Data integration: Datasets](https://www.palantir.com/docs/foundry/data-integration/datasets)
- [Data integration: Overview](https://www.palantir.com/docs/foundry/data-integration/overview)
- [Transforms: Overview](https://www.palantir.com/docs/foundry/transforms/overview)
