# Schedules & Builds

> A build is one execution of a pipeline that produces fresh output; a schedule controls when and how often builds run automatically.

## What it is

Foundry pipelines don't run continuously by default — they run as **builds**, and **schedules** are how you automate those builds. A schedule defines a scope (which datasets/pipelines to rebuild), a trigger (time-based cron, or event-based when an input updates), and policies for retries and concurrency. Schedules are what turn a one-time transform into a living pipeline that keeps data fresh.

## When to use it

- You want a pipeline to refresh automatically (hourly, daily, on a cron).
- You want downstream datasets to rebuild whenever an upstream input changes (event-driven).
- You need retry/failure policies for reliable production pipelines.

**When NOT to use it / alternatives:** For ad-hoc, manual experimentation, build on demand from the dataset/repository UI instead. Streaming pipelines run continuously and don't use batch schedules.

## Key concepts & terminology

- **Build** — A single execution producing new output transactions.
- **Schedule** — A configuration that triggers builds automatically.
- **Trigger** — What starts a build: **time-based** (cron) or **event-based** (input updated).
- **Scope / target** — The set of datasets or pipelines a schedule rebuilds.
- **Force build vs incremental** — Whether to rebuild fully or process only new data.
- **Retry policy** — Automatic re-attempts on failure.
- **Job** — The unit of compute work executed during a build.

## Core capabilities / features

- **Time-based triggers** — Cron-style scheduling (e.g., every hour, nightly at 02:00).
- **Event-based triggers** — Rebuild when upstream inputs land new data.
- **Multi-resource scope** — Schedule a whole connected pipeline, not just one dataset.
- **Retries & notifications** — Configure automatic retries and alerts on failure.
- **Concurrency & backpressure controls** — Avoid overlapping or runaway builds.
- **Incremental awareness** — Works with incremental transforms to process only deltas.
- **Monitoring** — Build status and history are visible in Data Lineage and Data Health.

## How it works / typical workflow

1. Build and validate the pipeline on a branch.
2. **Create a schedule** targeting the output dataset(s) or pipeline.
3. Choose a **trigger** — cron time or "when inputs update."
4. Set **retry and notification** policies.
5. **Enable** the schedule; builds now run automatically.
6. Monitor build history and health; tune cadence as needed.

## Example

- A `clean_orders` transform should refresh whenever raw orders land.
- Create a schedule with an **event-based trigger** on `/Project/raw/orders`.
- Add a retry policy (3 attempts) and a failure notification.
- Downstream object-storage sync rebuilds the `Order` object type automatically afterward.

## How it connects to the rest of Foundry

- **Transforms / Pipeline Builder** — Schedules run their builds.
- **Datasets** — Each build commits a new transaction.
- **Data Lineage** — Shows build status and dependencies across scheduled pipelines.
- **Data Health / Observability** — Monitors build success, duration, and freshness.
- **Ontology** — Object-storage syncs are themselves scheduled to keep objects current.

## Tips & gotchas for learners

- **Event-based triggers keep data fresh** without over-running on a fixed clock.
- **Scope schedules to whole pipelines** so dependent datasets rebuild in the right order.
- **Set retries and alerts** — silent failures leave stale data downstream.
- **Avoid over-scheduling** — building every minute wastes compute if data changes hourly.
- **Incremental + schedule** is the efficient combination for large append-only sources.

## Official documentation

- [Building pipelines: Schedules](https://www.palantir.com/docs/foundry/building-pipelines/schedules)
- [Data Lineage: Overview](https://www.palantir.com/docs/foundry/data-lineage/overview)
- [Data integration: Overview](https://www.palantir.com/docs/foundry/data-integration/overview)
