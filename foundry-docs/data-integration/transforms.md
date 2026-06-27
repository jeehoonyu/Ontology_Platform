# Transforms (Python / Java / SQL)

> A transform is code that reads one or more input datasets, processes them, and writes output datasets — the code-first way to build Foundry data pipelines in Code Repositories.

## What it is

Transforms are the programmatic counterpart to Pipeline Builder. You write them in **Code Repositories** using the Foundry **Transforms API** (most commonly Python with PySpark, also Java and SQL). Each transform declares its inputs and outputs explicitly, so Foundry can build a dependency graph, schedule rebuilds, and track lineage automatically. Transforms give you the full power of a real programming language — libraries, unit tests, reusable functions — for logic that is too complex or too custom for the visual builder.

## When to use it

- Logic is complex, reusable, or needs unit tests and code review.
- You need libraries or algorithms not available as visual nodes.
- You want fine-grained control over performance (partitioning, incremental logic).
- You are migrating existing Python/Spark/SQL code into Foundry.

**When NOT to use it / alternatives:** For straightforward cleaning/joining, **Pipeline Builder** is faster and needs no code. For interactive, exploratory analysis use **Code Workbook**.

## Key concepts & terminology

- **Transform** — A function that maps input datasets to output datasets.
- **Transforms API** — The Foundry library (`transforms.api`) providing `@transform`, `@transform_df`, `Input`, `Output`.
- **Input / Output** — Decorator-declared references to datasets, enabling automatic dependency tracking.
- **Incremental transform** — A transform that processes only new/changed rows since the last build using `@incremental`.
- **Build** — One execution of a transform that produces an output transaction.
- **Transaction** — An atomic write to a dataset (SNAPSHOT, APPEND, UPDATE, DELETE).
- **Spark profile** — The compute resource configuration for a transform.
- **Virtual tables** — Referencing external tables with pushdown rather than copying data into Foundry.

## Core capabilities / features

- **Multiple languages** — Python (PySpark/pandas), Java, and SQL transforms.
- **Declarative I/O** — Inputs/outputs declared via decorators; the dependency graph and lineage are derived automatically.
- **Incremental computation** — `@incremental` processes only new data, dramatically cutting compute on large append-only sources.
- **Spark configuration** — Tune executors, memory, and partitioning via Spark profiles.
- **Unit testing & checks** — Write tests and data-quality checks that run in CI on every branch.
- **Branching & code review** — Git-backed branches, pull requests, and automated checks before merge.
- **Reusable code** — Share helper modules and publish libraries across repositories.

## How it works / typical workflow

1. Create or open a **Code Repository** (Python transforms template).
2. Author a transform that declares inputs and outputs.
3. Use the **preview/build on a branch** to test against real data.
4. Add **unit tests and checks**; let CI validate the branch.
5. Open a **pull request**, get review, and merge to the default branch.
6. Attach a **schedule** so the output rebuilds automatically.
7. Track builds and dependencies in **Data Lineage**.

## Example

A minimal Python transform:

```python
from transforms.api import transform_df, Input, Output
from pyspark.sql import functions as F

@transform_df(
    Output("/Project/clean/orders_clean"),
    raw=Input("/Project/raw/orders"),
)
def compute(raw):
    return (
        raw
        .filter(F.col("status") == "COMPLETED")
        .withColumn("order_total", F.col("quantity") * F.col("unit_price"))
    )
```

This reads `orders`, filters to completed orders, adds a computed column, and writes `orders_clean`.

## How it connects to the rest of Foundry

- **Code Repositories** — The authoring environment for transforms.
- **Datasets** — Transforms read and write datasets and create transactions.
- **Pipeline Builder** — A no-code alternative that compiles to the same kind of jobs.
- **Schedules / Data Lineage** — Transforms build on schedules and appear in the lineage graph.
- **Ontology** — Transform outputs commonly back object types.
- **Functions** — Different concept: Functions serve interactive/Ontology logic; transforms produce datasets.

## Tips & gotchas for learners

- **Declare every input/output** — undeclared reads break lineage and scheduling.
- **Prefer incremental** for large append-only sources to save compute and time.
- **SNAPSHOT vs APPEND** transactions change downstream behavior — choose deliberately.
- **Test on a branch first**; never iterate directly on the default branch.
- **Transforms ≠ Functions.** Transforms build datasets in batch; Functions run logic on objects at query/action time.

## Official documentation

- [Transforms: Overview](https://www.palantir.com/docs/foundry/transforms/overview)
- [Code Repositories: Overview](https://www.palantir.com/docs/foundry/code-repositories/overview)
- [Data integration: Overview](https://www.palantir.com/docs/foundry/data-integration/overview)
