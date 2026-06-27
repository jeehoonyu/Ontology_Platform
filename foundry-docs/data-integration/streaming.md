# Streaming & Streams

> Streams are Foundry's primitive for low-latency, continuously-arriving data; streaming syncs and streaming pipelines process records in near real time rather than in scheduled batches.

## What it is

Most Foundry data is processed in batch — a schedule triggers a build that processes a bounded dataset. Streaming is the alternative for data that must be acted on within seconds: sensor readings, transactions, events, telemetry. A **stream** is an append-only topic of records. **Streaming syncs** ingest from message brokers (Kafka and similar) into streams, **streaming pipelines** (in Pipeline Builder) transform them continuously, and results can drive the Ontology, alerts, and operational apps with minimal delay. Streams can also be archived to datasets for historical analysis.

## When to use it

- Latency matters — you need results in seconds, not on the next batch build.
- The source pushes continuous events (IoT, message brokers, real-time APIs).
- You want real-time monitoring, alerting, or Ontology updates.

**When NOT to use it / alternatives:** If hourly/daily freshness is fine, batch datasets and schedules are simpler and cheaper. Streaming adds operational complexity (always-on compute, state, windowing).

## Key concepts & terminology

- **Stream** — An append-only, continuously-updated topic of records.
- **Streaming sync** — Ingests records from an external broker into a stream.
- **Streaming pipeline** — A Pipeline Builder pipeline in streaming mode that transforms records continuously.
- **Windowing** — Grouping streaming records by time windows for aggregation.
- **Latency** — The delay between a record arriving and being processed/available.
- **Archival** — Writing stream contents to a dataset for historical/batch use.
- **Checkpoint / state** — Internal progress and aggregation state a streaming job maintains.

## Core capabilities / features

- **Near real-time processing** — Sub-second to seconds latency end to end.
- **Streaming syncs** — Connect to Kafka-style brokers and other real-time sources.
- **Streaming transforms** — Filter, enrich, join, and aggregate with windowing in Pipeline Builder.
- **Ontology integration** — Update object types in near real time from a stream.
- **Archival to datasets** — Persist stream history for batch analytics and replay.
- **Monitoring** — Track lag, throughput, and failures via observability tools.

## How it works / typical workflow

1. Configure a streaming **source** (e.g., Kafka) in Data Connection.
2. Create a **streaming sync** into a stream.
3. Build a **streaming pipeline** to transform/enrich the records.
4. Write outputs to a **stream**, a **dataset (archive)**, or the **Ontology**.
5. Drive **alerts/automations** off the live results.
6. Monitor lag and throughput; archive for historical analysis.

## Example

A fraud-monitoring flow:

1. Card transactions arrive on a Kafka topic.
2. A streaming sync lands them in a `transactions` stream.
3. A streaming pipeline flags transactions over a threshold within a 5-minute window.
4. Flagged events update a `SuspiciousTransaction` object type.
5. **Automate** sends an alert to analysts in Workshop within seconds.

## How it connects to the rest of Foundry

- **Data Connection** — Streaming sources/syncs feed streams.
- **Pipeline Builder** — Authors streaming pipelines.
- **Ontology** — Streams can update object types in near real time.
- **Datasets** — Streams archive to datasets for history.
- **Automate / Observability** — Real-time results drive automations and are monitored for lag.

## Tips & gotchas for learners

- **Streaming ≠ frequent batch.** Don't simulate streaming with minute-by-minute batch syncs at scale.
- **Windowing semantics matter** — late/out-of-order events need careful handling.
- **Always-on compute** means streaming pipelines cost continuously, unlike scheduled batch.
- **Archive streams** if you'll ever need to reprocess or analyze history.
- **Monitor lag** — a backed-up stream silently delays everything downstream.

## Official documentation

- [Data integration: Streaming](https://www.palantir.com/docs/foundry/data-integration/streaming)
- [Pipeline Builder: Overview](https://www.palantir.com/docs/foundry/pipeline-builder/overview)
- [Data integration: Overview](https://www.palantir.com/docs/foundry/data-integration/overview)
